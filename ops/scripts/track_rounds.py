#!/usr/bin/env python3
"""Minimal read-only PEPEPOW round tracker script.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_timestamp(ts: Any) -> datetime:
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def tail_file(file_path: Path, max_lines: int) -> list[str]:
    if not file_path.exists():
        return []
    chunk_size = 4096
    lines: list[str] = []
    with file_path.open("rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        position = file_size
        buffer = b""
        while position > 0 and len(lines) <= max_lines:
            grab_size = min(chunk_size, position)
            position -= grab_size
            f.seek(position)
            chunk = f.read(grab_size)
            buffer = chunk + buffer
            lines = buffer.split(b"\n")
            if len(lines) > max_lines + 1:
                lines = lines[-(max_lines + 1):]
                buffer = b"\n".join(lines)
                break
    return [line.decode("utf-8", errors="replace") for line in lines if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--accepted-candidates",
        type=str,
        required=True,
        help="Path to accepted-candidates.json",
    )
    parser.add_argument(
        "--share-log",
        type=str,
        default=None,
        help="Path to share-events.jsonl",
    )
    parser.add_argument(
        "--activity-snapshot",
        type=str,
        default=None,
        help="Path to activity-snapshot.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to output rounds-snapshot.json",
    )
    parser.add_argument(
        "--max-share-lines",
        type=int,
        default=10000,
        help="Max lines of share events to process from tail",
    )
    parser.add_argument(
        "--min-share-difficulty",
        type=float,
        default=None,
        help="Minimum difficulty floor for shares",
    )
    args = parser.parse_args()

    # Load accepted candidates
    cand_path = Path(args.accepted_candidates)
    if not cand_path.exists():
        print(f"Error: accepted-candidates not found at {cand_path}", file=sys.stderr)
        return 1

    try:
        with cand_path.open("r", encoding="utf-8") as f:
            cand_data = json.load(f)
        candidates = cand_data.get("accepted_candidates", [])
    except Exception as exc:
        print(f"Error loading candidates: {exc}", file=sys.stderr)
        return 1

    # Load activity snapshot to find assumed share difficulty if not passed
    min_diff = args.min_share_difficulty
    if min_diff is None and args.activity_snapshot:
        act_path = Path(args.activity_snapshot)
        if act_path.exists():
            try:
                with act_path.open("r", encoding="utf-8") as f:
                    act_data = json.load(f)
                meta = act_data.get("meta", {})
                assumed_diff = meta.get("assumedShareDifficulty")
                if assumed_diff is not None:
                    min_diff = float(assumed_diff)
            except Exception:
                pass
    if min_diff is None:
        min_diff = 0.00000001

    # Read and parse shares from tail of share-events.jsonl
    shares: list[dict[str, Any]] = []
    if args.share_log:
        share_log_path = Path(args.share_log)
        if share_log_path.exists():
            tail_lines = tail_file(share_log_path, args.max_share_lines)
            for line in tail_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Exclude malformed

                # Validation checks:
                # 1. Exclude rejected
                accepted = payload.get("accepted")
                if accepted is not True:
                    # check for status/result/outcome
                    status = payload.get("status")
                    result = payload.get("result")
                    outcome = payload.get("outcome")
                    is_accepted = False
                    for val in (status, result, outcome):
                        if isinstance(val, str) and val.strip().lower() in {
                            "accepted",
                            "ok",
                            "valid",
                            "share-accepted",
                        }:
                            is_accepted = True
                            break
                    if not is_accepted:
                        continue

                # 2. Exclude malformed (missing wallet/login or timestamp)
                wallet = payload.get("wallet") or payload.get("login")
                if not wallet or not isinstance(wallet, str):
                    continue

                # Resolve wallet if login was used (e.g. login is wallet.worker)
                wallet = wallet.strip()
                if "." in wallet and not payload.get("wallet"):
                    wallet = wallet.split(".", 1)[0].strip()
                if not wallet:
                    continue

                ts_raw = (
                    payload.get("timestamp")
                    or payload.get("submittedAt")
                    or payload.get("observedAt")
                )
                if not ts_raw:
                    continue
                ts = parse_timestamp(ts_raw)
                if ts == datetime.min.replace(tzinfo=timezone.utc):
                    continue

                # 3. Exclude low-difficulty
                submit_payload = payload.get("submit")
                diff = None
                if isinstance(submit_payload, dict):
                    diff = submit_payload.get("difficulty")
                if diff is None:
                    # fallback to top level difficulty
                    diff = payload.get("difficulty")

                try:
                    diff_val = float(diff) if diff is not None else 0.0
                except (ValueError, TypeError):
                    continue  # Malformed difficulty

                if diff_val < min_diff:
                    continue  # Exclude low difficulty

                shares.append(
                    {"wallet": wallet, "timestamp": ts, "difficulty": diff_val}
                )

    # Filter candidates to only those matched on-chain (rounds)
    round_statuses = {"chain_match_found", "immature", "confirmed", "orphan"}
    round_cands = [
        c
        for c in candidates
        if c.get("lifecycle_status") in round_statuses
    ]

    # Sort rounds chronologically by submit timestamp
    def cand_key(c):
        return parse_timestamp(c.get("submit_timestamp"))

    round_cands.sort(key=cand_key)

    # Compute rounds and attribute shares
    rounds_list = []
    for i, c in enumerate(round_cands):
        c_ts = parse_timestamp(c.get("submit_timestamp"))
        if i == 0:
            start_ts = datetime.min.replace(tzinfo=timezone.utc)
        else:
            start_ts = parse_timestamp(
                round_cands[i - 1].get("submit_timestamp")
            )

        # Attribute shares in range (start_ts, c_ts]
        attributed_shares: dict[str, float] = {}
        for s in shares:
            s_ts = s["timestamp"]
            if start_ts < s_ts <= c_ts:
                wallet = s["wallet"]
                attributed_shares[wallet] = (
                    attributed_shares.get(wallet, 0.0) + s["difficulty"]
                )

        status = c.get("lifecycle_status")
        round_item = {
            "round_id": c.get("candidate_hash"),
            "candidate_hash": c.get("candidate_hash"),
            "height": c.get("matched_height"),
            "status": status,
            "submit_timestamp": c.get("submit_timestamp"),
            "confirmations": c.get("confirmations"),
            "shares": attributed_shares,
            "total_shares": sum(attributed_shares.values()),
        }

        # Immature / orphan / chain_match_found safety
        if status in {"immature", "orphan", "chain_match_found"}:
            round_item["payable"] = False
        # Confirmed safety: confirmed rounds do NOT expose balance/payable fields at all
        # (meaning we do NOT put "payable" or "balance" in confirmed rounds)

        rounds_list.append(round_item)

    output_data = {
        "updated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "rounds": rounds_list,
    }

    try:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, sort_keys=True)
        print(
            f"Successfully tracked {len(rounds_list)} rounds, output saved to {output_path}"
        )
    except Exception as exc:
        print(f"Error saving output to {args.output}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

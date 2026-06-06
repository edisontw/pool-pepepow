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
    newline_count = 0
    with file_path.open("rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        position = file_size
        needed_newlines = max_lines + 1
        while position > 0 and newline_count < needed_newlines:
            grab_size = min(chunk_size, position)
            position -= grab_size
            f.seek(position)
            chunk = f.read(grab_size)
            newline_count += chunk.count(b"\n")
        f.seek(position)
        rest = f.read()
        lines = rest.split(b"\n")
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
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

                # Resolve wallet and worker if login was used (e.g. login is wallet.worker)
                wallet = wallet.strip()
                worker = payload.get("worker")
                if "." in wallet and not payload.get("wallet"):
                    parts = wallet.split(".", 1)
                    wallet = parts[0].strip()
                    if len(parts) > 1 and not worker:
                        worker = parts[1].strip()

                if not worker and payload.get("login") and "." in payload.get("login"):
                    parts = payload.get("login").split(".", 1)
                    if len(parts) > 1:
                        worker = parts[1].strip()

                if not worker:
                    worker = "default"

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
                    {
                        "wallet": wallet,
                        "worker": worker,
                        "timestamp": ts,
                        "difficulty": diff_val,
                    }
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
        attributed_shares: dict[str, Any] = {}
        unique_workers_in_round = set()
        total_round_shares = 0
        total_round_score = 0.0

        for s in shares:
            s_ts = s["timestamp"]
            if start_ts < s_ts <= c_ts:
                wallet = s["wallet"]
                worker = s["worker"]
                diff = s["difficulty"]

                if wallet not in attributed_shares:
                    attributed_shares[wallet] = {
                        "share_count": 0,
                        "share_score": 0.0,
                        "workers": {}
                    }

                wallet_data = attributed_shares[wallet]
                wallet_data["share_count"] += 1
                wallet_data["share_score"] += diff

                if worker not in wallet_data["workers"]:
                    wallet_data["workers"][worker] = {
                        "share_count": 0,
                        "share_score": 0.0
                    }

                worker_data = wallet_data["workers"][worker]
                worker_data["share_count"] += 1
                worker_data["share_score"] += diff

                unique_workers_in_round.add((wallet, worker))
                total_round_shares += 1
                total_round_score += diff

        # Annotate share_percent and wallet_share_percent after all shares are tallied
        for wallet_addr, wallet_data in attributed_shares.items():
            w_score = wallet_data["share_score"]
            wallet_data["share_percent"] = (
                round(w_score / total_round_score * 100, 6)
                if total_round_score > 0
                else 0.0
            )
            for worker_name, worker_data in wallet_data["workers"].items():
                wk_score = worker_data["share_score"]
                worker_data["share_percent"] = (
                    round(wk_score / total_round_score * 100, 6)
                    if total_round_score > 0
                    else 0.0
                )
                worker_data["wallet_share_percent"] = (
                    round(wk_score / w_score * 100, 6)
                    if w_score > 0
                    else 0.0
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
            "total_share_count": total_round_shares,
            "total_share_score": total_round_score,
            "wallet_count": len(attributed_shares),
            "worker_count": len(unique_workers_in_round),
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

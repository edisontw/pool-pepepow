#!/usr/bin/env python3
"""Minimal read-only PEPEPOW round tracker script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_right
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


def share_log_segments(active_log_path: Path) -> list[Path]:
    parent = active_log_path.parent
    if not parent.exists():
        return []

    pattern = re.compile(
        rf"^{re.escape(active_log_path.stem)}\."
        r"(?P<first>\d{20})-(?P<last>\d{20})"
        rf"{re.escape(active_log_path.suffix)}$"
    )
    rotated: list[tuple[int, int, str, Path]] = []
    for path in parent.iterdir():
        if not path.is_file():
            continue
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        rotated.append(
            (
                int(match.group("first")),
                int(match.group("last")),
                path.name,
                path,
            )
        )

    paths = [item[3] for item in sorted(rotated)]
    if active_log_path.exists():
        paths.append(active_log_path)
    return paths


def tail_share_log_segments(active_log_path: Path, max_lines: int) -> tuple[list[str], int]:
    if max_lines <= 0:
        return [], 0

    selected: list[str] = []
    segments = share_log_segments(active_log_path)
    for path in reversed(segments):
        remaining = max_lines - len(selected)
        if remaining <= 0:
            break
        segment_lines = tail_file(path, remaining)
        if segment_lines:
            selected = segment_lines + selected

    if len(selected) > max_lines:
        selected = selected[-max_lines:]
    return selected, len(segments)


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
        default=100000,
        help="Max lines of share events to process from tail",
    )
    parser.add_argument(
        "--min-share-difficulty",
        type=float,
        default=None,
        help="Minimum difficulty floor for shares",
    )
    args = parser.parse_args()
    output_path = Path(args.output)

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

    existing_rounds_by_hash: dict[str, dict[str, Any]] = {}
    if output_path.exists():
        try:
            with output_path.open("r", encoding="utf-8") as f:
                existing_data = json.load(f)
            if isinstance(existing_data, dict) and isinstance(existing_data.get("rounds"), list):
                for item in existing_data["rounds"]:
                    if not isinstance(item, dict):
                        continue
                    candidate_hash = item.get("candidate_hash") or item.get("round_id")
                    if candidate_hash:
                        existing_rounds_by_hash[str(candidate_hash)] = item
        except Exception:
            existing_rounds_by_hash = {}

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

    max_share_lines = max(0, int(args.max_share_lines))

    # Read and parse shares from tail of share-events.jsonl
    shares: list[dict[str, Any]] = []
    tail_lines: list[str] = []
    share_log_segment_count = 0
    if args.share_log:
        share_log_path = Path(args.share_log)
        if share_log_path.exists() or share_log_path.parent.exists():
            tail_lines, share_log_segment_count = tail_share_log_segments(
                share_log_path,
                max_share_lines,
            )
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

    shares.sort(key=lambda s: s["timestamp"])
    share_timestamps = [s["timestamp"] for s in shares]
    earliest_share_ts = min(share_timestamps) if share_timestamps else None
    latest_share_ts = max(share_timestamps) if share_timestamps else None

    # Filter candidates to only those matched on-chain (rounds)
    round_statuses = {"chain_match_found", "immature", "confirmed", "orphan"}
    round_cands = [
        c
        for c in candidates
        if c.get("lifecycle_status") in round_statuses
    ]
    boundary_cands = [
        c
        for c in round_cands
        if c.get("lifecycle_status") != "orphan"
    ]

    # Sort rounds chronologically by submit timestamp
    def cand_key(c):
        return parse_timestamp(c.get("submit_timestamp"))

    round_cands.sort(key=cand_key)

    def attribution_for(
        status: str | None,
        total_shares: int,
        candidate_ts: datetime,
    ) -> tuple[str, str | None]:
        if total_shares > 0:
            return "ok", None
        if not tail_lines:
            return "incomplete", "no_share_log_loaded"
        if (
            status == "confirmed"
            and earliest_share_ts is not None
            and candidate_ts < earliest_share_ts
        ):
            return "incomplete", "share_log_tail_too_short"
        return "empty", "no_shares_in_round_window"

    preserved_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Compute rounds and attribute shares
    rounds_list = []
    previous_boundary_ts = datetime.min.replace(tzinfo=timezone.utc)
    for i, c in enumerate(round_cands):
        c_ts = parse_timestamp(c.get("submit_timestamp"))
        if c.get("lifecycle_status") == "orphan":
            if i == 0:
                start_ts = datetime.min.replace(tzinfo=timezone.utc)
            else:
                start_ts = parse_timestamp(
                    round_cands[i - 1].get("submit_timestamp")
                )
        else:
            start_ts = previous_boundary_ts
            previous_boundary_ts = c_ts

        # Attribute shares in range (start_ts, c_ts]
        attributed_shares: dict[str, Any] = {}
        unique_workers_in_round = set()
        total_round_shares = 0
        total_round_score = 0.0

        start_idx = bisect_right(share_timestamps, start_ts)
        end_idx = bisect_right(share_timestamps, c_ts)
        for s in shares[start_idx:end_idx]:
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
        attribution_status, attribution_reason = attribution_for(
            status,
            total_round_shares,
            c_ts,
        )
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
            "attribution_status": attribution_status,
            "attribution_reason": attribution_reason,
        }

        existing_round = existing_rounds_by_hash.get(str(c.get("candidate_hash")))
        if (
            total_round_shares == 0
            and attribution_reason == "share_log_tail_too_short"
            and isinstance(existing_round, dict)
        ):
            try:
                existing_share_count = int(existing_round.get("total_share_count") or 0)
            except (TypeError, ValueError):
                existing_share_count = 0
            existing_shares = existing_round.get("shares")
            if existing_share_count > 0 and isinstance(existing_shares, dict):
                round_item["shares"] = existing_shares
                round_item["total_share_count"] = existing_share_count
                try:
                    round_item["total_share_score"] = float(existing_round.get("total_share_score") or 0.0)
                except (TypeError, ValueError):
                    round_item["total_share_score"] = 0.0
                try:
                    round_item["wallet_count"] = int(existing_round.get("wallet_count") or len(existing_shares))
                except (TypeError, ValueError):
                    round_item["wallet_count"] = len(existing_shares)
                try:
                    round_item["worker_count"] = int(existing_round.get("worker_count") or 0)
                except (TypeError, ValueError):
                    round_item["worker_count"] = 0
                round_item["attribution_status"] = "preserved"
                round_item["attribution_reason"] = "preserved_existing_attribution_after_tail_short"
                round_item["attribution_preserved"] = True
                round_item["attribution_preserved_at"] = preserved_now

        # Immature / orphan / chain_match_found safety
        if status in {"immature", "orphan", "chain_match_found"}:
            round_item["payable"] = False
        # Confirmed safety: confirmed rounds do NOT expose balance/payable fields at all
        # (meaning we do NOT put "payable" or "balance" in confirmed rounds)

        rounds_list.append(round_item)

    preserved_round_attribution_count = sum(
        1
        for item in rounds_list
        if item.get("attribution_preserved") is True
    )
    incomplete_confirmed_round_count = sum(
        1
        for item in rounds_list
        if item.get("status") == "confirmed" and item.get("attribution_status") == "incomplete"
    )
    empty_confirmed_round_count = sum(
        1
        for item in rounds_list
        if item.get("status") == "confirmed" and item.get("attribution_status") == "empty"
    )
    output_data = {
        "updated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "shareLogLinesRead": len(tail_lines),
        "shareLogSegmentCount": share_log_segment_count,
        "parsedAcceptedShares": len(shares),
        "earliestShareTimestamp": (
            earliest_share_ts.isoformat().replace("+00:00", "Z")
            if earliest_share_ts is not None
            else None
        ),
        "latestShareTimestamp": (
            latest_share_ts.isoformat().replace("+00:00", "Z")
            if latest_share_ts is not None
            else None
        ),
        "roundBoundaryCount": len(boundary_cands),
        "preservedRoundAttributionCount": preserved_round_attribution_count,
        "incompleteConfirmedRoundCount": incomplete_confirmed_round_count,
        "emptyConfirmedRoundCount": empty_confirmed_round_count,
        "maxShareLines": max_share_lines,
        "rounds": rounds_list,
    }

    try:
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

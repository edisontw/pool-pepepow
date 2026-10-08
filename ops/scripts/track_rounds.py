#!/usr/bin/env python3
"""Minimal read-only PEPEPOW round tracker script.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
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


def analyze_share_source(lines: list[str], paths: list[Path], max_lines: int) -> dict[str, Any]:
    """Describe whether the loaded event stream has detectable holes or truncation."""
    rotated_ranges: list[tuple[int, int]] = []
    pattern = re.compile(r"^share-events\.(\d{20})-(\d{20})\.jsonl$")
    for path in paths:
        match = pattern.fullmatch(path.name)
        if match:
            rotated_ranges.append((int(match.group(1)), int(match.group(2))))
    rotated_ranges.sort()
    segments_contiguous = all(
        current[0] == previous[1] + 1
        for previous, current in zip(rotated_ranges, rotated_ranges[1:])
    )

    timestamps: list[datetime] = []
    sequences: list[int] = []
    missing_sequence_count = 0
    malformed_rows = 0
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed_rows += 1
            continue
        timestamp = parse_timestamp(
            item.get("timestamp") or item.get("submittedAt") or item.get("observedAt")
        ) if isinstance(item, dict) else datetime.min.replace(tzinfo=timezone.utc)
        if timestamp == datetime.min.replace(tzinfo=timezone.utc):
            malformed_rows += 1
        else:
            timestamps.append(timestamp)
        sequence = item.get("sequence") if isinstance(item, dict) else None
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            sequences.append(sequence)
        else:
            missing_sequence_count += 1

    truncated = max_lines <= 0 or len(lines) >= max_lines
    if sequences and not missing_sequence_count:
        sequence_contiguous = all(b == a + 1 for a, b in zip(sequences, sequences[1:]))
        if rotated_ranges:
            sequence_contiguous = sequence_contiguous and sequences[0] == rotated_ranges[0][0]
            sequence_contiguous = sequence_contiguous and all(
                last in sequences for _first, last in rotated_ranges
            )
    elif not sequences and not rotated_ranges:
        # A single unrotated fixture or legacy file can be bounded by its first
        # and last event timestamps. Production Stratum rows also carry sequence.
        sequence_contiguous = True
    else:
        sequence_contiguous = False

    return {
        "first_event_at": min(timestamps).isoformat().replace("+00:00", "Z") if timestamps else None,
        "last_event_at": max(timestamps).isoformat().replace("+00:00", "Z") if timestamps else None,
        "first_sequence": sequences[0] if sequences else None,
        "last_sequence": sequences[-1] if sequences else None,
        "tail_truncated": truncated,
        "segments_contiguous": segments_contiguous,
        "sequence_contiguous": sequence_contiguous,
        "malformed_rows": malformed_rows,
        "complete": bool(lines) and not truncated and segments_contiguous
        and sequence_contiguous and malformed_rows == 0,
    }


def make_window_coverage(
    source: dict[str, Any],
    start_ts: datetime,
    end_ts: datetime,
    candidate_hash: str,
    previous_boundary: str | None,
    window_start_candidate_hash: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    if start_ts == minimum:
        return None, "share_window_start_unbounded"
    if source.get("tail_truncated"):
        return None, "share_log_tail_truncated"
    if not source.get("segments_contiguous"):
        return None, "share_log_segment_gap"
    if not source.get("sequence_contiguous"):
        return None, "share_log_sequence_gap_or_missing_sequence"
    if source.get("malformed_rows"):
        return None, "share_log_malformed_rows"
    if not source.get("complete"):
        return None, "share_log_coverage_unavailable"
    first_event = parse_timestamp(source.get("first_event_at"))
    last_event = parse_timestamp(source.get("last_event_at"))
    if first_event == minimum or start_ts < first_event:
        return None, "share_window_starts_before_retained_events"
    if last_event == minimum or end_ts > last_event:
        return None, "share_window_ends_after_retained_events"
    proof = {
        "status": "complete",
        "candidate_hash": candidate_hash,
        "previous_pool_boundary": previous_boundary,
        "window_start_candidate_hash": window_start_candidate_hash,
        "start_after": start_ts.isoformat().replace("+00:00", "Z"),
        "end_at": end_ts.isoformat().replace("+00:00", "Z"),
        "source_first_event_at": source["first_event_at"],
        "source_last_event_at": source["last_event_at"],
        "source_first_sequence": source.get("first_sequence"),
        "source_last_sequence": source.get("last_sequence"),
        "segments_contiguous": True,
        "sequence_contiguous": True,
        "tail_truncated": False,
        "malformed_rows": 0,
    }
    return proof, None


def attribution_digest(record: dict[str, Any]) -> str:
    payload = {
        key: record.get(key)
        for key in ("candidate_hash", "total_share_count", "total_share_score", "wallet_count", "worker_count", "shares")
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def saved_window_coverage_is_valid(
    proof: Any,
    start_ts: datetime,
    end_ts: datetime,
    candidate_hash: str,
    previous_boundary: str | None,
    window_start_candidate_hash: str | None,
    attribution: dict[str, Any],
) -> bool:
    if not isinstance(proof, dict) or proof.get("status") != "complete":
        return False
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    proof_start = parse_timestamp(proof.get("start_after"))
    proof_end = parse_timestamp(proof.get("end_at"))
    first_event = parse_timestamp(proof.get("source_first_event_at"))
    last_event = parse_timestamp(proof.get("source_last_event_at"))
    return (
        proof.get("candidate_hash") == candidate_hash
        and proof.get("previous_pool_boundary") == previous_boundary
        and proof.get("window_start_candidate_hash") == window_start_candidate_hash
        and proof_start == start_ts
        and proof_end == end_ts
        and first_event != minimum
        and last_event != minimum
        and first_event <= start_ts <= end_ts <= last_event
        and proof.get("segments_contiguous") is True
        and proof.get("sequence_contiguous") is True
        and proof.get("tail_truncated") is False
        and proof.get("malformed_rows") == 0
        and proof.get("attribution_sha256") == attribution_digest(attribution)
    )


def attribution_matches(record: Any, round_item: dict[str, Any]) -> bool:
    if not valid_attribution(record):
        return False
    for field in ("total_share_count", "wallet_count", "worker_count"):
        try:
            if int(record.get(field) or 0) != int(round_item.get(field) or 0):
                return False
        except (TypeError, ValueError):
            return False
    try:
        if not math.isclose(float(record.get("total_share_score") or 0),
                            float(round_item.get("total_share_score") or 0), rel_tol=1e-9, abs_tol=1e-9):
            return False
    except (TypeError, ValueError):
        return False
    left, right = record.get("shares"), round_item.get("shares")
    if not isinstance(left, dict) or not isinstance(right, dict) or left.keys() != right.keys():
        return False
    numeric_fields = ("share_score", "share_percent")
    for wallet in left:
        a, b = left[wallet], right[wallet]
        if int(a.get("share_count") or 0) != int(b.get("share_count") or 0):
            return False
        if any(not math.isclose(float(a.get(field) or 0), float(b.get(field) or 0), rel_tol=1e-9, abs_tol=1e-6)
               for field in numeric_fields):
            return False
        aw, bw = a.get("workers"), b.get("workers")
        if not isinstance(aw, dict) or not isinstance(bw, dict) or aw.keys() != bw.keys():
            return False
        for worker in aw:
            x, y = aw[worker], bw[worker]
            if int(x.get("share_count") or 0) != int(y.get("share_count") or 0):
                return False
            if any(not math.isclose(float(x.get(field) or 0), float(y.get(field) or 0), rel_tol=1e-9, abs_tol=1e-6)
                   for field in ("share_score", "share_percent", "wallet_share_percent")):
                return False
    return True


def valid_attribution(record: Any) -> bool:
    if not isinstance(record, dict) or not isinstance(record.get("shares"), dict):
        return False
    try:
        count = int(record.get("total_share_count") or 0)
        score = float(record.get("total_share_score") or 0)
    except (TypeError, ValueError):
        return False
    if count <= 0 or not math.isfinite(score) or score <= 0 or not record["shares"]:
        return False
    wallet_scores = 0.0
    wallet_count = 0
    wallet_percent = 0.0
    for wallet, item in record["shares"].items():
        if not isinstance(wallet, str) or not wallet or not isinstance(item, dict):
            return False
        try:
            item_count = int(item.get("share_count") or 0)
            wallet_count += item_count
            weight = float(item.get("share_score") or 0)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(weight) or weight <= 0 or item_count <= 0:
            return False
        wallet_scores += weight
        try:
            percent = float(item.get("share_percent"))
        except (TypeError, ValueError):
            return False
        expected_percent = round(weight / score * 100, 6)
        if not math.isfinite(percent) or not math.isclose(percent, expected_percent, abs_tol=0.000001):
            return False
        wallet_percent += percent
        workers = item.get("workers")
        if not isinstance(workers, dict) or not workers:
            return False
        worker_count = 0
        worker_score = 0.0
        for worker in workers.values():
            if not isinstance(worker, dict):
                return False
            try:
                item_worker_count = int(worker.get("share_count") or 0)
                worker_count += item_worker_count
                worker_weight = float(worker.get("share_score") or 0)
                worker_percent = float(worker.get("share_percent"))
                wallet_worker_percent = float(worker.get("wallet_share_percent"))
            except (TypeError, ValueError):
                return False
            if (worker_weight <= 0 or not math.isfinite(worker_weight) or item_worker_count <= 0
                    or not math.isclose(worker_percent, round(worker_weight / score * 100, 6), abs_tol=0.000001)
                    or not math.isclose(wallet_worker_percent, round(worker_weight / weight * 100, 6), abs_tol=0.000001)):
                return False
            worker_score += worker_weight
        if worker_count != item_count or not math.isclose(worker_score, weight, rel_tol=1e-8, abs_tol=1e-8):
            return False
    return (wallet_count == count and math.isclose(wallet_scores, score, rel_tol=1e-8, abs_tol=1e-8)
            and math.isclose(wallet_percent, 100.0, abs_tol=0.001))


def attribution_record(
    round_item: dict[str, Any],
    previous_boundary: Any,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "miningMode": "pool",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate_hash": round_item["candidate_hash"],
        "round_id": round_item["round_id"],
        "submit_timestamp": round_item.get("submit_timestamp"),
        "previous_pool_boundary": previous_boundary,
        "total_share_count": round_item["total_share_count"],
        "total_share_score": round_item["total_share_score"],
        "wallet_count": round_item["wallet_count"],
        "worker_count": round_item["worker_count"],
        "shares": round_item["shares"],
    }
    if source_coverage is not None:
        record["share_window_coverage"] = source_coverage
    return record


def load_attribution_ledger(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"Warning: malformed attribution ledger row {line_number} ignored", file=sys.stderr)
                continue
            key = str(item.get("candidate_hash") or "") if isinstance(item, dict) else ""
            if (not re.fullmatch(r"[0-9a-fA-F]{64}", key) or item.get("miningMode") != "pool"
                    or not valid_attribution(item)):
                print(f"Warning: invalid attribution ledger row {line_number} ignored", file=sys.stderr)
                continue
            if key in records and records[key] != item:
                print(f"Warning: conflicting attribution ledger row for {key}; first record retained", file=sys.stderr)
                continue
            records[key] = item
    return records


def append_attribution(path: Path, record: dict[str, Any]) -> bool:
    """Append one immutable record under an advisory lock; return whether added."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND, 0o640)
    with os.fdopen(fd, "r+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        for line in stream:
            try:
                previous = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(previous, dict) and previous.get("candidate_hash") == record["candidate_hash"]:
                prior_identity = {key: value for key, value in previous.items() if key != "created_at"}
                new_identity = {key: value for key, value in record.items() if key != "created_at"}
                if prior_identity == new_identity:
                    return False
                raise ValueError(f"conflicting immutable attribution exists for {record['candidate_hash']}")
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        return True


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
    parser.add_argument("--attribution-ledger", type=str, default=None,
                        help="Append-only canonical Pool round attribution ledger")
    parser.add_argument(
        "--min-share-difficulty",
        type=float,
        default=None,
        help="Minimum difficulty floor for shares",
    )
    args = parser.parse_args()
    output_path = Path(args.output)
    ledger_path = Path(args.attribution_ledger) if args.attribution_ledger else output_path.with_name("round-attribution.jsonl")
    try:
        ledger_by_hash = load_attribution_ledger(ledger_path)
    except OSError as exc:
        print(f"Error loading attribution ledger: {exc}", file=sys.stderr)
        return 1

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
    share_log_paths: list[Path] = []
    if args.share_log:
        share_log_path = Path(args.share_log)
        if share_log_path.exists() or share_log_path.parent.exists():
            share_log_paths = share_log_segments(share_log_path)
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
                # 0. Exclude non-pool shares from Pool rounds
                share_mining_mode = payload.get("miningMode") or payload.get("mining_mode") or "pool"
                if isinstance(share_mining_mode, str) and share_mining_mode.strip().lower() != "pool":
                    continue

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

    share_source = analyze_share_source(tail_lines, share_log_paths, max_share_lines)

    shares.sort(key=lambda s: s["timestamp"])
    share_timestamps = [s["timestamp"] for s in shares]
    earliest_share_ts = min(share_timestamps) if share_timestamps else None
    latest_share_ts = max(share_timestamps) if share_timestamps else None

    # Filter candidates to only pool mode candidates matched on-chain (rounds)
    round_statuses = {"chain_match_found", "immature", "confirmed", "orphan"}
    round_cands = [
        c
        for c in candidates
        if c.get("lifecycle_status") in round_statuses
        and (str(c.get("mining_mode") or c.get("miningMode") or "pool")).strip().lower() == "pool"
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
        coverage: dict[str, Any] | None,
        coverage_reason: str | None,
    ) -> tuple[str, str | None]:
        if coverage is None:
            return "incomplete", coverage_reason or "share_window_coverage_unavailable"
        if total_shares > 0:
            return "ok", None
        return "empty", "no_shares_in_round_window"

    preserved_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Compute rounds and attribute shares
    rounds_list = []
    previous_boundary_ts = datetime.min.replace(tzinfo=timezone.utc)
    previous_boundary_hash: str | None = None
    attribution_added = 0
    for i, c in enumerate(round_cands):
        c_ts = parse_timestamp(c.get("submit_timestamp"))
        if c.get("lifecycle_status") == "orphan":
            if i == 0:
                start_ts = datetime.min.replace(tzinfo=timezone.utc)
                window_start_candidate_hash = None
            else:
                start_ts = parse_timestamp(
                    round_cands[i - 1].get("submit_timestamp")
                )
                window_start_candidate_hash = str(round_cands[i - 1].get("candidate_hash") or "") or None
        else:
            start_ts = previous_boundary_ts
            window_start_candidate_hash = previous_boundary_hash
            previous_boundary_ts = c_ts
            previous_boundary_hash = str(c.get("candidate_hash") or "") or None

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
        candidate_hash = str(c.get("candidate_hash") or "")
        record_previous_boundary = previous_boundary_hash if status == "orphan" else window_start_candidate_hash
        window_coverage, window_coverage_reason = make_window_coverage(
            share_source,
            start_ts,
            c_ts,
            candidate_hash,
            record_previous_boundary,
            window_start_candidate_hash,
        )
        attribution_status, attribution_reason = attribution_for(
            status,
            total_round_shares,
            window_coverage,
            window_coverage_reason,
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
            "attribution_coverage_verified": False,
        }
        if window_coverage is not None:
            window_coverage["attribution_sha256"] = attribution_digest(round_item)

        existing_round = existing_rounds_by_hash.get(str(c.get("candidate_hash")))
        persisted = ledger_by_hash.get(candidate_hash)
        coverage_verified = False
        verified_coverage = None
        if persisted is None and window_coverage is not None and valid_attribution(round_item):
            coverage_verified = True
            verified_coverage = window_coverage

        if persisted is not None:
            if window_coverage is not None and attribution_matches(persisted, round_item):
                coverage_verified = True
                verified_coverage = window_coverage
            else:
                persisted_coverage = persisted.get("share_window_coverage")
                if saved_window_coverage_is_valid(
                    persisted_coverage, start_ts, c_ts, candidate_hash,
                    record_previous_boundary, window_start_candidate_hash,
                    persisted,
                ):
                    coverage_verified = True
                    verified_coverage = persisted_coverage
                elif isinstance(existing_round, dict) and attribution_matches(persisted, existing_round):
                    snapshot_coverage = existing_round.get("attribution_source_coverage")
                    if saved_window_coverage_is_valid(
                        snapshot_coverage, start_ts, c_ts, candidate_hash,
                        record_previous_boundary, window_start_candidate_hash,
                        persisted,
                    ):
                        coverage_verified = True
                        verified_coverage = snapshot_coverage

        elif candidate_hash and re.fullmatch(r"[0-9a-fA-F]{64}", candidate_hash):
            old_is_valid = isinstance(existing_round, dict) and valid_attribution(existing_round)
            old_coverage = existing_round.get("attribution_source_coverage") if isinstance(existing_round, dict) else None
            if (old_is_valid and saved_window_coverage_is_valid(
                    old_coverage, start_ts, c_ts, candidate_hash,
                    record_previous_boundary, window_start_candidate_hash, existing_round,
            )):
                record = attribution_record(existing_round, record_previous_boundary, old_coverage)
                try:
                    if append_attribution(ledger_path, record):
                        attribution_added += 1
                    ledger_by_hash[candidate_hash] = record
                except (OSError, ValueError) as exc:
                    print(f"Error persisting attribution for {candidate_hash}: {exc}", file=sys.stderr)
                    return 1
                persisted = record
                coverage_verified = True
                verified_coverage = old_coverage
            if persisted is None and window_coverage is not None and old_is_valid and attribution_matches(existing_round, round_item):
                record = attribution_record(existing_round, record_previous_boundary, window_coverage)
                try:
                    if append_attribution(ledger_path, record):
                        attribution_added += 1
                    ledger_by_hash[candidate_hash] = record
                except (OSError, ValueError) as exc:
                    print(f"Error persisting attribution for {candidate_hash}: {exc}", file=sys.stderr)
                    return 1
                persisted = record
                coverage_verified = True
                verified_coverage = window_coverage
            elif persisted is None and window_coverage is not None and valid_attribution(round_item):
                record = attribution_record(round_item, record_previous_boundary, window_coverage)
                try:
                    if append_attribution(ledger_path, record):
                        attribution_added += 1
                    ledger_by_hash[candidate_hash] = record
                except (OSError, ValueError) as exc:
                    print(f"Error persisting attribution for {candidate_hash}: {exc}", file=sys.stderr)
                    return 1
                persisted = record
                coverage_verified = True
                verified_coverage = window_coverage

        if persisted is not None:
            round_item["shares"] = persisted["shares"]
            for field in ("total_share_count", "total_share_score", "wallet_count", "worker_count"):
                round_item[field] = persisted[field]
            round_item["attribution_persisted"] = True
            round_item["attribution_coverage_verified"] = coverage_verified
            if coverage_verified:
                round_item["attribution_status"] = "ok"
                round_item["attribution_reason"] = None
                round_item["attribution_source_coverage"] = verified_coverage
            else:
                round_item["attribution_status"] = "unverified"
                round_item["attribution_reason"] = "existing_attribution_source_unverifiable"
        elif isinstance(existing_round, dict) and valid_attribution(existing_round):
            # Keep historical snapshot values visible, but never promote them to
            # immutable accounting without matching, complete share-window evidence.
            round_item["shares"] = existing_round["shares"]
            for field in ("total_share_count", "total_share_score", "wallet_count", "worker_count"):
                round_item[field] = existing_round[field]
            round_item["attribution_status"] = "unverified"
            round_item["attribution_reason"] = "snapshot_attribution_source_unverifiable"
            round_item["attribution_preserved"] = True
            round_item["attribution_preserved_at"] = preserved_now

        if persisted is None:
            round_item["attribution_coverage_verified"] = coverage_verified
            if coverage_verified:
                round_item["attribution_source_coverage"] = verified_coverage

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
    unverified_attribution_count = sum(
        1 for item in rounds_list if item.get("attribution_coverage_verified") is not True
        and item.get("total_share_count", 0) > 0
    )
    unverified_confirmed_round_count = sum(
        1 for item in rounds_list
        if item.get("status") == "confirmed" and item.get("attribution_coverage_verified") is not True
        and item.get("total_share_count", 0) > 0
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
        "persistedAttributionCount": len(ledger_by_hash),
        "newAttributionRecords": attribution_added,
        "incompleteConfirmedRoundCount": incomplete_confirmed_round_count,
        "emptyConfirmedRoundCount": empty_confirmed_round_count,
        "unverifiedAttributionCount": unverified_attribution_count,
        "unverifiedConfirmedRoundCount": unverified_confirmed_round_count,
        "maxShareLines": max_share_lines,
        "shareLogCoverage": share_source,
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

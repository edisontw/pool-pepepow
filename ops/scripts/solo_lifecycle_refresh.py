#!/usr/bin/env python3
"""Refresh Pure SOLO block lifecycle snapshots without rescanning large runtime logs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TAIL_MAX_BYTES = 4 * 1024 * 1024


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tail_json_objects(
    path: Path,
    max_lines: int,
    *,
    max_bytes: int = DEFAULT_TAIL_MAX_BYTES,
) -> list[dict[str, Any]]:
    if max_lines <= 0 or not path.exists():
        return []

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        remaining = min(end, max_bytes)
        pos = end
        chunks: list[bytes] = []
        newline_count = 0
        block_size = 64 * 1024

        while remaining > 0 and newline_count <= max_lines:
            size = min(block_size, remaining)
            pos -= size
            handle.seek(pos)
            chunk = handle.read(size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
            remaining -= size

    raw = b"".join(reversed(chunks))
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines()[-max_lines:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest_outcomes_by_hash(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        block_hash = row.get("candidateBlockHash")
        if isinstance(block_hash, str) and block_hash:
            latest[block_hash] = row
    return latest


def _should_check_candidate(
    candidate: dict[str, Any],
    latest_outcome: dict[str, Any] | None,
    *,
    now: datetime,
    retry_no_match_seconds: int,
) -> bool:
    if candidate.get("submitblockSent") is not True:
        return False

    block_hash = candidate.get("candidateBlockHash")
    if not isinstance(block_hash, str) or not block_hash:
        return False

    if not latest_outcome:
        return True

    status = latest_outcome.get("followupStatus")
    if status == "match-found":
        return False

    if status == "no-match-found":
        candidate_at = _parse_iso(
            candidate.get("submitblockSubmittedAt") or candidate.get("timestamp")
        )
        if candidate_at is None:
            return False
        return (now - candidate_at).total_seconds() <= retry_no_match_seconds

    return True


def _followup_changed(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> bool:
    if not previous:
        return True
    keys = (
        "followupStatus",
        "followupObservedHeight",
        "followupObservedBlockHash",
        "followupNote",
    )
    return any(previous.get(key) != current.get(key) for key in keys)


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _load_chain_context(pool_snapshot: Path) -> tuple[list[dict[str, Any]], int]:
    payload = _load_json_dict(pool_snapshot) or {}
    blocks = payload.get("blocks", [])
    if not isinstance(blocks, list):
        blocks = []
    try:
        height = int((payload.get("network") or {}).get("height") or 0)
    except (TypeError, ValueError, AttributeError):
        height = 0
    return [item for item in blocks if isinstance(item, dict)], max(0, height)


def _normalized_record_from_outcome(
    row: dict[str, Any],
    snapshot_blocks: list[dict[str, Any]],
    current_height: int,
) -> dict[str, Any] | None:
    block_hash = row.get("candidateBlockHash")
    if not isinstance(block_hash, str) or not block_hash:
        return None

    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from track_accepted_candidates import map_lifecycle_status  # noqa: E402

    lifecycle_status, confirmations, maturity_label = map_lifecycle_status(
        row, snapshot_blocks, current_height
    )
    return {
        "candidate_hash": block_hash,
        "job_id": row.get("jobId"),
        "submit_timestamp": (
            row.get("submitblockSubmittedAt")
            or row.get("candidateTimestamp")
            or row.get("timestamp")
        ),
        "daemon_result": row.get("submitblockDaemonResult"),
        "followup_status": row.get("followupStatus"),
        "matched_height": row.get("followupObservedHeight"),
        "matched_block_hash": row.get("followupObservedBlockHash"),
        "lifecycle_status": lifecycle_status,
        "confirmations": confirmations,
        "maturity_label": maturity_label,
        "wallet": row.get("wallet"),
        "worker": row.get("worker"),
        "mining_mode": row.get("miningMode") or row.get("mining_mode") or "pool",
    }


def _refresh_existing_record(
    record: dict[str, Any],
    snapshot_blocks: list[dict[str, Any]],
    current_height: int,
) -> dict[str, Any]:
    current = dict(record)
    lifecycle = str(current.get("lifecycle_status") or "")
    followup_status = current.get("followup_status")
    if not followup_status and lifecycle in {"chain_match_found", "immature", "confirmed"}:
        followup_status = "match-found"
    elif not followup_status and lifecycle == "orphan":
        followup_status = "no-match-found"

    pseudo_outcome = {
        "candidateBlockHash": current.get("candidate_hash"),
        "jobId": current.get("job_id"),
        "candidateTimestamp": current.get("submit_timestamp"),
        "submitblockDaemonResult": current.get("daemon_result"),
        "followupStatus": followup_status,
        "followupObservedHeight": current.get("matched_height"),
        "followupObservedBlockHash": current.get("matched_block_hash"),
        "wallet": current.get("wallet"),
        "worker": current.get("worker"),
        "miningMode": current.get("mining_mode") or "solo",
    }
    refreshed = _normalized_record_from_outcome(
        pseudo_outcome, snapshot_blocks, current_height
    )
    return refreshed or current


def _merge_incremental_accepted_candidates(
    *,
    outcome_rows: list[dict[str, Any]],
    accepted_candidates: Path,
    pool_snapshot: Path,
) -> int:
    existing_payload = _load_json_dict(accepted_candidates)
    if not existing_payload or not isinstance(existing_payload.get("accepted_candidates"), list):
        return -1

    snapshot_blocks, current_height = _load_chain_context(pool_snapshot)
    merged: dict[str, dict[str, Any]] = {}
    for item in existing_payload["accepted_candidates"]:
        if not isinstance(item, dict):
            continue
        block_hash = item.get("candidate_hash")
        if not isinstance(block_hash, str) or not block_hash:
            continue
        merged[block_hash] = _refresh_existing_record(
            item, snapshot_blocks, current_height
        )

    for row in outcome_rows:
        normalized = _normalized_record_from_outcome(
            row, snapshot_blocks, current_height
        )
        if normalized is not None:
            merged[normalized["candidate_hash"]] = normalized

    def sort_key(item: dict[str, Any]) -> datetime:
        return _parse_iso(item.get("submit_timestamp")) or datetime.min.replace(tzinfo=timezone.utc)

    accepted_list = sorted(merged.values(), key=sort_key)
    _write_json_atomic(
        accepted_candidates,
        {
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "accepted_candidates": accepted_list,
        },
    )
    return len(accepted_list)


def _rebuild_accepted_candidates(
    *,
    repo_root: Path,
    outcome_events: Path,
    outcome_rows: list[dict[str, Any]],
    accepted_candidates: Path,
    pool_snapshot: Path,
) -> tuple[str, int | None]:
    merged_count = _merge_incremental_accepted_candidates(
        outcome_rows=outcome_rows,
        accepted_candidates=accepted_candidates,
        pool_snapshot=pool_snapshot,
    )
    if merged_count >= 0:
        return "incremental", merged_count

    # Bootstrap only: if no valid persisted snapshot exists yet, build it once
    # from the complete outcome log. Normal minute-by-minute refreshes never
    # rescan the growing JSONL again.
    cmd = [
        sys.executable,
        str(repo_root / "ops" / "scripts" / "track_accepted_candidates.py"),
        str(outcome_events),
        str(accepted_candidates),
        "--pool-snapshot",
        str(pool_snapshot),
    ]
    subprocess.run(cmd, check=True)
    payload = _load_json_dict(accepted_candidates) or {}
    items = payload.get("accepted_candidates", [])
    return "bootstrap-full-scan", len(items) if isinstance(items, list) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-events", type=Path, required=True)
    parser.add_argument("--followup-events", type=Path, required=True)
    parser.add_argument("--outcome-events", type=Path, required=True)
    parser.add_argument("--accepted-candidates", type=Path, required=True)
    parser.add_argument("--pool-snapshot", type=Path, required=True)
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--max-outcomes", type=int, default=2000)
    parser.add_argument("--retry-no-match-seconds", type=int, default=600)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    pool_core_dir = repo_root / "apps" / "pool-core"
    sys.path.insert(0, str(pool_core_dir))

    from daemon_rpc import (  # noqa: E402
        DaemonRpcClient,
        append_candidate_followup_event,
        check_candidate_followup,
    )

    candidates = _tail_json_objects(args.candidate_events, args.max_candidates)
    outcomes = _tail_json_objects(args.outcome_events, args.max_outcomes)
    latest_outcomes = _latest_outcomes_by_hash(outcomes)
    now = datetime.now(timezone.utc)

    pending: list[dict[str, Any]] = []
    for candidate in candidates:
        block_hash = candidate.get("candidateBlockHash")
        previous = latest_outcomes.get(block_hash) if isinstance(block_hash, str) else None
        if _should_check_candidate(
            candidate,
            previous,
            now=now,
            retry_no_match_seconds=max(0, args.retry_no_match_seconds),
        ):
            pending.append(candidate)

    rpc_errors = 0
    checked = 0
    recorded = 0

    if pending:
        rpc_host = os.getenv("PEPEPOWD_RPC_HOST", "127.0.0.1")
        rpc_port = os.getenv("PEPEPOWD_RPC_PORT", "8834")
        rpc_url = os.getenv("PEPEPOWD_RPC_URL", f"http://{rpc_host}:{rpc_port}")
        rpc_user = os.getenv("PEPEPOWD_RPC_USER", "")
        rpc_password = os.getenv("PEPEPOWD_RPC_PASSWORD", "")
        rpc_timeout = max(1.0, float(os.getenv("PEPEPOWD_RPC_TIMEOUT_SECONDS", "5")))

        if not rpc_user or not rpc_password:
            print("solo-lifecycle-refresh: daemon RPC credentials are missing", file=sys.stderr)
            return 2

        rpc_client = DaemonRpcClient(
            rpc_url=rpc_url,
            rpc_user=rpc_user,
            rpc_password=rpc_password,
            timeout_seconds=rpc_timeout,
            cache_ttl_seconds=1,
        )

        for candidate in pending:
            block_hash = candidate.get("candidateBlockHash")
            previous = latest_outcomes.get(block_hash) if isinstance(block_hash, str) else None
            followup = check_candidate_followup(block_hash, rpc_client=rpc_client)
            checked += 1
            if followup.get("followupStatus") == "check-error":
                rpc_errors += 1

            if _followup_changed(previous, followup):
                append_candidate_followup_event(
                    args.followup_events,
                    candidate,
                    followup,
                    outcome_path=args.outcome_events,
                )
                recorded += 1
                if isinstance(block_hash, str):
                    latest_outcomes[block_hash] = followup

    # Refresh the tail after any new followup outcome was appended in this run.
    outcomes = _tail_json_objects(args.outcome_events, args.max_outcomes)
    refresh_mode, accepted_count = _rebuild_accepted_candidates(
        repo_root=repo_root,
        outcome_events=args.outcome_events,
        outcome_rows=outcomes,
        accepted_candidates=args.accepted_candidates,
        pool_snapshot=args.pool_snapshot,
    )

    print(
        "solo-lifecycle-refresh:"
        f" candidates_tail={len(candidates)}"
        f" outcomes_tail={len(outcomes)}"
        f" pending={len(pending)}"
        f" checked={checked}"
        f" recorded={recorded}"
        f" rpc_errors={rpc_errors}"
        f" snapshot_refresh={refresh_mode}"
        f" accepted_candidates={accepted_count if accepted_count is not None else 'unknown'}"
    )
    return 1 if rpc_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

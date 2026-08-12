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


def _rebuild_accepted_candidates(
    *,
    repo_root: Path,
    outcome_events: Path,
    accepted_candidates: Path,
    pool_snapshot: Path,
) -> None:
    cmd = [
        sys.executable,
        str(repo_root / "ops" / "scripts" / "track_accepted_candidates.py"),
        str(outcome_events),
        str(accepted_candidates),
        "--pool-snapshot",
        str(pool_snapshot),
    ]
    subprocess.run(cmd, check=True)


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

    _rebuild_accepted_candidates(
        repo_root=repo_root,
        outcome_events=args.outcome_events,
        accepted_candidates=args.accepted_candidates,
        pool_snapshot=args.pool_snapshot,
    )

    print(
        "solo-lifecycle-refresh:"
        f" candidates_tail={len(candidates)}"
        f" pending={len(pending)}"
        f" checked={checked}"
        f" recorded={recorded}"
        f" rpc_errors={rpc_errors}"
    )
    return 1 if rpc_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

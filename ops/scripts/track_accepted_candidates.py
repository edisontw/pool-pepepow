#!/usr/bin/env python3
"""Minimal block lifecycle / accepted candidate tracking.

Filters candidate-outcome-events.jsonl to track accepted candidates and maintain their block lifecycle status.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allowed lifecycle statuses
LIFECYCLE_STATUSES = {
    "submitted",
    "chain_match_found",
    "pending_followup",
    "chain_match_not_found",
    "unknown",
}

def map_lifecycle_status(row: dict[str, Any]) -> str:
    followup_status = row.get("followupStatus")
    outcome_status = row.get("candidateOutcomeStatus")
    sent = row.get("submitblockSent")
    daemon_accepted = row.get("submitblockDaemonAcceptedLikely")
    daemon_result = row.get("submitblockDaemonResult")

    if followup_status == "match-found" or outcome_status == "chain-match-found":
        return "chain_match_found"
    if followup_status == "no-match-found" or outcome_status == "chain-match-not-found":
        return "chain_match_not_found"

    # If it was sent/accepted but followup not checked yet
    is_accepted_or_sent = (
        sent
        or daemon_accepted is True
        or (daemon_result is None and sent)
        or daemon_result == "Success"
    )
    if is_accepted_or_sent:
        # Check elapsed time
        submitted_at_str = row.get("submitblockSubmittedAt") or row.get("timestamp")
        if submitted_at_str:
            try:
                dt = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = (now - dt).total_seconds()
                if elapsed < 30:
                    return "submitted"
            except Exception:
                pass
        return "pending_followup"

    return "unknown"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outcome_log", type=str, help="Path to candidate-outcome-events.jsonl")
    parser.add_argument("output_json", type=str, help="Path to output accepted-candidates.json")
    args = parser.parse_args()

    outcome_path = Path(args.outcome_log)
    output_path = Path(args.output_json)

    if not outcome_path.exists():
        print(f"Error: outcome log file not found at {outcome_path}", file=sys.stderr)
        # Write an empty structure if the file does not exist yet to initialize it cleanly
        output_data = {
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "accepted_candidates": []
        }
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, sort_keys=True)
        except Exception:
            pass
        return 0

    # Load JSON lines
    candidates_by_hash: dict[str, dict[str, Any]] = {}
    try:
        with outcome_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                block_hash = row.get("candidateBlockHash")
                if not block_hash:
                    continue
                
                # We group by candidateBlockHash and keep the latest record
                candidates_by_hash[block_hash] = row
    except Exception as exc:
        print(f"Error reading outcome log: {exc}", file=sys.stderr)
        return 1

    accepted_list = []
    for block_hash, row in candidates_by_hash.items():
        # Check acceptance criteria:
        # - reached submitblockDaemonResult=Success
        # - or submitblockDaemonAcceptedLikely=True
        # - or follow-up chain-match-found
        daemon_result = row.get("submitblockDaemonResult")
        daemon_accepted = row.get("submitblockDaemonAcceptedLikely")
        followup_status = row.get("followupStatus")
        outcome_status = row.get("candidateOutcomeStatus")
        sent = row.get("submitblockSent")

        is_success = (
            daemon_result == "Success"
            or (daemon_result is None and sent)
            or daemon_accepted is True
            or followup_status == "match-found"
            or outcome_status == "chain-match-found"
        )

        if not is_success:
            continue

        lifecycle = map_lifecycle_status(row)

        record = {
            "candidate_hash": block_hash,
            "job_id": row.get("jobId"),
            "submit_timestamp": row.get("submitblockSubmittedAt") or row.get("candidateTimestamp") or row.get("timestamp"),
            "daemon_result": daemon_result,
            "submitblock_daemon_accepted_likely": daemon_accepted,
            "followup_status": followup_status,
            "matched_height": row.get("followupObservedHeight"),
            "matched_block_hash": row.get("followupObservedBlockHash"),
            "lifecycle_status": lifecycle
        }
        accepted_list.append(record)

    # Sort accepted list by submit timestamp ascending (chronological order)
    def parse_time(ts):
        if not ts:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    accepted_list.sort(key=lambda x: parse_time(x["submit_timestamp"]))

    output_data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "accepted_candidates": accepted_list
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, sort_keys=True)
        print(f"Saved {len(accepted_list)} accepted candidates to {output_path}")
    except Exception as exc:
        print(f"Error writing output JSON: {exc}", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())

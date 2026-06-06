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
    "candidate_recorded",
    "submit_accepted",
    "chain_match_found",
    "immature",
    "confirmed",
    "orphan",
    "unknown",
}

def map_lifecycle_status(row: dict[str, Any], snapshot_blocks: list[dict[str, Any]], current_height: int) -> tuple[str, int | None, str | None]:
    followup_status = row.get("followupStatus")
    outcome_status = row.get("candidateOutcomeStatus")
    sent = row.get("submitblockSent")
    daemon_accepted = row.get("submitblockDaemonAcceptedLikely")
    daemon_result = row.get("submitblockDaemonResult")
    candidate_hash = row.get("candidateBlockHash")
    matched_block_hash = row.get("followupObservedBlockHash")
    matched_height = row.get("followupObservedHeight")

    # Determine confirmations
    confirmations = None
    if isinstance(snapshot_blocks, list):
        for sb in snapshot_blocks:
            if not isinstance(sb, dict):
                continue
            sb_hash = sb.get("hash")
            if sb_hash and (sb_hash == candidate_hash or (matched_block_hash and sb_hash == matched_block_hash)):
                confirmations = sb.get("confirmations")
                break

    if confirmations is None and matched_height is not None and current_height > 0:
        try:
            m_h = int(matched_height)
            if current_height >= m_h:
                confirmations = current_height - m_h + 1
        except (ValueError, TypeError):
            pass

    # Check if a block at matched_height exists in snapshot_blocks but has a divergent hash
    is_divergent = False
    if matched_height is not None and isinstance(snapshot_blocks, list):
        try:
            m_h = int(matched_height)
            for sb in snapshot_blocks:
                if isinstance(sb, dict) and sb.get("height") is not None:
                    if int(sb["height"]) == m_h:
                        sb_hash = sb.get("hash")
                        matches_candidate = (sb_hash and candidate_hash and sb_hash == candidate_hash)
                        matches_matched = (sb_hash and matched_block_hash and sb_hash == matched_block_hash)
                        if not (matches_candidate or matches_matched):
                            is_divergent = True
                        break
        except (ValueError, TypeError):
            pass

    # Check for orphan (takes precedence if matched block is no longer on the active chain or mismatched)
    is_orphan = (
        followup_status == "no-match-found"
        or outcome_status == "chain-match-not-found"
        or is_divergent
        or (matched_block_hash is not None and candidate_hash is not None and matched_block_hash != candidate_hash)
    )

    if is_orphan:
        return "orphan", None, None

    # Check for chain match (chain_match_found, immature, confirmed)
    is_match = (
        followup_status == "match-found"
        or outcome_status == "chain-match-found"
        or (matched_block_hash and matched_block_hash == candidate_hash)
    )

    if is_match:
        maturity_label = None
        if confirmations is not None:
            try:
                conf_int = int(confirmations)
                if conf_int >= 100:
                    status = "confirmed"
                    maturity_label = "mature"
                else:
                    status = "immature"
                    maturity_label = "immature"
            except (ValueError, TypeError):
                status = "chain_match_found"
                maturity_label = "immature"
        else:
            status = "chain_match_found"
            maturity_label = "immature"
        return status, confirmations, maturity_label

    # Check for submit_accepted
    is_accepted = (
        daemon_result == "Success"
        or daemon_accepted is True
    )
    if is_accepted:
        return "submit_accepted", None, None

    # Check for candidate_recorded
    return "candidate_recorded", None, None

def load_snapshot_data(snapshot_path_arg: str | None, output_path: Path) -> dict[str, Any] | None:
    candidates = []
    if snapshot_path_arg:
        candidates.append(Path(snapshot_path_arg))
    
    import os
    env_core = os.getenv("PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT")
    if env_core:
        candidates.append(Path(env_core))
        
    env_api = os.getenv("PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH")
    if env_api:
        candidates.append(Path(env_api))
        
    candidates.append(output_path.parent / "pool-snapshot.json")
    candidates.append(output_path.parent.parent / "systemd-smoke" / "pool-snapshot.json")
    candidates.append(Path("/var/lib/pepepow-pool/pool-snapshot.json"))
    
    for p in candidates:
        if p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outcome_log", type=str, help="Path to candidate-outcome-events.jsonl")
    parser.add_argument("output_json", type=str, help="Path to output accepted-candidates.json")
    parser.add_argument("--pool-snapshot", type=str, default=None, help="Path to pool-snapshot.json")
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

    snapshot_data = load_snapshot_data(args.pool_snapshot, output_path)
    snapshot_blocks = []
    current_height = 0
    if snapshot_data:
        snapshot_blocks = snapshot_data.get("blocks", [])
        if not isinstance(snapshot_blocks, list):
            snapshot_blocks = []
        current_height = snapshot_data.get("network", {}).get("height", 0)
        try:
            current_height = int(current_height)
        except (ValueError, TypeError):
            current_height = 0

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
        daemon_result = row.get("submitblockDaemonResult")
        followup_status = row.get("followupStatus")
        matched_height = row.get("followupObservedHeight")
        matched_block_hash = row.get("followupObservedBlockHash")

        lifecycle_status, confirmations, maturity_label = map_lifecycle_status(
            row, snapshot_blocks, current_height
        )

        record = {
            "candidate_hash": block_hash,
            "job_id": row.get("jobId"),
            "submit_timestamp": row.get("submitblockSubmittedAt") or row.get("candidateTimestamp") or row.get("timestamp"),
            "daemon_result": daemon_result,
            "followup_status": followup_status,
            "matched_height": matched_height,
            "matched_block_hash": matched_block_hash,
            "lifecycle_status": lifecycle_status,
            "confirmations": confirmations,
            "maturity_label": maturity_label,
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

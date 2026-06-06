#!/usr/bin/env python3
"""Payout helper tool for PEPEPOW pool.
Handles read-only payout candidate generation and manual payment recording.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

def generate_payout_candidates(accepted_path: Path, rounds_path: Path, output_path: Path) -> int:
    candidates = []
    if accepted_path.exists():
        try:
            with accepted_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                candidates = data.get("accepted_candidates", [])
        except Exception as exc:
            print(f"Warning: Failed to load accepted candidates: {exc}", file=sys.stderr)

    rounds_map = {}
    if rounds_path.exists():
        try:
            with rounds_path.open("r", encoding="utf-8") as f:
                rounds_data = json.load(f)
            if isinstance(rounds_data, dict):
                for r in rounds_data.get("rounds", []):
                    h = r.get("candidate_hash")
                    if h:
                        rounds_map[h] = r
        except Exception as exc:
            print(f"Warning: Failed to load rounds snapshot: {exc}", file=sys.stderr)

    payout_candidates = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        c_hash = c.get("candidate_hash")
        l_status = c.get("lifecycle_status")
        height = c.get("matched_height")

        status = "blocked"
        reason = None

        if l_status == "confirmed":
            if not c_hash:
                reason = "missing_candidate_hash"
            elif c_hash not in rounds_map:
                reason = "missing_round_data"
            else:
                r_data = rounds_map[c_hash]
                shares = r_data.get("shares")
                if not isinstance(shares, dict):
                    reason = "missing_share_data"
                else:
                    status = "eligible"
        elif l_status in ("immature", "orphan"):
            status = "blocked"
            reason = f"{l_status}_block"
        else:
            status = "blocked"
            reason = f"unconfirmed_status_{l_status}"

        shares_info = {}
        if c_hash in rounds_map:
            shares_info = rounds_map[c_hash].get("shares", {})

        payout_candidates.append({
            "candidate_hash": c_hash,
            "height": height,
            "lifecycle_status": l_status,
            "status": status,
            "reason": reason,
            "shares": shares_info,
            "submit_timestamp": c.get("submit_timestamp")
        })

    out_data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidates": payout_candidates
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=output_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(out_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, output_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Error: Failed to write payout candidates atomically: {exc}", file=sys.stderr)
        return 1

    return 0

def record_payment(
    actions_log_path: Path,
    snapshot_path: Path,
    candidate_id: str,
    wallet: str,
    amount: float,
    txid: str
) -> int:
    pattern = re.compile(r"^[A-Za-z0-9]{26,128}$")

    if not pattern.match(candidate_id):
        print(f"Error: Invalid candidate_id format (must be 26-128 chars alphanumeric): {candidate_id}", file=sys.stderr)
        return 1
    if not pattern.match(wallet):
        print(f"Error: Invalid wallet address format (must be 26-128 chars alphanumeric): {wallet}", file=sys.stderr)
        return 1
    if not pattern.match(txid):
        print(f"Error: Invalid txid format (must be 26-128 chars alphanumeric): {txid}", file=sys.stderr)
        return 1
    if amount <= 0:
        print(f"Error: Amount must be positive: {amount}", file=sys.stderr)
        return 1

    existing_actions = []
    if actions_log_path.exists():
        try:
            with actions_log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        act = json.loads(line)
                        if not isinstance(act, dict):
                            continue
                        if act.get("candidate_id") == candidate_id and act.get("wallet") == wallet:
                            print(f"Error: Duplicate payment rejected. Wallet {wallet} has already been paid for candidate {candidate_id}.", file=sys.stderr)
                            return 1
                        existing_actions.append(act)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            print(f"Error reading payment actions log: {exc}", file=sys.stderr)
            return 1

    new_action = {
        "candidate_id": candidate_id,
        "wallet": wallet,
        "amount": amount,
        "txid": txid,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

    try:
        actions_log_path.parent.mkdir(parents=True, exist_ok=True)
        with actions_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(new_action) + "\n")
    except Exception as exc:
        print(f"Error writing to payment actions log: {exc}", file=sys.stderr)
        return 1

    existing_actions.append(new_action)

    items = []
    for act in existing_actions:
        items.append({
            "wallet": act.get("wallet"),
            "amount": act.get("amount"),
            "paidAt": act.get("timestamp"),
            "confirmations": 1,
            "txid": act.get("txid")
        })

    # Sort descending by paidAt
    items.sort(key=lambda x: x.get("paidAt", ""), reverse=True)

    snapshot_data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items
    }

    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=snapshot_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(snapshot_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, snapshot_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Error writing payments snapshot atomically: {exc}", file=sys.stderr)
        return 1

    return 0

def main() -> int:
    parser = argparse.ArgumentParser(description="PEPEPOW Manual Payout Accounting Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_cand = subparsers.add_parser("payout-candidates", help="Generate payout candidates")
    parser_cand.add_argument("--accepted-candidates", type=str, required=True, help="Path to accepted-candidates.json")
    parser_cand.add_argument("--rounds-snapshot", type=str, required=True, help="Path to rounds-snapshot.json")
    parser_cand.add_argument("--output", type=str, required=True, help="Path to output payout-candidates.json")

    parser_rec = subparsers.add_parser("record-payment", help="Record a manual payment")
    parser_rec.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_rec.add_argument("--snapshot", type=str, required=True, help="Path to payments-snapshot.json")
    parser_rec.add_argument("--candidate-id", type=str, required=True, help="Hash of candidate block")
    parser_rec.add_argument("--wallet", type=str, required=True, help="Wallet address paid")
    parser_rec.add_argument("--amount", type=float, required=True, help="Payment amount")
    parser_rec.add_argument("--txid", type=str, required=True, help="Transaction ID (txid)")

    args = parser.parse_args()

    if args.command == "payout-candidates":
        return generate_payout_candidates(
            Path(args.accepted_candidates),
            Path(args.rounds_snapshot),
            Path(args.output)
        )
    elif args.command == "record-payment":
        return record_payment(
            Path(args.actions_log),
            Path(args.snapshot),
            args.candidate_id,
            args.wallet,
            args.amount,
            args.txid
        )

    return 0

if __name__ == "__main__":
    sys.exit(main())

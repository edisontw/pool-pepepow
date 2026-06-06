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
from typing import Any

def load_pool_snapshot() -> dict[str, Any]:
    paths = [
        Path(os.getenv("PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT", "")),
        Path(os.getenv("PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH", "")),
        Path("/var/lib/pepepow-pool/pool-snapshot.json"),
        Path(".runtime/systemd-smoke/pool-snapshot.json"),
        Path(".runtime/pool-snapshot.json"),
        Path("apps/api/data/mock/pool-snapshot.json"),
    ]
    for p in paths:
        if p and p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {}

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

    pool_snap = load_pool_snapshot()
    snap_blocks = pool_snap.get("blocks", [])
    snap_rewards = {}
    if isinstance(snap_blocks, list):
        for sb in snap_blocks:
            if not isinstance(sb, dict):
                continue
            h_hash = sb.get("hash")
            h_reward = sb.get("reward")
            if h_hash:
                snap_rewards[h_hash] = h_reward

    payout_candidates = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        c_hash = c.get("candidate_hash")
        l_status = c.get("lifecycle_status")
        height = c.get("matched_height")
        
        # Reward source lookup
        reward = c.get("reward")
        reward_source = "candidate"
        if reward is None:
            reward = snap_rewards.get(c_hash)
            reward_source = "pool-snapshot" if reward is not None else None

        status = "blocked"
        reason = None
        gross_reward = None
        net_reward = None
        pool_fee_percent = None
        pool_fee_amount = None
        weight_mode = None
        round_share_total = None
        payouts = []

        if l_status != "confirmed":
            status = "blocked"
            if l_status in ("immature", "orphan"):
                reason = f"{l_status}_block"
            else:
                reason = f"unconfirmed_status_{l_status}"
        else:
            # Enforce validations
            # 1. Reward validation
            if reward is None:
                status = "blocked"
                reason = "blocked_missing_reward"
            elif isinstance(reward, str) and reward.strip().lower() == "synthetic":
                status = "blocked"
                reason = "blocked_invalid_reward"
            else:
                try:
                    reward_val = float(reward)
                    if reward_val == 0:
                        status = "blocked"
                        reason = "blocked_zero_reward"
                    elif reward_val < 0:
                        status = "blocked"
                        reason = "blocked_invalid_reward"
                    else:
                        gross_reward = reward_val
                except (ValueError, TypeError):
                    status = "blocked"
                    reason = "blocked_invalid_reward"

            if not reason:
                # 2. Candidate hash validation
                if not c_hash:
                    status = "blocked"
                    reason = "missing_candidate_hash"
                # 3. Round validation
                elif c_hash not in rounds_map:
                    status = "blocked"
                    reason = "missing_round_data"
                else:
                    r_data = rounds_map[c_hash]
                    shares = r_data.get("shares")
                    # 4. Wallet weights / shares validation
                    if not isinstance(shares, dict) or not shares:
                        status = "blocked"
                        reason = "missing_share_data"
                    else:
                        # 5. Round weight validation
                        total_score = r_data.get("total_share_score", 0.0)
                        total_count = r_data.get("total_share_count", 0)

                        weight_mode = "share_difficulty_sum"
                        total_weight = total_score
                        if total_weight <= 0:
                            weight_mode = "accepted_share_count"
                            total_weight = total_count

                        if total_weight <= 0:
                            status = "blocked"
                            reason = "zero_total_round_weight"
                        else:
                            # 6. Internally consistent ready state
                            status = "ready_for_manual_review"
                            round_share_total = total_weight
                            
                            pool_fee_pct = float(os.getenv("PEPEPOW_POOL_FEE_PERCENT", "1.0"))
                            pool_fee_percent = pool_fee_pct
                            pool_fee_amount = gross_reward * pool_fee_pct / 100.0
                            net_reward = gross_reward - pool_fee_amount

                            for wallet, share_info in shares.items():
                                if weight_mode == "share_difficulty_sum":
                                    weight = share_info.get("share_score", 0.0)
                                else:
                                    weight = share_info.get("share_count", 0.0)
                                
                                amount = net_reward * weight / total_weight
                                payouts.append({
                                    "wallet": wallet,
                                    "weight": weight,
                                    "amount": amount,
                                    "status": "pending_manual_payment"
                                })

        shares_info = {}
        if c_hash in rounds_map:
            shares_info = rounds_map[c_hash].get("shares", {})

        payout_candidates.append({
            "candidate_hash": c_hash,
            "candidateId": c_hash,
            "blockHash": c_hash,
            "height": height,
            "lifecycle_status": l_status,
            "lifecycleStatus": l_status,
            "status": status,
            "reason": reason,
            "blockedReason": reason,
            "gross_reward": gross_reward,
            "grossReward": gross_reward,
            "net_reward": net_reward,
            "netReward": net_reward,
            "pool_fee_percent": pool_fee_percent,
            "poolFeePercent": pool_fee_percent,
            "pool_fee_amount": pool_fee_amount,
            "poolFeeAmount": pool_fee_amount,
            "weight_mode": weight_mode,
            "weightMode": weight_mode,
            "round_share_total": round_share_total,
            "roundShareTotal": round_share_total,
            "payouts": payouts,
            "shares": shares_info,
            "submit_timestamp": c.get("submit_timestamp"),
            "reward_source": reward_source,
            "rewardSource": reward_source
        })

    out_data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": payout_candidates
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

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
import base64
import urllib.request
import urllib.error
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

def load_env_vars() -> dict[str, str]:
    paths = [
        Path(os.getenv("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", "")) / "launch.env",
        Path(".runtime/live-stratum/launch.env"),
        Path(".runtime/systemd-smoke/core.env"),
    ]
    env = {}
    for p in paths:
        if p and p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            env[k.strip()] = v.strip()
                break
            except Exception:
                pass
    return env

def query_rpc(method: str, params: list[Any]) -> Any:
    env = load_env_vars()
    rpc_url = env.get("PEPEPOWD_RPC_URL")
    if not rpc_url:
        rpc_host = env.get("PEPEPOWD_RPC_HOST", "127.0.0.1")
        rpc_port = env.get("PEPEPOWD_RPC_PORT", "8834")
        rpc_url = f"http://{rpc_host}:{rpc_port}"
    rpc_user = env.get("PEPEPOWD_RPC_USER", "")
    rpc_password = env.get("PEPEPOWD_RPC_PASSWORD", "")
    
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "payout_helper",
        "method": method,
        "params": params,
    }).encode("utf-8")
    
    auth = base64.b64encode(f"{rpc_user}:{rpc_password}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if isinstance(res_data, dict):
                if res_data.get("error"):
                    return None
                return res_data.get("result")
    except Exception:
        pass
    return None

def fetch_block_info_from_daemon(block_hash: str) -> tuple[int | None, float | None]:
    # Try verbosity=2
    block_data = query_rpc("getblock", [block_hash, 2])
    if not isinstance(block_data, dict):
        # Fallback to verbosity=True
        block_data = query_rpc("getblock", [block_hash, True])
        
    if isinstance(block_data, dict):
        confirmations = block_data.get("confirmations")
        if confirmations is not None:
            try:
                confirmations = int(confirmations)
            except (ValueError, TypeError):
                confirmations = None
        
        tx_list = block_data.get("tx")
        total_reward = None
        if isinstance(tx_list, list) and tx_list:
            coinbase_tx = tx_list[0]
            if isinstance(coinbase_tx, str):
                coinbase_tx = query_rpc("getrawtransaction", [coinbase_tx, 1])
                
            if isinstance(coinbase_tx, dict):
                vout_list = coinbase_tx.get("vout")
                if isinstance(vout_list, list):
                    total_reward = 0.0
                    for out in vout_list:
                        if isinstance(out, dict):
                            val = out.get("value")
                            if val is not None:
                                total_reward += float(val)
        return confirmations, total_reward
    return None, None

def generate_payout_candidates(accepted_path: Path, rounds_path: Path, output_path: Path) -> int:
    paid_pairs = set()
    actions_log_path = output_path.parent / "payment-actions.jsonl"
    if actions_log_path.exists():
        try:
            with actions_log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        act = json.loads(line)
                        c_id = act.get("candidate_id")
                        w = act.get("wallet")
                        if c_id and w:
                            paid_pairs.add((c_id, w))
                    except Exception:
                        pass
        except Exception:
            pass

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

        daemon_confirmations = None
        if l_status == "confirmed":
            d_conf, d_reward = fetch_block_info_from_daemon(c_hash)
            daemon_confirmations = d_conf
            if reward is None and d_reward is not None:
                reward = d_reward
                reward_source = "daemon-rpc" if reward is not None else None

        status = "blocked"
        reason = None
        gross_reward = None
        net_reward = None
        pool_fee_percent = None
        pool_fee_amount = None
        weight_mode = None
        round_share_total = None
        payouts = []

        is_orphan = (l_status == "orphan")
        if (daemon_confirmations is not None and daemon_confirmations < 0) or (c_hash in rounds_map and rounds_map[c_hash].get("status") == "orphan"):
            is_orphan = True

        is_already_paid = False
        if c_hash in rounds_map:
            r_data = rounds_map[c_hash]
            shares = r_data.get("shares", {})
            if isinstance(shares, dict) and shares:
                if all((c_hash, w) in paid_pairs for w in shares):
                    is_already_paid = True
            else:
                if any(p[0] == c_hash for p in paid_pairs):
                    is_already_paid = True
        else:
            if any(p[0] == c_hash for p in paid_pairs):
                is_already_paid = True

        if is_already_paid:
            status = "blocked"
            reason = "blocked_already_paid"
        elif is_orphan:
            status = "blocked"
            reason = "orphan_block"
        elif l_status != "confirmed":
            status = "blocked"
            if l_status == "immature":
                reason = "immature_block"
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
                elif rounds_map[c_hash].get("status") == "orphan":
                    status = "blocked"
                    reason = "orphan_block"
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

def generate_payments_snapshot(
    actions_log_path: Path,
    snapshot_path: Path
) -> int:
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
                        existing_actions.append(act)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            print(f"Error reading payment actions log: {exc}", file=sys.stderr)
            return 1

    # Load pool snapshot to get current chain height
    pool_snap = load_pool_snapshot()
    current_height = pool_snap.get("network", {}).get("height") if isinstance(pool_snap, dict) else None

    # Load payout-candidates.json to enrich payment items with metadata if available
    candidates_map = {}
    candidates_file = snapshot_path.parent / "payout-candidates.json"
    if candidates_file.exists():
        try:
            with candidates_file.open("r", encoding="utf-8") as f:
                cand_data = json.load(f)
            if isinstance(cand_data, dict) and isinstance(cand_data.get("items"), list):
                for item in cand_data["items"]:
                    c_id = item.get("candidate_hash") or item.get("candidateId")
                    if c_id:
                        candidates_map[c_id] = item
        except Exception:
            pass

    # Load existing payments-snapshot.json to preserve fields and read existing metadata/confirmations
    existing_snapshot_items = {}
    if snapshot_path.exists():
        try:
            with snapshot_path.open("r", encoding="utf-8") as f:
                old_snap = json.load(f)
            if isinstance(old_snap, dict) and isinstance(old_snap.get("items"), list):
                for item in old_snap["items"]:
                    w = item.get("wallet")
                    txid = item.get("txid")
                    if w and txid:
                        existing_snapshot_items[(txid, w)] = item
        except Exception:
            pass

    items = []
    for act in existing_actions:
        txid = act.get("txid")
        w = act.get("wallet")
        c_id = act.get("candidate_id")

        # Initial default confirmations
        confirmations = 1

        # Locate existing item if available
        existing_item = existing_snapshot_items.get((txid, w)) if (txid and w) else None
        if existing_item:
            confirmations = existing_item.get("confirmations", 1)

        item = {
            "wallet": w,
            "amount": act.get("amount"),
            "paidAt": act.get("timestamp"),
            "confirmations": confirmations,
            "txid": txid
        }

        cand_meta = candidates_map.get(c_id) if c_id else None

        # Determine block height, candidate hash, block hash, status
        candidate_hash = None
        block_hash = None
        block_height = None
        status = None

        if cand_meta:
            candidate_hash = cand_meta.get("candidate_hash") or cand_meta.get("candidateId")
            block_hash = cand_meta.get("blockHash")
            block_height = cand_meta.get("height")
            status = cand_meta.get("status")
        elif existing_item:
            candidate_hash = existing_item.get("candidateHash")
            block_hash = existing_item.get("blockHash")
            block_height = existing_item.get("blockHeight")
            status = existing_item.get("status")

        # Populate metadata in item if found
        if candidate_hash is not None:
            item["candidateHash"] = candidate_hash
        if block_hash is not None:
            item["blockHash"] = block_hash
        if block_height is not None:
            item["blockHeight"] = block_height
        if status is not None:
            item["status"] = status

        # Recompute confirmations if blockHeight and currentHeight are available
        if current_height is not None and block_height is not None:
            try:
                h_val = int(block_height)
                item["confirmations"] = max(0, int(current_height) - h_val + 1)
            except (ValueError, TypeError):
                pass

        items.append(item)

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

    return generate_payments_snapshot(actions_log_path, snapshot_path)

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

    parser_rebuild = subparsers.add_parser("rebuild-payments-snapshot", help="Rebuild payments snapshot from actions log")
    parser_rebuild.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_rebuild.add_argument("--snapshot", type=str, required=True, help="Path to payments-snapshot.json")

    parser_refresh = subparsers.add_parser("refresh-payment-confirmations", help="Refresh payment confirmations in snapshot")
    parser_refresh.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_refresh.add_argument("--snapshot", type=str, required=True, help="Path to payments-snapshot.json")

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
    elif args.command == "rebuild-payments-snapshot":
        return generate_payments_snapshot(
            Path(args.actions_log),
            Path(args.snapshot)
        )
    elif args.command == "refresh-payment-confirmations":
        return generate_payments_snapshot(
            Path(args.actions_log),
            Path(args.snapshot)
        )

    return 0

if __name__ == "__main__":
    sys.exit(main())

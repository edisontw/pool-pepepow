#!/usr/bin/env python3
"""SOLO Payout Helper Tool for PEPEPOW Pool.

Generates read-only SOLO payout candidates for confirmed SOLO blocks.
SOLO candidates pay 100% of the net miner reward (minerRewardAmount - soloPoolFee)
to the block finder.

The output keeps the SOLO-specific ``solo_payout_candidates`` collection and
also exposes the same rows through the standard ``items`` collection consumed
by the shared guarded payout sender. Eligible payout rows use the standard
``pending_manual_payment`` status so the sender can re-validate aggregate
sources before any wallet RPC send.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

# Re-use read-only coinbase reward helpers and payment action loaders from payout_helper
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from payout_helper import (  # noqa: E402
    fetch_coinbase_reward_from_daemon,
    iter_jsonl_objects,
    load_paid_payment_pairs,
    NonBlockingFileLock,
)

DEFAULT_SOLO_FEE_PERCENT = 1.0
DEFAULT_SOLO_MIN_CONFIRMATIONS = 101


def quantize_amount(value: float | str | Decimal) -> float:
    """Quantize reward amounts to 8 decimal places using Decimal for precision."""
    d = Decimal(str(value))
    return float(d.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def build_solo_payout_candidate(
    candidate_record: dict[str, Any],
    coinbase_data: dict[str, Any],
    *,
    solo_fee_percent: float = DEFAULT_SOLO_FEE_PERCENT,
) -> dict[str, Any]:
    """Build a SOLO payout candidate structure for a confirmed SOLO candidate block."""
    candidate_hash = str(
        candidate_record.get("candidate_hash")
        or candidate_record.get("candidateBlockHash")
        or ""
    )
    candidate_id = f"solo:{candidate_hash}"
    wallet = str(candidate_record.get("wallet") or "").strip()
    worker = str(candidate_record.get("worker") or "default").strip()
    lifecycle_status = str(candidate_record.get("lifecycle_status") or "unknown")
    confirmations = candidate_record.get("confirmations")
    if confirmations is not None:
        try:
            confirmations = int(confirmations)
        except (ValueError, TypeError):
            confirmations = None

    miner_reward = coinbase_data.get("minerRewardAmount")
    gross_reward = float(miner_reward) if miner_reward is not None else 0.0
    gross_reward = quantize_amount(gross_reward)

    fee_percent = float(solo_fee_percent)
    solo_fee_amount = quantize_amount(gross_reward * (fee_percent / 100.0))
    net_reward = quantize_amount(gross_reward - solo_fee_amount)

    payouts = []
    if wallet and wallet != "unknown" and net_reward > 0:
        payouts.append(
            {
                "wallet": wallet,
                "amount": net_reward,
                "status": "pending_manual_payment",
            }
        )

    return {
        "candidateId": candidate_id,
        "candidateHash": candidate_hash,
        "miningMode": "solo",
        "lifecycleStatus": lifecycle_status,
        "confirmations": confirmations,
        "matchedHeight": candidate_record.get("matched_height"),
        "submitTimestamp": candidate_record.get("submit_timestamp"),
        "finderWallet": wallet,
        "finderWorker": worker,
        "grossReward": gross_reward,
        "soloFeePercent": fee_percent,
        "soloFeeAmount": solo_fee_amount,
        "netReward": net_reward,
        "weightMode": "solo_finder",
        "coinbaseTxid": coinbase_data.get("coinbaseTxid"),
        "coinbaseMatchesExpectedPoolWallet": coinbase_data.get("coinbaseMatchesExpectedPoolWallet"),
        "payouts": payouts,
    }


def evaluate_solo_eligibility(
    candidate: dict[str, Any],
    paid_pairs: set[tuple[str, str]] | None = None,
    min_confirmations: int = DEFAULT_SOLO_MIN_CONFIRMATIONS,
) -> tuple[bool, str | None]:
    """Check if a SOLO candidate block is eligible for SOLO payout."""
    mode = str(candidate.get("miningMode") or candidate.get("mining_mode") or "solo").strip().lower()
    if mode != "solo":
        return False, "not_solo_mode"

    status = str(candidate.get("lifecycleStatus") or candidate.get("lifecycle_status") or "")
    if status != "confirmed":
        return False, f"status_{status or 'unconfirmed'}"

    conf = candidate.get("confirmations")
    if conf is None or not isinstance(conf, int) or conf < min_confirmations:
        return False, f"insufficient_confirmations_{conf}"

    wallet = str(candidate.get("finderWallet") or candidate.get("wallet") or "").strip()
    if not wallet or wallet == "unknown":
        return False, "missing_finder_wallet"

    if candidate.get("coinbaseMatchesExpectedPoolWallet") is False:
        return False, "blocked_coinbase_reward_mismatch"

    payouts = candidate.get("payouts")
    if not isinstance(payouts, list) or not payouts:
        return False, "missing_payout_recipients"

    net_reward = candidate.get("netReward")
    if net_reward is None or float(net_reward) <= 0:
        return False, "invalid_net_reward"

    cand_id = str(candidate.get("candidateId") or candidate.get("candidate_hash") or "")
    if paid_pairs and cand_id and wallet:
        if (cand_id, wallet) in paid_pairs or (f"solo:{cand_id}", wallet) in paid_pairs:
            return False, "blocked_already_paid"

    return True, None


def generate_solo_payout_candidates(
    accepted_candidates_path: Path,
    output_path: Path,
    *,
    actions_log_path: Path | None = None,
    payments_snapshot_path: Path | None = None,
    solo_fee_percent: float = DEFAULT_SOLO_FEE_PERCENT,
    min_confirmations: int = DEFAULT_SOLO_MIN_CONFIRMATIONS,
    mock_coinbase_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Process accepted candidates log, filter SOLO mode candidates, generate candidate JSON."""
    if not accepted_candidates_path.exists():
        empty = {
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "solo_fee_percent": solo_fee_percent,
            "min_confirmations": min_confirmations,
            "solo_payout_candidates": [],
            "items": [],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(empty, indent=2, sort_keys=True), encoding="utf-8")
        return empty

    try:
        cand_data = json.loads(accepted_candidates_path.read_text(encoding="utf-8"))
        accepted_list = cand_data.get("accepted_candidates", [])
    except Exception as exc:
        print(f"Error reading accepted candidates: {exc}", file=sys.stderr)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "solo_fee_percent": solo_fee_percent,
            "min_confirmations": min_confirmations,
            "solo_payout_candidates": [],
            "items": [],
        }

    paid_pairs = set()
    if actions_log_path and actions_log_path.exists():
        paid_pairs = load_paid_payment_pairs(actions_log_path, None, payments_snapshot_path)

    solo_candidates = []
    for record in accepted_list:
        if not isinstance(record, dict):
            continue
        mode = str(record.get("mining_mode") or record.get("miningMode") or "pool").strip().lower()
        if mode != "solo":
            continue

        cand_hash = record.get("candidate_hash")
        matched_height = record.get("matched_height")

        # Fetch coinbase info from daemon or mock
        coinbase_info = {}
        if mock_coinbase_data and cand_hash in mock_coinbase_data:
            coinbase_info = mock_coinbase_data[cand_hash]
        elif matched_height is not None:
            try:
                coinbase_info = fetch_coinbase_reward_from_daemon(matched_height, cand_hash)
            except Exception as exc:
                coinbase_info = {"minerRewardAmount": None, "coinbaseLookupError": str(exc)}

        cand_obj = build_solo_payout_candidate(record, coinbase_info, solo_fee_percent=solo_fee_percent)
        is_eligible, ineligible_reason = evaluate_solo_eligibility(cand_obj, paid_pairs, min_confirmations)
        cand_obj["eligibleForPayout"] = is_eligible
        if ineligible_reason:
            cand_obj["ineligibleReason"] = ineligible_reason

        solo_candidates.append(cand_obj)

    result = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "solo_fee_percent": solo_fee_percent,
        "min_confirmations": min_confirmations,
        "solo_payout_candidates": solo_candidates,
        "items": solo_candidates,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="PEPEPOW Pure SOLO Payout Candidate Generator")
    parser.add_argument("--accepted-candidates", type=str, required=True, help="Path to accepted-candidates.json")
    parser.add_argument("--output", type=str, required=True, help="Path to output solo-payout-candidates.json")
    parser.add_argument("--solo-fee-percent", type=float, default=DEFAULT_SOLO_FEE_PERCENT, help="SOLO pool fee percentage")
    parser.add_argument("--min-confirmations", type=int, default=DEFAULT_SOLO_MIN_CONFIRMATIONS, help="Minimum confirmations for payout eligibility")
    parser.add_argument("--actions-log", type=str, default=None, help="Path to solo-payment-actions.jsonl")
    parser.add_argument("--payments-snapshot", type=str, default=None, help="Path to solo-payments-snapshot.json")

    args = parser.parse_args()
    cand_path = Path(args.accepted_candidates)
    out_path = Path(args.output)
    actions_path = Path(args.actions_log) if args.actions_log else None
    snap_path = Path(args.payments_snapshot) if args.payments_snapshot else None

    result = generate_solo_payout_candidates(
        cand_path,
        out_path,
        actions_log_path=actions_path,
        payments_snapshot_path=snap_path,
        solo_fee_percent=args.solo_fee_percent,
        min_confirmations=args.min_confirmations,
    )
    count = len(result.get("solo_payout_candidates", []))
    print(f"Processed {count} SOLO candidates saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
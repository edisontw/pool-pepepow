#!/usr/bin/env python3
"""Read-only payment consistency audit for PEPEPOW pool snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import payout_helper

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path(
    os.environ.get("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", str(REPO_ROOT / ".runtime/live-stratum"))
)
DEFAULT_TOLERANCE = Decimal("0.00000001")

OK = "OK"
MISSING_FROM_PAYMENTS_API = "MISSING_FROM_PAYMENTS_API"
MISSING_FROM_MINER_API = "MISSING_FROM_MINER_API"
DUPLICATE_TXID = "DUPLICATE_TXID"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
WALLET_MISMATCH = "WALLET_MISMATCH"
CONFIRMS_OR_HEIGHT_SUSPICIOUS = "CONFIRMS_OR_HEIGHT_SUSPICIOUS"
STALE_ADDRESS_ATTRIBUTION_HINT = "STALE_ADDRESS_ATTRIBUTION_HINT"


@dataclass(frozen=True)
class PaymentRecord:
    source: str
    source_index: int
    wallet: str
    txid: str
    amount: Decimal | None
    candidate_id: str
    timestamp: str
    height: int | None
    confirmations: int | None
    actor: str
    raw: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    return rows


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value is True or value is False:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount


def int_value(value: Any) -> int | None:
    if value is None or value is True or value is False:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def payment_candidate_id(item: dict[str, Any]) -> str:
    value = first_present(
        item,
        "candidate_id",
        "candidateId",
        "candidateHash",
        "candidate_hash",
        "blockHash",
        "roundId",
    )
    return str(value or "")


def payment_actor(item: dict[str, Any]) -> str:
    value = first_present(
        item,
        "worker",
        "workerName",
        "miner",
        "minerName",
        "username",
        "login",
        "account",
    )
    return str(value or "")


def normalize_record(source: str, index: int, item: dict[str, Any]) -> PaymentRecord:
    return PaymentRecord(
        source=source,
        source_index=index,
        wallet=str(item.get("wallet") or item.get("address") or ""),
        txid=str(item.get("txid") or item.get("transactionId") or item.get("hash") or ""),
        amount=decimal_value(first_present(item, "amount", "value", "totalAmount")),
        candidate_id=payment_candidate_id(item),
        timestamp=str(first_present(item, "timestamp", "paidAt", "time", "createdAt") or ""),
        height=int_value(first_present(item, "blockHeight", "height", "matchedHeight", "block_height")),
        confirmations=int_value(
            first_present(item, "confirmations", "confirms", "txConfirmations", "candidateConfirmations")
        ),
        actor=payment_actor(item),
        raw=item,
    )


def successful_action_records(actions_path: Path) -> list[PaymentRecord]:
    records: list[PaymentRecord] = []
    for index, action in enumerate(load_jsonl(actions_path)):
        if not payout_helper.action_represents_successful_payment(action):
            continue
        records.append(normalize_record("payment_actions", index, action))
    return records


def payment_snapshot_records(payments_path: Path) -> list[PaymentRecord]:
    data = load_json(payments_path)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return []
    records = []
    for index, item in enumerate(data["items"]):
        if isinstance(item, dict):
            records.append(normalize_record("payments_api_source", index, item))
    return records


def activity_miner_records(activity_path: Path) -> list[PaymentRecord]:
    data = load_json(activity_path)
    if not isinstance(data, dict) or not isinstance(data.get("miners"), dict):
        return []
    records: list[PaymentRecord] = []
    index = 0
    for wallet, miner_payload in data["miners"].items():
        if not isinstance(miner_payload, dict) or not isinstance(miner_payload.get("payments"), list):
            continue
        for item in miner_payload["payments"]:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("wallet", wallet)
            records.append(normalize_record("activity_miner_source", index, row))
            index += 1
    return records


def explorer_records(explorer_path: Path) -> list[PaymentRecord]:
    data = load_json(explorer_path)
    if data is None:
        return []
    if isinstance(data, dict):
        items = data.get("items") or data.get("transactions") or data.get("txs") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    records: list[PaymentRecord] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("outputs"), list):
            for out_index, output in enumerate(item["outputs"]):
                if not isinstance(output, dict):
                    continue
                row = dict(output)
                row.setdefault("txid", item.get("txid") or item.get("hash"))
                row.setdefault("height", item.get("height") or item.get("blockHeight"))
                row.setdefault("confirmations", item.get("confirmations") or item.get("confirms"))
                records.append(normalize_record("explorer_source", index * 1000 + out_index, row))
        else:
            records.append(normalize_record("explorer_source", index, item))
    return records


def key(record: PaymentRecord) -> tuple[str, str]:
    if record.candidate_id:
        return (record.candidate_id, record.wallet)
    return (record.txid, record.wallet)


def tx_wallet_amount_key(record: PaymentRecord) -> tuple[str, str, str]:
    amount = format(record.amount, "f") if record.amount is not None else ""
    return (record.wallet, record.txid, amount)


def matching_records(record: PaymentRecord, candidates: list[PaymentRecord]) -> list[PaymentRecord]:
    out = []
    record_key = key(record)
    for candidate in candidates:
        if record.txid and candidate.txid == record.txid and candidate.wallet == record.wallet:
            out.append(candidate)
        elif record_key != ("", "") and key(candidate) == record_key:
            out.append(candidate)
    return out


def issue(category: str, message: str, record: PaymentRecord | None = None, **details: Any) -> dict[str, Any]:
    payload = {"category": category, "message": message}
    if record is not None:
        payload.update(
            {
                "source": record.source,
                "sourceIndex": record.source_index,
                "wallet": record.wallet,
                "txid": record.txid,
                "candidateId": record.candidate_id,
            }
        )
    for k, v in details.items():
        if v is not None:
            payload[k] = v
    return payload


def compare_amounts(
    action: PaymentRecord,
    matches: list[PaymentRecord],
    tolerance: Decimal,
    source_label: str,
) -> list[dict[str, Any]]:
    issues = []
    if action.amount is None:
        return issues
    for match in matches:
        if match.amount is None:
            continue
        if abs(action.amount - match.amount) > tolerance:
            issues.append(
                issue(
                    AMOUNT_MISMATCH,
                    f"payment action amount differs from {source_label}",
                    action,
                    otherSource=match.source,
                    expected=str(action.amount),
                    actual=str(match.amount),
                    tolerance=str(tolerance),
                )
            )
    return issues


def compare_wallets_by_txid(action: PaymentRecord, records: list[PaymentRecord], source_label: str) -> list[dict[str, Any]]:
    if not action.txid:
        return []
    issues = []
    for record in records:
        if record.txid == action.txid and record.wallet and record.wallet != action.wallet:
            issues.append(
                issue(
                    WALLET_MISMATCH,
                    f"payment action txid maps to a different wallet in {source_label}",
                    action,
                    otherSource=record.source,
                    expected=action.wallet,
                    actual=record.wallet,
                )
            )
    return issues


def duplicate_issues(records: list[PaymentRecord]) -> list[dict[str, Any]]:
    issues = []
    by_txid: dict[tuple[str, str], list[PaymentRecord]] = defaultdict(list)
    by_exact: dict[tuple[str, str, str, str], list[PaymentRecord]] = defaultdict(list)
    for record in records:
        if record.txid:
            by_txid[(record.source, record.txid)].append(record)
            wallet, txid, amount = tx_wallet_amount_key(record)
            by_exact[(record.source, wallet, txid, amount)].append(record)
    for (source, txid), rows in sorted(by_txid.items()):
        unique_wallets = sorted({row.wallet for row in rows if row.wallet})
        if len(rows) > 1:
            issues.append(
                issue(
                    DUPLICATE_TXID,
                    "txid appears on multiple payment records",
                    rows[0],
                    txid=txid,
                    count=len(rows),
                    wallets=unique_wallets,
                    sources=[source],
                )
            )
    for exact_key, rows in sorted(by_exact.items()):
        source, wallet, txid, amount = exact_key
        if wallet and txid and amount and len(rows) > 1:
            issues.append(
                issue(
                    DUPLICATE_TXID,
                    "wallet+txid+amount appears on multiple payment records",
                    rows[0],
                    wallet=wallet,
                    txid=txid,
                    amount=amount,
                    count=len(rows),
                    sources=[source],
                )
            )
    return issues


def suspicious_height_issues(records: list[PaymentRecord], current_height: int | None) -> list[dict[str, Any]]:
    issues = []
    for record in records:
        if record.height is not None and record.height <= 0:
            issues.append(issue(CONFIRMS_OR_HEIGHT_SUSPICIOUS, "payment record has missing or invalid height", record))
        if record.confirmations is not None and record.confirmations < 0:
            issues.append(issue(CONFIRMS_OR_HEIGHT_SUSPICIOUS, "payment record has negative confirmations", record))
        if current_height is None:
            continue
        if record.height is not None and record.height > current_height + 1:
            issues.append(
                issue(
                    CONFIRMS_OR_HEIGHT_SUSPICIOUS,
                    "payment record height is ahead of current chain height",
                    record,
                    currentHeight=current_height,
                    height=record.height,
                )
            )
        if record.height is not None and record.confirmations is not None:
            expected_max = max(0, current_height - record.height + 1)
            if record.confirmations > expected_max + 1:
                issues.append(
                    issue(
                        CONFIRMS_OR_HEIGHT_SUSPICIOUS,
                        "payment record confirmations exceed height-derived range",
                        record,
                        currentHeight=current_height,
                        height=record.height,
                        confirmations=record.confirmations,
                    )
                )
    return issues


def stale_attribution_issues(actions: list[PaymentRecord]) -> list[dict[str, Any]]:
    by_actor: dict[str, list[PaymentRecord]] = defaultdict(list)
    for record in actions:
        hinted = first_present(record.raw, "currentWallet", "authorizedWallet", "latestWallet")
        if hinted and str(hinted) != record.wallet:
            yield issue(
                STALE_ADDRESS_ATTRIBUTION_HINT,
                "payment action carries a current wallet hint different from paid wallet",
                record,
                expected=str(hinted),
                actual=record.wallet,
            )
        if record.actor:
            by_actor[record.actor].append(record)
    for actor, records in by_actor.items():
        wallets = [record.wallet for record in records if record.wallet]
        if len(set(wallets)) <= 1:
            continue
        sorted_records = sorted(records, key=lambda row: row.timestamp)
        latest_wallet = sorted_records[-1].wallet
        for record in sorted_records[:-1]:
            if record.wallet and latest_wallet and record.wallet != latest_wallet:
                yield issue(
                    STALE_ADDRESS_ATTRIBUTION_HINT,
                    "same worker/miner appears across multiple payout wallets",
                    record,
                    actor=actor,
                    latestWallet=latest_wallet,
                )


def current_chain_height(pool_snapshot_path: Path) -> int | None:
    data = load_json(pool_snapshot_path)
    if not isinstance(data, dict):
        return None
    network = data.get("network")
    if isinstance(network, dict):
        height = int_value(network.get("height"))
        if height is not None:
            return height
    return int_value(data.get("height"))


def audit(
    actions_path: Path,
    payments_path: Path,
    activity_path: Path,
    pool_snapshot_path: Path,
    explorer_path: Path,
    tolerance: Decimal,
) -> dict[str, Any]:
    actions = successful_action_records(actions_path)
    payments = payment_snapshot_records(payments_path)
    activity_miners = activity_miner_records(activity_path)
    explorer = explorer_records(explorer_path) if explorer_path.exists() else []
    miner_api_source = payments + activity_miners
    all_local_records = actions + payments + activity_miners
    if explorer:
        all_local_records += explorer

    issues: list[dict[str, Any]] = []
    for action in actions:
        payment_matches = matching_records(action, payments)
        if not payment_matches:
            issues.append(issue(MISSING_FROM_PAYMENTS_API, "successful payment action is absent from payments API source", action))
        else:
            issues.extend(compare_amounts(action, payment_matches, tolerance, "payments API source"))
            issues.extend(compare_wallets_by_txid(action, payments, "payments API source"))

        miner_matches = matching_records(action, miner_api_source)
        if not miner_matches:
            issues.append(issue(MISSING_FROM_MINER_API, "successful payment action is absent from miner API source", action))
        else:
            issues.extend(compare_amounts(action, miner_matches, tolerance, "miner API source"))
            issues.extend(compare_wallets_by_txid(action, miner_api_source, "miner API source"))

        if explorer:
            explorer_matches = matching_records(action, explorer)
            issues.extend(compare_amounts(action, explorer_matches, tolerance, "explorer source"))
            issues.extend(compare_wallets_by_txid(action, explorer, "explorer source"))

    issues.extend(duplicate_issues(all_local_records))
    issues.extend(suspicious_height_issues(all_local_records, current_chain_height(pool_snapshot_path)))
    issues.extend(stale_attribution_issues(actions))

    categories = sorted({item["category"] for item in issues}) or [OK]
    return {
        "generatedAt": utc_now(),
        "status": OK if not issues else "warning",
        "categories": categories,
        "counts": {
            "successfulPaymentActions": len(actions),
            "paymentsApiSourceRecords": len(payments),
            "activityMinerSourceRecords": len(activity_miners),
            "explorerSourceRecords": len(explorer),
            "issues": len(issues),
        },
        "sources": {
            "paymentActions": str(actions_path),
            "paymentsApiSource": str(payments_path),
            "activityMinerSource": str(activity_path),
            "poolSnapshot": str(pool_snapshot_path),
            "explorerSource": str(explorer_path) if explorer_path.exists() else None,
        },
        "issues": issues,
    }


def print_human(result: dict[str, Any]) -> None:
    print("Payment Consistency Audit")
    print(f"status: {result['status']}")
    print(f"categories: {', '.join(result['categories'])}")
    counts = result["counts"]
    print(
        "counts: "
        f"actions={counts['successfulPaymentActions']} "
        f"payments={counts['paymentsApiSourceRecords']} "
        f"miner={counts['activityMinerSourceRecords']} "
        f"explorer={counts['explorerSourceRecords']} "
        f"issues={counts['issues']}"
    )
    for item in result["issues"][:20]:
        detail = item.get("txid") or item.get("candidateId") or ""
        print(f"- {item['category']}: {item['message']} {detail}".rstrip())
    if len(result["issues"]) > 20:
        print(f"- ... {len(result['issues']) - 20} more")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only payment consistency audit")
    parser.add_argument("--actions-log", type=Path, default=RUNTIME_DIR / "payment-actions.jsonl")
    parser.add_argument("--payments-snapshot", type=Path, default=RUNTIME_DIR / "payments-snapshot.json")
    parser.add_argument("--activity-snapshot", type=Path, default=RUNTIME_DIR / "activity-snapshot.json")
    parser.add_argument("--pool-snapshot", type=Path, default=RUNTIME_DIR / "pool-snapshot.json")
    parser.add_argument("--explorer-transactions", type=Path, default=RUNTIME_DIR / "explorer-transactions.json")
    parser.add_argument("--tolerance", default=str(DEFAULT_TOLERANCE))
    parser.add_argument("--format", choices=("human", "json", "both"), default="human")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    tolerance = decimal_value(args.tolerance)
    if tolerance is None or tolerance < 0:
        print("payment_consistency_audit: invalid --tolerance", file=sys.stderr)
        return 2
    result = audit(
        args.actions_log,
        args.payments_snapshot,
        args.activity_snapshot,
        args.pool_snapshot,
        args.explorer_transactions,
        tolerance,
    )
    if args.format in {"human", "both"}:
        print_human(result)
    if args.format == "both":
        print("")
    if args.format in {"json", "both"}:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == OK else 1


if __name__ == "__main__":
    raise SystemExit(main())

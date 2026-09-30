#!/usr/bin/env python3
"""Read-only payment consistency audit for PEPEPOW pool snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
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
DEFAULT_ISSUE_LIMIT = 50
DEFAULT_SNAPSHOT_PATH = RUNTIME_DIR / "payment-audit.json"

OK = "OK"
MISSING_FROM_PAYMENTS_API = "MISSING_FROM_PAYMENTS_API"
MISSING_FROM_MINER_API = "MISSING_FROM_MINER_API"
DUPLICATE_TXID = "DUPLICATE_TXID"
DUPLICATE_ACTION_RECORD = "DUPLICATE_ACTION_RECORD"
DUPLICATE_ACTION_TXID_REWRITE_HINT = "DUPLICATE_ACTION_TXID_REWRITE_HINT"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
WALLET_MISMATCH = "WALLET_MISMATCH"
CONFIRMS_OR_HEIGHT_SUSPICIOUS = "CONFIRMS_OR_HEIGHT_SUSPICIOUS"
STALE_ADDRESS_ATTRIBUTION_HINT = "STALE_ADDRESS_ATTRIBUTION_HINT"

CARRY_METADATA_KEYS = {
    "carrySourceCandidateIds",
    "carry_source_candidate_ids",
    "carrySourceCount",
    "carry_source_count",
}
TIMESTAMP_KEYS = {"timestamp", "paidAt", "time", "createdAt"}


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
    current_wallet_hint: str
    has_carry_metadata: bool
    duplicate_signature: str


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


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def iter_jsonl(path: Path):
    """Yield JSON object rows without retaining the append-only source log."""
    if not path.exists():
        return
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
                    yield row
    except OSError:
        return


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
    ignored = CARRY_METADATA_KEYS | TIMESTAMP_KEYS
    normalized = {key: value for key, value in item.items() if key not in ignored}
    signature = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
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
        current_wallet_hint=str(first_present(item, "currentWallet", "authorizedWallet", "latestWallet") or ""),
        has_carry_metadata=any(key in item for key in CARRY_METADATA_KEYS),
        duplicate_signature=signature,
    )


def successful_action_records(actions_path: Path) -> list[PaymentRecord]:
    records: list[PaymentRecord] = []
    for index, action in enumerate(iter_jsonl(actions_path)):
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


def duplicate_action_rewrite_issue(rows: list[PaymentRecord]) -> dict[str, Any] | None:
    if len(rows) <= 1 or any(row.source != "payment_actions" for row in rows):
        return None
    wallets = {row.wallet for row in rows}
    amounts = {format(row.amount, "f") if row.amount is not None else "" for row in rows}
    candidates = {row.candidate_id for row in rows}
    same_wallet = len(wallets) == 1
    same_amount = len(amounts) == 1
    same_candidate = len(candidates) == 1
    if not (same_wallet and same_amount and same_candidate):
        return None
    if len({row.duplicate_signature for row in rows}) != 1:
        return None

    timestamps = sorted(row.timestamp for row in rows if row.timestamp)
    carry_metadata_present = any(row.has_carry_metadata for row in rows)
    category = DUPLICATE_ACTION_TXID_REWRITE_HINT if carry_metadata_present else DUPLICATE_ACTION_RECORD
    return issue(
        category,
        "successful payment action txid appears on duplicate action records",
        rows[0],
        txid=rows[0].txid,
        count=len(rows),
        firstTimestamp=timestamps[0] if timestamps else "",
        lastTimestamp=timestamps[-1] if timestamps else "",
        recordIndexes=[row.source_index for row in rows],
        sameWallet=same_wallet,
        sameAmount=same_amount,
        sameCandidate=same_candidate,
        hasCarryMetadata=carry_metadata_present,
    )


def matching_records(record: PaymentRecord, candidates: list[PaymentRecord]) -> list[PaymentRecord]:
    out = []
    record_key = key(record)
    for candidate in candidates:
        if record.txid and candidate.txid == record.txid and candidate.wallet == record.wallet:
            out.append(candidate)
        elif record_key != ("", "") and key(candidate) == record_key:
            out.append(candidate)
    return out


class RecordIndex:
    """Compact lookup indexes for the bounded JSON snapshots."""

    def __init__(self, records: list[PaymentRecord]):
        self.by_tx_wallet: dict[tuple[str, str], list[PaymentRecord]] = defaultdict(list)
        self.by_candidate_wallet: dict[tuple[str, str], list[PaymentRecord]] = defaultdict(list)
        self.by_txid: dict[str, list[PaymentRecord]] = defaultdict(list)
        for record in records:
            if record.txid:
                self.by_tx_wallet[(record.txid, record.wallet)].append(record)
                self.by_txid[record.txid].append(record)
            if record.candidate_id or record.wallet:
                self.by_candidate_wallet[key(record)].append(record)

    def matches(self, record: PaymentRecord) -> list[PaymentRecord]:
        matches = list(self.by_tx_wallet.get((record.txid, record.wallet), [])) if record.txid else []
        seen = {id(item) for item in matches}
        for item in self.by_candidate_wallet.get(key(record), []):
            if id(item) not in seen:
                matches.append(item)
                seen.add(id(item))
        return matches


class IssueCollector:
    def __init__(self, limit: int = DEFAULT_ISSUE_LIMIT):
        self.limit = limit
        self.items: list[dict[str, Any]] = []
        self.categories: set[str] = set()
        self.category_counts: dict[str, int] = defaultdict(int)
        self.total = 0

    def add(self, item: dict[str, Any]) -> None:
        self.total += 1
        self.categories.add(item["category"])
        self.category_counts[item["category"]] += 1
        if len(self.items) < self.limit:
            self.items.append(item)

    def extend(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            self.add(item)


class ActionDuplicateIndex:
    """Aggregate duplicate state without retaining historical action rows."""

    def __init__(self):
        self.by_txid: dict[str, dict[str, Any]] = {}
        self.by_exact: dict[tuple[str, str, str], dict[str, Any]] = {}

    @staticmethod
    def _state(record: PaymentRecord) -> dict[str, Any]:
        return {
            "count": 0,
            "wallets": set(), "amounts": set(), "candidates": set(), "signatures": set(),
            "carry": False, "first": "", "last": "", "indexes": [], "record": record,
        }

    @staticmethod
    def _add(state: dict[str, Any], record: PaymentRecord) -> None:
        state["count"] += 1
        state["wallets"].add(record.wallet)
        state["amounts"].add(format(record.amount, "f") if record.amount is not None else "")
        state["candidates"].add(record.candidate_id)
        state["signatures"].add(record.duplicate_signature)
        state["carry"] = state["carry"] or record.has_carry_metadata
        if record.timestamp:
            state["first"] = min(state["first"], record.timestamp) if state["first"] else record.timestamp
            state["last"] = max(state["last"], record.timestamp)
        if len(state["indexes"]) < DEFAULT_ISSUE_LIMIT:
            state["indexes"].append(record.source_index)

    def add(self, record: PaymentRecord) -> None:
        if not record.txid:
            return
        tx_state = self.by_txid.setdefault(record.txid, self._state(record))
        self._add(tx_state, record)
        exact = (record.wallet, record.txid, format(record.amount, "f") if record.amount is not None else "")
        exact_state = self.by_exact.setdefault(exact, self._state(record))
        self._add(exact_state, record)

    @staticmethod
    def _rewrite(state: dict[str, Any]) -> bool:
        return (
            state["count"] > 1 and len(state["wallets"]) == len(state["amounts"]) == len(state["candidates"]) == 1
            and len(state["signatures"]) == 1
        )

    def issues(self) -> list[dict[str, Any]]:
        result = []
        for txid, state in sorted(self.by_txid.items()):
            if state["count"] <= 1:
                continue
            record = state["record"]
            if self._rewrite(state):
                category = DUPLICATE_ACTION_TXID_REWRITE_HINT if state["carry"] else DUPLICATE_ACTION_RECORD
                result.append(issue(category, "successful payment action txid appears on duplicate action records", record,
                                    txid=txid, count=state["count"], firstTimestamp=state["first"], lastTimestamp=state["last"],
                                    recordIndexes=state["indexes"], sameWallet=True, sameAmount=True, sameCandidate=True,
                                    hasCarryMetadata=state["carry"]))
            else:
                result.append(issue(DUPLICATE_TXID, "txid appears on multiple payment records", record,
                                    txid=txid, count=state["count"], wallets=sorted(wallet for wallet in state["wallets"] if wallet),
                                    sources=["payment_actions"]))
        for (wallet, txid, amount), state in sorted(self.by_exact.items()):
            if state["count"] > 1 and not self._rewrite(state):
                result.append(issue(DUPLICATE_TXID, "wallet+txid+amount appears on multiple payment records", state["record"],
                                    wallet=wallet, txid=txid, amount=amount, count=state["count"], sources=["payment_actions"]))
        return result


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
            action_rewrite_issue = duplicate_action_rewrite_issue(rows)
            if action_rewrite_issue is not None:
                issues.append(action_rewrite_issue)
            else:
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
            if duplicate_action_rewrite_issue(rows) is not None:
                continue
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
        if record.current_wallet_hint and record.current_wallet_hint != record.wallet:
            yield issue(
                STALE_ADDRESS_ATTRIBUTION_HINT,
                "payment action carries a current wallet hint different from paid wallet",
                record,
                expected=record.current_wallet_hint,
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
    payments = payment_snapshot_records(payments_path)
    activity_miners = activity_miner_records(activity_path)
    explorer = explorer_records(explorer_path) if explorer_path.exists() else []
    miner_api_source = payments + activity_miners
    payment_index = RecordIndex(payments)
    miner_index = RecordIndex(miner_api_source)
    explorer_index = RecordIndex(explorer)
    current_height = current_chain_height(pool_snapshot_path)
    collector = IssueCollector()
    action_duplicates = ActionDuplicateIndex()
    action_count = 0
    actor_wallets: dict[str, dict[str, PaymentRecord]] = defaultdict(dict)

    # payment-actions.jsonl is append-only: process successful records once and
    # retain only duplicate/attribution aggregate state, never the full rows.
    for index, row in enumerate(iter_jsonl(actions_path)):
        if not payout_helper.action_represents_successful_payment(row):
            continue
        action = normalize_record("payment_actions", index, row)
        action_count += 1
        action_duplicates.add(action)
        if action.current_wallet_hint and action.current_wallet_hint != action.wallet:
            collector.add(issue(STALE_ADDRESS_ATTRIBUTION_HINT,
                                "payment action carries a current wallet hint different from paid wallet", action,
                                expected=action.current_wallet_hint, actual=action.wallet))
        if action.actor and action.wallet:
            prior = actor_wallets[action.actor].get(action.wallet)
            if prior is None or action.timestamp >= prior.timestamp:
                actor_wallets[action.actor][action.wallet] = action

        payment_matches = payment_index.matches(action)
        if not payment_matches:
            collector.add(issue(MISSING_FROM_PAYMENTS_API, "successful payment action is absent from payments API source", action))
        else:
            collector.extend(compare_amounts(action, payment_matches, tolerance, "payments API source"))
            collector.extend(compare_wallets_by_txid(action, payment_index.by_txid.get(action.txid, []), "payments API source"))

        miner_matches = miner_index.matches(action)
        if not miner_matches:
            collector.add(issue(MISSING_FROM_MINER_API, "successful payment action is absent from miner API source", action))
        else:
            collector.extend(compare_amounts(action, miner_matches, tolerance, "miner API source"))
            collector.extend(compare_wallets_by_txid(action, miner_index.by_txid.get(action.txid, []), "miner API source"))

        if explorer:
            explorer_matches = explorer_index.matches(action)
            collector.extend(compare_amounts(action, explorer_matches, tolerance, "explorer source"))
            collector.extend(compare_wallets_by_txid(action, explorer_index.by_txid.get(action.txid, []), "explorer source"))
        collector.extend(suspicious_height_issues([action], current_height))

    collector.extend(action_duplicates.issues())
    for actor, wallets in actor_wallets.items():
        if len(wallets) <= 1:
            continue
        latest = max(wallets.values(), key=lambda record: record.timestamp)
        for record in wallets.values():
            if record.wallet != latest.wallet:
                collector.add(issue(STALE_ADDRESS_ATTRIBUTION_HINT,
                                    "same worker/miner appears across multiple payout wallets", record,
                                    actor=actor, latestWallet=latest.wallet))

    bounded_records = payments + activity_miners + explorer
    collector.extend(duplicate_issues(bounded_records))
    collector.extend(suspicious_height_issues(bounded_records, current_height))

    categories = sorted(collector.categories) or [OK]
    return {
        "generatedAt": utc_now(),
        "status": OK if collector.total == 0 else "warning",
        "categories": categories,
        "counts": {
            "successfulPaymentActions": action_count,
            "paymentsApiSourceRecords": len(payments),
            "activityMinerSourceRecords": len(activity_miners),
            "explorerSourceRecords": len(explorer),
            "issues": collector.total,
            "issuesByCategory": dict(sorted(collector.category_counts.items())),
        },
        "sources": {
            "paymentActions": str(actions_path),
            "paymentsApiSource": str(payments_path),
            "activityMinerSource": str(activity_path),
            "poolSnapshot": str(pool_snapshot_path),
            "explorerSource": str(explorer_path) if explorer_path.exists() else None,
        },
        "issues": collector.items,
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
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--no-write", action="store_true")
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
    if not args.no_write:
        atomic_write_json(args.output, result)
    if args.format in {"human", "both"}:
        print_human(result)
    if args.format == "both":
        print("")
    if args.format in {"json", "both"}:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == OK else 1


if __name__ == "__main__":
    raise SystemExit(main())

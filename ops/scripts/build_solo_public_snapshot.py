#!/usr/bin/env python3
"""Build read-only Pure SOLO API snapshots from canonical and legacy snapshots.

This output is display-only. Payout/accounting must continue to read the canonical
/var/lib/pepepow-pool/solo runtime directly.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PUBLIC_BLOCK_STATUSES = {"chain_match_found", "immature", "confirmed"}


def _load_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _candidate_key(item: dict[str, Any]) -> str | None:
    value = item.get("candidate_hash") or item.get("candidateHash") or item.get("hash")
    return value if isinstance(value, str) and value else None


def _payment_key(item: dict[str, Any]) -> tuple[str, ...]:
    txid = item.get("txid") or item.get("transactionId") or item.get("transaction_id")
    if isinstance(txid, str) and txid:
        return ("txid", txid)
    return (
        "fallback",
        str(item.get("candidateId") or item.get("candidate_id") or ""),
        str(item.get("wallet") or ""),
        str(item.get("amount") or ""),
        str(item.get("paidAt") or item.get("timestamp") or ""),
    )


def merge_candidates(current_path: Path, legacy_path: Path) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    # Legacy first; canonical current data wins on duplicate hashes.
    for path in (legacy_path, current_path):
        rows = _load_dict(path).get("accepted_candidates", [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            status = item.get("lifecycle_status") or item.get("lifecycleStatus")
            if status not in PUBLIC_BLOCK_STATUSES:
                continue
            key = _candidate_key(item)
            if key:
                merged[key] = dict(item)
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("submit_timestamp") or item.get("timestamp") or ""),
    )


def merge_payments(current_path: Path, legacy_path: Path) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for path in (legacy_path, current_path):
        rows = _load_dict(path).get("items", [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                merged[_payment_key(item)] = dict(item)
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("paidAt") or item.get("timestamp") or ""),
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-candidates", type=Path, required=True)
    parser.add_argument("--legacy-candidates", type=Path, required=True)
    parser.add_argument("--current-payments", type=Path, required=True)
    parser.add_argument("--legacy-payments", type=Path, required=True)
    parser.add_argument("--output-candidates", type=Path, required=True)
    parser.add_argument("--output-payments", type=Path, required=True)
    args = parser.parse_args()

    candidates = merge_candidates(args.current_candidates, args.legacy_candidates)
    payments = merge_payments(args.current_payments, args.legacy_payments)
    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    _write_json(
        args.output_candidates,
        {"updated_at": updated_at, "accepted_candidates": candidates},
    )
    _write_json(
        args.output_payments,
        {"updated_at": updated_at, "items": payments},
    )

    print(
        "solo-public-snapshot:"
        f" blocks={len(candidates)}"
        f" payments={len(payments)}"
        f" candidates={args.output_candidates}"
        f" payments_path={args.output_payments}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

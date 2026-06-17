#!/usr/bin/env python3
"""Build a public-safe operator status snapshot from read-only diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import payment_consistency_audit
import pool_health_summary


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path(
    os.environ.get("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", str(REPO_ROOT / ".runtime/live-stratum"))
)
OUTPUT_PATH = Path(
    os.environ.get("PEPEPOW_OPERATOR_STATUS_OUTPUT", str(RUNTIME_DIR / "operator-status.json"))
)

STATUSES = {"ok", "warning", "error", "unknown"}
SEVERITY = {"ok": 0, "unknown": 1, "warning": 2, "error": 3}
REWRITE_HINT_ONLY = {payment_consistency_audit.DUPLICATE_ACTION_TXID_REWRITE_HINT}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def safe_status(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    if text in {"ok", "baseline", "healthy", "fresh"}:
        return "ok"
    if text in {"warning", "warn", "degraded", "delayed"}:
        return "warning"
    if text in {"error", "critical", "failed", "failure"}:
        return "error"
    return text if text in STATUSES else "unknown"


def aggregate_status(items: list[dict[str, str]]) -> str:
    status = "ok"
    for item in items:
        item_status = safe_status(item.get("status"))
        if SEVERITY[item_status] > SEVERITY[status]:
            status = item_status
    return status


def pool_health_item(summary: dict[str, Any], stale_seconds: float) -> dict[str, str]:
    try:
        api_snapshots = summary.get("apiSnapshots") if isinstance(summary, dict) else None
        api_available = bool(api_snapshots.get("available")) if isinstance(api_snapshots, dict) else False
        age_values = []
        for key in ("roundsSnapshot", "paymentsSnapshot"):
            section = summary.get(key)
            if isinstance(section, dict):
                age = section.get("ageSeconds")
                if isinstance(age, (int, float)) and age >= 0:
                    age_values.append(float(age))
        if api_available and (not age_values or max(age_values) <= stale_seconds):
            status = "ok"
            message = "Snapshots fresh"
        elif api_available:
            status = "warning"
            message = "Snapshot delayed"
        else:
            status = "unknown"
            message = "Status unavailable"
    except Exception:
        status = "unknown"
        message = "Status unavailable"
    return {
        "key": "pool_health",
        "label": "Pool Health",
        "status": status,
        "message": message,
    }


def wallet_watchdog_item(snapshot: dict[str, Any] | None) -> dict[str, str]:
    status = safe_status(snapshot.get("status") if isinstance(snapshot, dict) else None)
    if status == "ok":
        message = "Wallet growth normal"
    elif status in {"warning", "error"}:
        message = "Review wallet growth"
    else:
        message = "Status unavailable"
    return {
        "key": "wallet_watchdog",
        "label": "Wallet Watchdog",
        "status": status,
        "message": message,
    }


def payment_audit_item(result: dict[str, Any]) -> dict[str, str]:
    categories = result.get("categories") if isinstance(result, dict) else None
    category_set = {str(item) for item in categories} if isinstance(categories, list) else set()
    raw_status = str(result.get("status") or "").strip().upper() if isinstance(result, dict) else ""

    if raw_status == payment_consistency_audit.OK or category_set == {payment_consistency_audit.OK}:
        status = "ok"
        message = "Payments consistent"
    elif category_set and category_set <= REWRITE_HINT_ONLY:
        status = "warning"
        message = "Payment records need review"
    elif raw_status:
        status = "error"
        message = "Payment records need review"
    else:
        status = "unknown"
        message = "Status unavailable"

    return {
        "key": "payment_audit",
        "label": "Payment Audit",
        "status": status,
        "message": message,
    }


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def build_operator_status(args: argparse.Namespace) -> dict[str, Any]:
    runtime_dir = Path(args.runtime_dir)
    health_args = argparse.Namespace(
        runtime_dir=str(runtime_dir),
        activity_snapshot=args.activity_snapshot,
        rounds_snapshot=args.rounds_snapshot,
        payments_snapshot=args.payments_snapshot,
        accepted_candidates=args.accepted_candidates,
        share_log=args.share_log,
        watchdog_snapshot=args.watchdog_snapshot,
        launch_env=args.launch_env,
        api_pool_snapshot=args.pool_snapshot,
    )
    health = pool_health_summary.build_summary(health_args)
    watchdog = read_json(Path(args.watchdog_snapshot or runtime_dir / "pool-wallet-watchdog.json"))
    audit_result = payment_consistency_audit.audit(
        Path(args.actions_log),
        Path(args.payments_snapshot or runtime_dir / "payments-snapshot.json"),
        Path(args.activity_snapshot or runtime_dir / "activity-snapshot.json"),
        Path(args.pool_snapshot or runtime_dir / "pool-snapshot.json"),
        Path(args.explorer_transactions),
        Decimal(str(args.tolerance)),
    )
    items = [
        pool_health_item(health, args.snapshot_stale_seconds),
        wallet_watchdog_item(watchdog),
        payment_audit_item(audit_result),
    ]
    return {
        "generatedAt": utc_now(),
        "status": aggregate_status(items),
        "items": items,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write public-safe operator status JSON")
    parser.add_argument("--runtime-dir", default=str(RUNTIME_DIR))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--activity-snapshot", default=None)
    parser.add_argument("--rounds-snapshot", default=None)
    parser.add_argument("--payments-snapshot", default=None)
    parser.add_argument("--accepted-candidates", default=None)
    parser.add_argument("--share-log", default=None)
    parser.add_argument("--watchdog-snapshot", default=None)
    parser.add_argument("--launch-env", default=None)
    parser.add_argument("--pool-snapshot", default=None)
    parser.add_argument("--actions-log", default=str(RUNTIME_DIR / "payment-actions.jsonl"))
    parser.add_argument("--explorer-transactions", default=str(RUNTIME_DIR / "explorer-transactions.json"))
    parser.add_argument("--tolerance", default=str(payment_consistency_audit.DEFAULT_TOLERANCE))
    parser.add_argument("--snapshot-stale-seconds", type=float, default=300.0)
    parser.add_argument("--format", choices=("human", "json", "both"), default="human")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def print_human(payload: dict[str, Any], output_path: Path | None) -> None:
    print(f"status: {payload.get('status')}")
    for item in payload.get("items", []):
        if isinstance(item, dict):
            print(f"{item.get('key')}: {item.get('status')} - {item.get('message')}")
    if output_path is not None:
        print(f"snapshot: {output_path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_operator_status(args)
    output_path = Path(args.output)
    if not args.no_write:
        atomic_write_json(output_path, payload)
    if args.format in {"human", "both"}:
        print_human(payload, None if args.no_write else output_path)
    if args.format == "both":
        print("")
    if args.format in {"json", "both"}:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 1 if payload["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())

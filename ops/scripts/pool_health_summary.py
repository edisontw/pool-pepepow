#!/usr/bin/env python3
"""Read-only pool health summary from existing PEPEPOW pool snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path(
    os.environ.get("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", str(REPO_ROOT / ".runtime/live-stratum"))
)
FAILED_PAYMENT_STATUSES = {
    "failed",
    "error",
    "blocked",
    "reserved",
    "dry_run",
    "preflight",
    "blocked_real_wallet_payout_disabled",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value is True or value is False:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(value: Any, now: datetime) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def file_status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    readable = False
    if exists:
        try:
            with path.open("rb"):
                readable = True
        except Exception:
            readable = False
    return {
        "path": str(path),
        "exists": exists,
        "readable": readable,
    }


def env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def config_value(key: str, launch_env: dict[str, str], default: str) -> str:
    return os.environ.get(key) or launch_env.get(key) or default


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def newest_timestamp(items: list[Any], *keys: str) -> str | None:
    newest: datetime | None = None
    newest_raw: str | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = first_present(item, *keys)
        parsed = parse_timestamp(raw)
        if parsed is None:
            continue
        if newest is None or parsed > newest:
            newest = parsed
            newest_raw = parsed.isoformat().replace("+00:00", "Z")
    return newest_raw


def latest_share_from_activity(activity: Any) -> str | None:
    if not isinstance(activity, dict):
        return None
    meta = activity.get("meta")
    if isinstance(meta, dict):
        raw = first_present(meta, "lastShareAt", "activityLastShareAt")
        parsed = parse_timestamp(raw)
        if parsed is not None:
            return parsed.isoformat().replace("+00:00", "Z")
    return None


def latest_share_from_tail(path: Path, max_bytes: int = 65536) -> str | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    newest: datetime | None = None
    for line in data.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        status = str(first_present(payload, "status", "result", "outcome") or "").lower()
        if status and status not in {"accepted", "ok", "valid"}:
            continue
        raw = first_present(payload, "timestamp", "submittedAt", "observedAt")
        parsed = parse_timestamp(raw)
        if parsed is not None and (newest is None or parsed > newest):
            newest = parsed
    if newest is None:
        return None
    return newest.isoformat().replace("+00:00", "Z")


def confirmed_block_timestamp(accepted: Any, rounds: Any) -> str | None:
    accepted_items = []
    if isinstance(accepted, dict) and isinstance(accepted.get("accepted_candidates"), list):
        accepted_items = [
            item
            for item in accepted["accepted_candidates"]
            if isinstance(item, dict) and item.get("lifecycle_status") == "confirmed"
        ]
    accepted_ts = newest_timestamp(accepted_items, "submit_timestamp", "timestamp", "matchedAt")

    round_items = []
    if isinstance(rounds, dict) and isinstance(rounds.get("rounds"), list):
        round_items = [
            item
            for item in rounds["rounds"]
            if isinstance(item, dict) and item.get("status") == "confirmed"
        ]
    rounds_ts = newest_timestamp(round_items, "submit_timestamp", "timestamp")

    parsed = [ts for ts in [accepted_ts, rounds_ts] if parse_timestamp(ts) is not None]
    return newest_timestamp([{"timestamp": ts} for ts in parsed], "timestamp")


def successful_payout_timestamp(payments: Any) -> str | None:
    if not isinstance(payments, dict) or not isinstance(payments.get("items"), list):
        return None
    items = []
    for item in payments["items"]:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status in FAILED_PAYMENT_STATUSES:
            continue
        if not first_present(item, "txid", "transactionId"):
            continue
        items.append(item)
    return newest_timestamp(items, "paidAt", "timestamp", "createdAt")


def snapshot_age(data: Any, path: Path, now: datetime) -> float | None:
    if isinstance(data, dict):
        raw = first_present(data, "updated_at", "generatedAt", "generated_at", "createdAt")
        parsed_age = age_seconds(raw, now)
        if parsed_age is not None:
            return parsed_age
    if path.exists():
        try:
            return max(0.0, now.timestamp() - path.stat().st_mtime)
        except Exception:
            return None
    return None


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    runtime_dir = Path(args.runtime_dir)
    def runtime_path(arg_value: str | None, filename: str) -> Path:
        return Path(arg_value) if arg_value else runtime_dir / filename

    paths = {
        "activity": runtime_path(args.activity_snapshot, "activity-snapshot.json"),
        "rounds": runtime_path(args.rounds_snapshot, "rounds-snapshot.json"),
        "payments": runtime_path(args.payments_snapshot, "payments-snapshot.json"),
        "accepted": runtime_path(args.accepted_candidates, "accepted-candidates.json"),
        "shareLog": runtime_path(args.share_log, "share-events.jsonl"),
        "watchdog": runtime_path(args.watchdog_snapshot, "pool-wallet-watchdog.json"),
        "launchEnv": runtime_path(args.launch_env, "launch.env"),
        "apiPool": runtime_path(args.api_pool_snapshot, "pool-snapshot.json"),
    }

    activity = read_json(paths["activity"])
    rounds = read_json(paths["rounds"])
    payments = read_json(paths["payments"])
    accepted = read_json(paths["accepted"])
    watchdog = read_json(paths["watchdog"])
    launch_env = env_file_values(paths["launchEnv"])

    last_share_at = latest_share_from_activity(activity) or latest_share_from_tail(paths["shareLog"])
    last_confirmed_block_at = confirmed_block_timestamp(accepted, rounds)
    last_successful_payout_at = successful_payout_timestamp(payments)

    api_snapshots = {
        "poolSnapshot": file_status(paths["apiPool"]),
        "activitySnapshot": file_status(paths["activity"]),
        "roundsSnapshot": file_status(paths["rounds"]),
        "paymentsSnapshot": file_status(paths["payments"]),
        "acceptedCandidates": file_status(paths["accepted"]),
    }
    api_available = all(item["exists"] and item["readable"] for item in api_snapshots.values())

    real_submit_enabled = None
    if isinstance(activity, dict) and isinstance(activity.get("meta"), dict):
        real_submit_enabled = activity["meta"].get("realSubmitblockEnabled")
    if real_submit_enabled is None:
        real_submit_enabled = config_value("PEPEPOW_ENABLE_REAL_SUBMITBLOCK", launch_env, "false")

    watchdog_status = watchdog.get("status") if isinstance(watchdog, dict) else None
    watchdog_generated_at = (
        first_present(watchdog, "generatedAt", "updated_at", "generated_at")
        if isinstance(watchdog, dict)
        else None
    )

    return {
        "generatedAt": iso_now(),
        "runtimeDir": str(runtime_dir),
        "roundsSnapshot": {
            "path": str(paths["rounds"]),
            "available": isinstance(rounds, dict),
            "ageSeconds": snapshot_age(rounds, paths["rounds"], now),
        },
        "paymentsSnapshot": {
            "path": str(paths["payments"]),
            "available": isinstance(payments, dict),
            "ageSeconds": snapshot_age(payments, paths["payments"], now),
        },
        "lastAcceptedShare": {
            "at": last_share_at,
            "ageSeconds": age_seconds(last_share_at, now),
        },
        "lastConfirmedPoolBlock": {
            "at": last_confirmed_block_at,
            "ageSeconds": age_seconds(last_confirmed_block_at, now),
        },
        "lastSuccessfulPayout": {
            "at": last_successful_payout_at,
            "ageSeconds": age_seconds(last_successful_payout_at, now),
        },
        "config": {
            "payoutEnabled": config_value("PEPEPOW_ENABLE_REAL_WALLET_PAYOUT", launch_env, "false"),
            "realSubmitEnabled": real_submit_enabled,
            "minPayout": config_value("PEPEPOW_MIN_PAYOUT", launch_env, "100000.0"),
            "poolFeePercent": config_value("PEPEPOW_POOL_FEE_PERCENT", launch_env, "1.0"),
        },
        "walletWatchdog": {
            "path": str(paths["watchdog"]),
            "available": isinstance(watchdog, dict),
            "status": watchdog_status,
            "generatedAt": watchdog_generated_at,
            "ageSeconds": age_seconds(watchdog_generated_at, now),
        },
        "apiSnapshots": {
            "available": api_available,
            "items": api_snapshots,
        },
    }


def format_age(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def print_human(summary: dict[str, Any]) -> None:
    print(f"generated_at: {summary.get('generatedAt')}")
    print(f"runtime_dir: {summary.get('runtimeDir')}")
    print(f"rounds_snapshot_age: {format_age(summary['roundsSnapshot'].get('ageSeconds'))}")
    print(f"payments_snapshot_age: {format_age(summary['paymentsSnapshot'].get('ageSeconds'))}")
    print(f"last_accepted_share_at: {summary['lastAcceptedShare'].get('at')}")
    print(f"last_accepted_share_age: {format_age(summary['lastAcceptedShare'].get('ageSeconds'))}")
    print(f"last_confirmed_pool_block_at: {summary['lastConfirmedPoolBlock'].get('at')}")
    print(f"last_confirmed_pool_block_age: {format_age(summary['lastConfirmedPoolBlock'].get('ageSeconds'))}")
    print(f"last_successful_payout_at: {summary['lastSuccessfulPayout'].get('at')}")
    print(f"last_successful_payout_age: {format_age(summary['lastSuccessfulPayout'].get('ageSeconds'))}")
    print(f"payout_enabled: {summary['config'].get('payoutEnabled')}")
    print(f"real_submit_enabled: {summary['config'].get('realSubmitEnabled')}")
    print(f"min_payout: {summary['config'].get('minPayout')}")
    print(f"pool_fee_percent: {summary['config'].get('poolFeePercent')}")
    print(f"watchdog_available: {summary['walletWatchdog'].get('available')}")
    print(f"watchdog_status: {summary['walletWatchdog'].get('status')}")
    print(f"watchdog_age: {format_age(summary['walletWatchdog'].get('ageSeconds'))}")
    print(f"api_snapshots_available: {summary['apiSnapshots'].get('available')}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only PEPEPOW pool health summary")
    parser.add_argument("--runtime-dir", default=str(RUNTIME_DIR))
    parser.add_argument("--activity-snapshot", default=None)
    parser.add_argument("--rounds-snapshot", default=None)
    parser.add_argument("--payments-snapshot", default=None)
    parser.add_argument("--accepted-candidates", default=None)
    parser.add_argument("--share-log", default=None)
    parser.add_argument("--watchdog-snapshot", default=None)
    parser.add_argument("--launch-env", default=None)
    parser.add_argument("--api-pool-snapshot", default=None)
    parser.add_argument("--format", choices=("human", "json", "both"), default="human")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = build_summary(args)
    if args.format in {"human", "both"}:
        print_human(summary)
    if args.format in {"json", "both"}:
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

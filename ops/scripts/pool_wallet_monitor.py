#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
POOL_WALLET = os.environ.get(
    "PEPEPOW_POOL_MONITOR_WALLET",
    "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho",
)
EXPLORER_BASE = os.environ.get("PEPEPOW_POOL_MONITOR_EXPLORER", "https://explorer.pepepow.net").rstrip("/")
RUNTIME_DIR = Path(
    os.environ.get("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", str(REPO_ROOT / ".runtime/live-stratum"))
)
STATE_PATH = Path(os.environ.get("PEPEPOW_POOL_WALLET_MONITOR_STATE", str(RUNTIME_DIR / "pool-wallet-monitor-state.json")))
SNAPSHOT_PATH = Path(os.environ.get("PEPEPOW_POOL_WALLET_MONITOR_OUTPUT", str(RUNTIME_DIR / "pool-wallet-monitor.json")))
PUBLIC_SNAPSHOT_PATH = Path(
    os.environ.get(
        "PEPEPOW_POOL_WALLET_MONITOR_PUBLIC_OUTPUT",
        str(REPO_ROOT / "apps/frontend/site/pool-wallet-monitor.json"),
    )
)
WARNING_MINUTES = float(os.environ.get("PEPEPOW_MONITOR_NO_GROWTH_WARNING_MINUTES", "180"))
TIMEOUT_SECONDS = float(os.environ.get("PEPEPOW_MONITOR_HTTP_TIMEOUT_SECONDS", "8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.replace(",", "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def first_number(data: Any, keys: tuple[str, ...]) -> float | None:
    if not isinstance(data, dict):
        return None
    lowered = {str(k).lower().replace(" ", "").replace("_", ""): v for k, v in data.items()}
    for key in keys:
        direct = as_number(data.get(key))
        if direct is not None:
            return direct
        compact = key.lower().replace(" ", "").replace("_", "")
        compact_value = as_number(lowered.get(compact))
        if compact_value is not None:
            return compact_value
    return None


def fetch_json_or_text(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "pepepow-pool-wallet-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()


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


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_address_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        return payload
    return {}


def minutes_since(iso_value: str | None) -> float | None:
    if not iso_value:
        return None
    try:
        dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)


def load_optional_notes(delta_balance: float | None) -> list[str]:
    notes: list[str] = []
    payments = read_json(RUNTIME_DIR / "payments-snapshot.json")
    items = payments.get("items") if isinstance(payments, dict) else None
    if isinstance(items, list) and items:
        notes.append("Recent recorded payments exist; balance drops can be normal.")
    if delta_balance is not None and delta_balance < 0 and not notes:
        notes.append("Balance decreased; this can be normal after payouts or wallet movement.")
    notes.append("Pool wallet may include node/staking income; this is a rough public health signal.")
    return notes


def build_snapshot() -> dict[str, Any]:
    now = utc_now()
    address_url = f"{EXPLORER_BASE}/ext/getaddress/{POOL_WALLET}"
    balance_url = f"{EXPLORER_BASE}/ext/getbalance/{POOL_WALLET}"
    height_url = f"{EXPLORER_BASE}/api/getblockcount"
    explorer_wallet_url = f"{EXPLORER_BASE}/address/{POOL_WALLET}"

    previous = read_json(STATE_PATH)
    warnings: list[str] = []
    errors: list[str] = []

    try:
        address_payload = parse_address_payload(fetch_json_or_text(address_url))
        balance_payload = fetch_json_or_text(balance_url)
        height_payload = fetch_json_or_text(height_url)
    except Exception as exc:
        snapshot = {
            "generatedAt": now,
            "status": "critical",
            "headline": "Explorer unavailable",
            "summary": "Pool wallet monitor could not read explorer data.",
            "wallet": POOL_WALLET,
            "explorerWalletUrl": explorer_wallet_url,
            "explorerOk": False,
            "errors": [str(exc)],
            "warnings": ["Explorer API fetch failed."],
        }
        atomic_write_json(SNAPSHOT_PATH, snapshot)
        atomic_write_json(PUBLIC_SNAPSHOT_PATH, snapshot)
        return snapshot

    balance = first_number(address_payload, ("balance", "currentBalance"))
    if balance is None:
        balance = as_number(balance_payload)
    total_received = first_number(
        address_payload,
        ("totalReceived", "total_received", "totalreceived", "received", "total received"),
    )
    total_sent = first_number(
        address_payload,
        ("totalSent", "total_sent", "totalsent", "sent", "total sent"),
    )
    height = as_number(height_payload)

    previous_received = as_number(previous.get("totalReceived"))
    previous_balance = as_number(previous.get("balance"))
    previous_height = as_number(previous.get("currentBlockHeight"))
    delta_received = None if previous_received is None or total_received is None else total_received - previous_received
    delta_balance = None if previous_balance is None or balance is None else balance - previous_balance
    delta_blocks = None if previous_height is None or height is None else height - previous_height
    is_first_sample = previous_received is None and total_received is not None

    last_growth_at = previous.get("lastGrowthAt") if isinstance(previous.get("lastGrowthAt"), str) else None
    if delta_received is not None and delta_received > 0:
        last_growth_at = now
    elif last_growth_at is None and total_received is not None:
        last_growth_at = now

    no_growth_minutes = minutes_since(last_growth_at)
    status = "ok"
    headline = "Baseline recorded" if is_first_sample else "Wallet growth OK"
    if total_received is None:
        status = "warning"
        headline = "Explorer format changed"
        warnings.append("Explorer address data did not include total received.")
    elif not is_first_sample and no_growth_minutes is not None and no_growth_minutes >= WARNING_MINUTES:
        status = "warning"
        headline = "No recent wallet growth"
        warnings.append(f"Total received has not grown for about {no_growth_minutes:.0f} minutes.")

    if height is None:
        warnings.append("Explorer block height unavailable.")
    if balance is None:
        warnings.append("Explorer balance unavailable.")

    if is_first_sample:
        summary = "First monitor sample recorded. The next run will show wallet growth delta."
    elif delta_received is not None and delta_received > 0:
        summary = f"Pool wallet total received increased by {delta_received:,.3f} PEPEW since the previous monitor run."
    elif total_received is not None:
        summary = "Pool wallet total received is stable in this monitor window."
    else:
        summary = "Pool wallet total received could not be parsed from explorer data."

    snapshot = {
        "generatedAt": now,
        "status": status,
        "headline": headline,
        "summary": summary,
        "wallet": POOL_WALLET,
        "explorerWalletUrl": explorer_wallet_url,
        "explorerOk": True,
        "currentBlockHeight": height,
        "previousBlockHeight": previous_height,
        "deltaBlocks": delta_blocks,
        "balance": balance,
        "totalReceived": total_received,
        "totalSent": total_sent,
        "previousBalance": previous_balance,
        "previousTotalReceived": previous_received,
        "deltaBalance": delta_balance,
        "deltaTotalReceived": delta_received,
        "lastGrowthAt": last_growth_at,
        "minutesSinceGrowth": no_growth_minutes,
        "warnings": warnings,
        "errors": errors,
        "notes": load_optional_notes(delta_balance),
    }

    state = {
        "generatedAt": now,
        "wallet": POOL_WALLET,
        "currentBlockHeight": height,
        "balance": balance,
        "totalReceived": total_received,
        "totalSent": total_sent,
        "lastGrowthAt": last_growth_at,
    }
    atomic_write_json(STATE_PATH, state)
    atomic_write_json(SNAPSHOT_PATH, snapshot)
    atomic_write_json(PUBLIC_SNAPSHOT_PATH, snapshot)
    return snapshot


def main() -> int:
    snapshot = build_snapshot()
    print(f"status: {snapshot.get('status')}")
    print(f"headline: {snapshot.get('headline')}")
    print(f"wallet: {snapshot.get('wallet')}")
    print(f"totalReceived: {snapshot.get('totalReceived')}")
    print(f"deltaTotalReceived: {snapshot.get('deltaTotalReceived')}")
    print(f"balance: {snapshot.get('balance')}")
    print(f"currentBlockHeight: {snapshot.get('currentBlockHeight')}")
    print(f"snapshot: {SNAPSHOT_PATH}")
    print(f"publicSnapshot: {PUBLIC_SNAPSHOT_PATH}")
    return 0 if snapshot.get("status") in {"ok", "warning"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

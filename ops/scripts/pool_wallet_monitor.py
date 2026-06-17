#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import payout_helper

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
HISTORY_RETENTION_HOURS = float(os.environ.get("PEPEPOW_POOL_WALLET_MONITOR_HISTORY_HOURS", "72"))
PRIMARY_WINDOW_HOURS = float(os.environ.get("PEPEPOW_POOL_WALLET_MONITOR_PRIMARY_WINDOW_HOURS", "24"))
SECONDARY_WINDOW_HOURS = float(os.environ.get("PEPEPOW_POOL_WALLET_MONITOR_SECONDARY_WINDOW_HOURS", "48"))
WATCHDOG_STATE_PATH = Path(
    os.environ.get(
        "PEPEPOW_POOL_WALLET_WATCHDOG_STATE",
        str(RUNTIME_DIR / "pool-wallet-watchdog-state.json"),
    )
)
WATCHDOG_OUTPUT_PATH = Path(
    os.environ.get(
        "PEPEPOW_POOL_WALLET_WATCHDOG_OUTPUT",
        str(RUNTIME_DIR / "pool-wallet-watchdog.json"),
    )
)
WATCHDOG_TOLERANCE = float(os.environ.get("PEPEPOW_POOL_WALLET_WATCHDOG_TOLERANCE", "0.01"))
DEFAULT_BLOCK_REWARD = 7000.0
DEFAULT_DEVELOPER_FACTOR = 0.95
DEFAULT_MINER_FACTOR = 0.65


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(iso_value: str | None) -> datetime | None:
    if not iso_value:
        return None
    try:
        return datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def atomic_write_json(path: Path, data: dict[str, Any], mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(temp_name, path)
        if mode is not None:
            os.chmod(path, mode)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def write_snapshots(snapshot: dict[str, Any]) -> None:
    atomic_write_json(SNAPSHOT_PATH, snapshot)
    atomic_write_json(PUBLIC_SNAPSHOT_PATH, snapshot, 0o644)


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
    dt = parse_time(iso_value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)


def normalize_history(previous: dict[str, Any], now_dt: datetime) -> list[dict[str, Any]]:
    cutoff = now_dt.timestamp() - HISTORY_RETENTION_HOURS * 3600
    rows: list[dict[str, Any]] = []
    raw_rows = previous.get("history")
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            generated_at = row.get("generatedAt") if isinstance(row.get("generatedAt"), str) else None
            total_received = as_number(row.get("totalReceived"))
            balance = as_number(row.get("balance"))
            height = as_number(row.get("currentBlockHeight"))
            dt = parse_time(generated_at)
            if dt is None or total_received is None or dt.timestamp() < cutoff:
                continue
            rows.append({
                "generatedAt": generated_at,
                "totalReceived": total_received,
                "balance": balance,
                "currentBlockHeight": height,
            })
    elif as_number(previous.get("totalReceived")) is not None and isinstance(previous.get("generatedAt"), str):
        rows.append({
            "generatedAt": previous.get("generatedAt"),
            "totalReceived": as_number(previous.get("totalReceived")),
            "balance": as_number(previous.get("balance")),
            "currentBlockHeight": as_number(previous.get("currentBlockHeight")),
        })
    rows.sort(key=lambda item: item["generatedAt"])
    return rows[-512:]


def append_history(previous: dict[str, Any], sample: dict[str, Any], now_dt: datetime) -> list[dict[str, Any]]:
    history = normalize_history(previous, now_dt)
    if as_number(sample.get("totalReceived")) is None:
        return history
    if history and history[-1].get("generatedAt") == sample.get("generatedAt"):
        history[-1] = sample
    else:
        history.append(sample)
    cutoff = now_dt.timestamp() - HISTORY_RETENTION_HOURS * 3600
    filtered = []
    for row in history:
        dt = parse_time(row.get("generatedAt") if isinstance(row.get("generatedAt"), str) else None)
        if dt is not None and dt.timestamp() >= cutoff:
            filtered.append(row)
    return filtered[-512:]


def window_delta(history: list[dict[str, Any]], total_received: float | None, now_dt: datetime, hours: float) -> dict[str, Any]:
    result = {
        "hours": hours,
        "deltaTotalReceived": None,
        "sampleStartAt": None,
        "sampleEndAt": now_dt.isoformat().replace("+00:00", "Z"),
        "sampleHours": 0.0,
    }
    if total_received is None or not history:
        return result
    cutoff = now_dt.timestamp() - hours * 3600
    candidates = []
    for row in history:
        dt = parse_time(row.get("generatedAt") if isinstance(row.get("generatedAt"), str) else None)
        received = as_number(row.get("totalReceived"))
        if dt is None or received is None:
            continue
        if dt.timestamp() <= cutoff:
            candidates.append((dt, row))
    if candidates:
        start_dt, start_row = candidates[-1]
    else:
        start_dt = parse_time(history[0].get("generatedAt") if isinstance(history[0].get("generatedAt"), str) else None)
        start_row = history[0]
    start_received = as_number(start_row.get("totalReceived"))
    if start_dt is None or start_received is None:
        return result
    result["deltaTotalReceived"] = total_received - start_received
    result["sampleStartAt"] = start_dt.isoformat().replace("+00:00", "Z")
    result["sampleHours"] = max(0.0, (now_dt - start_dt).total_seconds() / 3600.0)
    return result


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
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat().replace("+00:00", "Z")
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
        write_snapshots(snapshot)
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

    sample = {
        "generatedAt": now,
        "totalReceived": total_received,
        "balance": balance,
        "currentBlockHeight": height,
    }
    history = append_history(previous, sample, now_dt)
    primary_window = window_delta(history, total_received, now_dt, PRIMARY_WINDOW_HOURS)
    secondary_window = window_delta(history, total_received, now_dt, SECONDARY_WINDOW_HOURS)

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

    primary_delta = as_number(primary_window.get("deltaTotalReceived"))
    primary_hours = as_number(primary_window.get("sampleHours")) or 0.0
    if is_first_sample:
        summary = "First monitor sample recorded. The next run will show wallet growth delta."
    elif primary_delta is not None and primary_hours >= 1.0:
        label = f"{int(PRIMARY_WINDOW_HOURS)}h" if PRIMARY_WINDOW_HOURS.is_integer() else f"{PRIMARY_WINDOW_HOURS:g}h"
        summary = f"Pool wallet total received increased by {primary_delta:,.3f} PEPEW over the latest available {label} window."
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
        "primaryWindowHours": PRIMARY_WINDOW_HOURS,
        "primaryWindowDeltaTotalReceived": primary_window.get("deltaTotalReceived"),
        "primaryWindowSampleHours": primary_window.get("sampleHours"),
        "secondaryWindowHours": SECONDARY_WINDOW_HOURS,
        "secondaryWindowDeltaTotalReceived": secondary_window.get("deltaTotalReceived"),
        "secondaryWindowSampleHours": secondary_window.get("sampleHours"),
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
        "history": history,
    }
    atomic_write_json(STATE_PATH, state)
    write_snapshots(snapshot)
    return snapshot


def confirmed_candidate_id(candidate: dict[str, Any]) -> str | None:
    value = (
        candidate.get("candidate_hash")
        or candidate.get("candidateId")
        or candidate.get("blockHash")
        or candidate.get("block_hash")
    )
    return str(value) if value else None


def is_confirmed_pool_candidate(candidate: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        return False
    status = str(candidate.get("lifecycle_status") or candidate.get("lifecycleStatus") or "").lower()
    followup_status = str(candidate.get("followup_status") or candidate.get("followupStatus") or "").lower()
    if status != "confirmed" or followup_status == "no-match-found":
        return False
    return candidate.get("coinbaseMatchesExpectedPoolWallet") is not False and candidate.get("coinbase_matches_expected_pool_wallet") is not False


def candidate_miner_reward(candidate: dict[str, Any], default_reward: float) -> float:
    for key in ("minerRewardAmount", "miner_reward_amount", "miner_gross_reward", "minerGrossReward"):
        value = as_number(candidate.get(key))
        if value is not None and value > 0:
            return value
    return default_reward


def payment_id(item: dict[str, Any]) -> str | None:
    txid = item.get("txid")
    wallet = item.get("wallet")
    amount = item.get("amount")
    candidate_id = item.get("candidate_id") or item.get("candidateHash") or item.get("candidateId")
    if txid and wallet:
        return f"tx:{txid}:{wallet}:{amount}"
    if txid:
        return f"tx:{txid}:{wallet or ''}:{candidate_id or ''}:{amount}"
    return None


def load_successful_payments(actions_path: Path, snapshot_path: Path) -> dict[str, dict[str, Any]]:
    payments: dict[str, dict[str, Any]] = {}
    if actions_path.exists():
        try:
            with actions_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        action = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(action, dict) or not payout_helper.action_represents_successful_payment(action):
                        continue
                    pid = payment_id(action)
                    amount = as_number(action.get("amount"))
                    if pid and amount is not None and amount > 0:
                        payments[pid] = {"id": pid, "amount": amount, "txid": action.get("txid"), "wallet": action.get("wallet")}
        except Exception:
            pass
    snapshot = read_json(snapshot_path)
    items = snapshot.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or not item.get("txid"):
                continue
            pid = payment_id(item)
            amount = as_number(item.get("amount"))
            if pid and amount is not None and amount > 0:
                payments[pid] = {"id": pid, "amount": amount, "txid": item.get("txid"), "wallet": item.get("wallet")}
    return payments


def load_confirmed_candidates(path: Path) -> dict[str, dict[str, Any]]:
    data = read_json(path)
    raw_items = data.get("accepted_candidates")
    candidates: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_items, list):
        return candidates
    for candidate in raw_items:
        if not is_confirmed_pool_candidate(candidate):
            continue
        cid = confirmed_candidate_id(candidate)
        if cid:
            candidates[cid] = candidate
    return candidates


def wallet_balance_from_explorer(wallet: str, explorer_base: str) -> float:
    address_payload = parse_address_payload(fetch_json_or_text(f"{explorer_base}/ext/getaddress/{wallet}"))
    balance = first_number(address_payload, ("balance", "currentBalance"))
    if balance is not None:
        return balance
    fallback = as_number(fetch_json_or_text(f"{explorer_base}/ext/getbalance/{wallet}"))
    if fallback is None:
        raise RuntimeError("explorer balance unavailable")
    return fallback


def build_watchdog_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    env = payout_helper.load_env_vars()
    block_reward = float(args.block_reward)
    developer_factor = float(args.developer_factor)
    miner_factor = float(args.miner_factor)
    miner_reward_default = block_reward * developer_factor * miner_factor
    parsed_pool_fee_percent = as_number(env.get("PEPEPOW_POOL_FEE_PERCENT"))
    parsed_min_payout = as_number(env.get("PEPEPOW_MIN_PAYOUT"))
    pool_fee_percent = 1.0 if parsed_pool_fee_percent is None else parsed_pool_fee_percent
    min_payout = 100000.0 if parsed_min_payout is None else parsed_min_payout

    state_path = Path(args.state)
    output_path = Path(args.output)
    accepted_path = Path(args.accepted_candidates)
    actions_path = Path(args.payment_actions)
    payments_path = Path(args.payments_snapshot)
    previous = read_json(state_path)

    try:
        current_balance = float(args.balance) if args.balance is not None else wallet_balance_from_explorer(args.wallet, args.explorer.rstrip("/"))
    except Exception as exc:
        snapshot = {
            "generatedAt": now,
            "status": "critical",
            "summary": "Pool wallet watchdog could not read wallet balance.",
            "wallet": args.wallet,
            "errors": [str(exc)],
        }
        atomic_write_json(output_path, snapshot)
        return snapshot

    candidates = load_confirmed_candidates(accepted_path)
    payments = load_successful_payments(actions_path, payments_path)
    seen_candidate_ids = {str(x) for x in previous.get("seenCandidateIds", []) if x}
    seen_payment_ids = {str(x) for x in previous.get("seenPaymentIds", []) if x}

    first_sample = as_number(previous.get("balance")) is None
    new_candidate_ids = sorted(set(candidates) - seen_candidate_ids)
    new_payment_ids = sorted(set(payments) - seen_payment_ids)

    confirmed_blocks = []
    miner_gross_total = 0.0
    for cid in new_candidate_ids:
        candidate = candidates[cid]
        miner_gross = candidate_miner_reward(candidate, miner_reward_default)
        pool_retained = miner_gross * pool_fee_percent / 100.0
        miner_net = miner_gross - pool_retained
        miner_gross_total += miner_gross
        confirmed_blocks.append({
            "candidateId": cid,
            "height": candidate.get("matched_height") or candidate.get("height"),
            "minerGrossReward": miner_gross,
            "minerNetReward": miner_net,
            "poolRetainedReward": pool_retained,
        })

    outgoing_total = sum(payments[pid]["amount"] for pid in new_payment_ids)
    expected_delta = miner_gross_total - outgoing_total
    previous_balance = as_number(previous.get("balance"))
    actual_delta = None if previous_balance is None else current_balance - previous_balance
    unexpected_increase = None if actual_delta is None else actual_delta - expected_delta

    status = "baseline" if first_sample else "ok"
    if unexpected_increase is not None and unexpected_increase > WATCHDOG_TOLERANCE:
        status = "warning"
    if first_sample:
        summary = "Baseline recorded; next run will compare wallet balance deltas."
    elif status == "warning":
        summary = f"Unexpected wallet balance increase detected: {unexpected_increase:.8f} PEPEW over expected delta."
    else:
        summary = "Wallet balance delta is within expected confirmed-block and payment accounting."

    snapshot = {
        "generatedAt": now,
        "status": status,
        "summary": summary,
        "wallet": args.wallet,
        "explorerInfoUrl": f"{args.explorer.rstrip('/')}/info",
        "outputPath": str(output_path),
        "balance": current_balance,
        "previousBalance": previous_balance,
        "actualDelta": actual_delta,
        "expectedDelta": None if first_sample else expected_delta,
        "unexpectedIncrease": None if first_sample else unexpected_increase,
        "tolerance": WATCHDOG_TOLERANCE,
        "params": {
            "blockReward": block_reward,
            "developerFactor": developer_factor,
            "minerFactor": miner_factor,
            "poolFeePercent": pool_fee_percent,
            "minPayout": min_payout,
            "defaultMinerGrossReward": miner_reward_default,
        },
        "accounting": {
            "newConfirmedBlockCount": 0 if first_sample else len(new_candidate_ids),
            "newConfirmedMinerGrossTotal": 0.0 if first_sample else miner_gross_total,
            "newPoolRetainedTotal": 0.0 if first_sample else sum(row["poolRetainedReward"] for row in confirmed_blocks),
            "newMinerNetTotal": 0.0 if first_sample else sum(row["minerNetReward"] for row in confirmed_blocks),
            "newOutgoingPaymentCount": 0 if first_sample else len(new_payment_ids),
            "newOutgoingPaymentTotal": 0.0 if first_sample else outgoing_total,
        },
        "confirmedBlocks": [] if first_sample else confirmed_blocks[:50],
        "errors": [],
    }
    state = {
        "generatedAt": now,
        "wallet": args.wallet,
        "balance": current_balance,
        "seenCandidateIds": sorted(set(candidates)),
        "seenPaymentIds": sorted(set(payments)),
    }
    atomic_write_json(state_path, state)
    atomic_write_json(output_path, snapshot)
    return snapshot


def print_growth_summary(snapshot: dict[str, Any]) -> None:
    print(f"status: {snapshot.get('status')}")
    print(f"headline: {snapshot.get('headline')}")
    print(f"wallet: {snapshot.get('wallet')}")
    print(f"primaryWindowHours: {snapshot.get('primaryWindowHours')}")
    print(f"primaryWindowDeltaTotalReceived: {snapshot.get('primaryWindowDeltaTotalReceived')}")
    print(f"deltaTotalReceived: {snapshot.get('deltaTotalReceived')}")
    print(f"balance: {snapshot.get('balance')}")
    print(f"currentBlockHeight: {snapshot.get('currentBlockHeight')}")
    print(f"snapshot: {SNAPSHOT_PATH}")
    print(f"publicSnapshot: {PUBLIC_SNAPSHOT_PATH}")


def print_watchdog(snapshot: dict[str, Any], output_format: str) -> None:
    if output_format in {"human", "both"}:
        print(f"status: {snapshot.get('status')}")
        print(f"summary: {snapshot.get('summary')}")
        print(f"balance: {snapshot.get('balance')}")
        print(f"actualDelta: {snapshot.get('actualDelta')}")
        print(f"expectedDelta: {snapshot.get('expectedDelta')}")
        print(f"unexpectedIncrease: {snapshot.get('unexpectedIncrease')}")
        print(f"snapshot: {snapshot.get('outputPath') or WATCHDOG_OUTPUT_PATH}")
    if output_format in {"json", "both"}:
        print(json.dumps(snapshot, sort_keys=True, separators=(",", ":")))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PEPEPOW pool wallet monitors")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("growth", help="write the legacy public wallet growth snapshot")
    watchdog = subparsers.add_parser("watchdog", help="check wallet balance against pool accounting deltas")
    watchdog.add_argument("--wallet", default=POOL_WALLET)
    watchdog.add_argument("--explorer", default=EXPLORER_BASE)
    watchdog.add_argument("--accepted-candidates", default=str(RUNTIME_DIR / "accepted-candidates.json"))
    watchdog.add_argument("--payment-actions", default=str(RUNTIME_DIR / "payment-actions.jsonl"))
    watchdog.add_argument("--payments-snapshot", default=str(RUNTIME_DIR / "payments-snapshot.json"))
    watchdog.add_argument("--state", default=str(WATCHDOG_STATE_PATH))
    watchdog.add_argument("--output", default=str(WATCHDOG_OUTPUT_PATH))
    watchdog.add_argument("--block-reward", type=float, default=DEFAULT_BLOCK_REWARD)
    watchdog.add_argument("--developer-factor", type=float, default=DEFAULT_DEVELOPER_FACTOR)
    watchdog.add_argument("--miner-factor", type=float, default=DEFAULT_MINER_FACTOR)
    watchdog.add_argument("--balance", type=float, default=None, help="override current wallet balance for tests")
    watchdog.add_argument("--format", choices=("human", "json", "both"), default="both")
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "growth"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "growth":
        snapshot = build_snapshot()
        print_growth_summary(snapshot)
        return 0 if snapshot.get("status") in {"ok", "warning"} else 2
    snapshot = build_watchdog_snapshot(args)
    print_watchdog(snapshot, args.format)
    status = snapshot.get("status")
    if status in {"ok", "baseline"}:
        return 0
    if status == "warning":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

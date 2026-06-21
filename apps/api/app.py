from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from flask import Flask, jsonify
from waitress import serve

from config import AppConfig, load_config
from store import SnapshotRecord, SnapshotStore, SnapshotUnavailableError


LOCAL_SERVICE_BASELINE = {
    "core": True,
    "api": True,
    "stratum": True,
    "frontendExpected": False,
    "deploymentVariant": "core-api-stratum-no-local-frontend",
}

HASHRATE_HISTORY_MAX_AGE_SECONDS = 24 * 60 * 60
HASHRATE_HISTORY_MAX_POINTS = 1440
HASHRATE_HISTORY_SAMPLE_MS = 60 * 1000
OPERATOR_STATUS_ITEMS = (
    ("pool_health", "Pool Health", "Status unavailable"),
    ("wallet_watchdog", "Wallet Watchdog", "Status unavailable"),
    ("payment_audit", "Payment Audit", "Status unavailable"),
)
PUBLIC_STATUSES = {"ok", "warning", "error", "unknown"}


def parse_price_defensively(data: Any) -> float | None:
    if not data:
        return None
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]
    if not isinstance(data, dict):
        return None

    if isinstance(data.get("ticker"), dict):
        data = data["ticker"]
    elif isinstance(data.get("data"), dict):
        data = data["data"]

    for key in ("last_price", "last", "price"):
        if data.get(key) is not None:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                pass

    bid = None
    ask = None
    for key in ("bid", "buy"):
        if data.get(key) is not None:
            try:
                bid = float(data[key])
                break
            except (TypeError, ValueError):
                pass
    for key in ("ask", "sell"):
        if data.get(key) is not None:
            try:
                ask = float(data[key])
                break
            except (TypeError, ValueError):
                pass
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return None


class PriceCache:
    def __init__(self, cache_ttl_seconds: int = 120) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self.price: float | None = None
        self.updated_at: str | None = None
        self.last_fetch_success = 0.0
        self.last_fetch_attempt = 0.0
        self.lock = threading.Lock()

    def get_price_info(self) -> dict[str, Any]:
        now = time.time()
        with self.lock:
            should_fetch = (
                now - self.last_fetch_success >= self.cache_ttl_seconds
                and now - self.last_fetch_attempt >= 10.0
            )
            if should_fetch:
                self.last_fetch_attempt = now

        if should_fetch:
            try:
                req = urllib.request.Request(
                    "https://api.nonkyc.io/api/v2/ticker/PEPEW_USDT",
                    headers={"User-Agent": "pepepow-pool-api/0.1.0"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
                new_price = parse_price_defensively(data)
                if new_price is not None:
                    with self.lock:
                        self.price = new_price
                        self.updated_at = _now_iso()
                        self.last_fetch_success = now
            except Exception as exc:
                print(f"Error fetching PEPEW price from NonKYC: {exc}")

        with self.lock:
            return {
                "symbol": "PEPEW_USDT",
                "price": self.price,
                "source": "nonkyc",
                "updatedAt": self.updated_at,
                "cacheSeconds": self.cache_ttl_seconds,
            }


def create_app(config: AppConfig | None = None) -> Flask:
    app_config = config or load_config()
    app = Flask(__name__)
    app.config["APP_CONFIG"] = app_config
    app.config["SNAPSHOT_STORE"] = SnapshotStore(
        app_config.runtime_snapshot_path,
        app_config.fallback_snapshot_path,
        app_config.activity_snapshot_path,
        app_config.cache_ttl_seconds,
        app_config.stale_after_seconds,
    )
    app.config["PRICE_CACHE"] = PriceCache()
    app.config["HASHRATE_HISTORY"] = {"pool": [], "network": []}
    wallet_pattern = re.compile(app_config.allowed_wallet_pattern)

    def json_error(status: HTTPStatus, message: str):
        response = jsonify({"error": {"code": status.value, "message": message}})
        response.status_code = status.value
        return response

    def get_snapshot_record() -> SnapshotRecord:
        store: SnapshotStore = app.config["SNAPSHOT_STORE"]
        return store.get_snapshot_record()

    @app.errorhandler(SnapshotUnavailableError)
    def handle_snapshot_error(exc: SnapshotUnavailableError):
        return json_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return json_error(HTTPStatus.NOT_FOUND, "Route not found")

    @app.errorhandler(500)
    def handle_internal_error(_exc):
        return json_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

    @app.get("/api/health")
    def health():
        record = get_snapshot_record()
        return jsonify(
            {
                "service": app_config.app_name,
                "localServiceBaseline": LOCAL_SERVICE_BASELINE,
                "status": "ok" if not record.degraded else "degraded",
                "version": app_config.version,
                "mode": "snapshot",
                "generatedAt": record.generated_at,
                "snapshotAgeSeconds": record.age_seconds,
                "snapshotSource": record.source,
                "degraded": record.degraded,
                "stale": record.stale,
                "daemonReachable": bool(record.meta.get("daemonReachable", False)),
                "blockFeedKind": record.meta.get("blockFeedKind", "unknown"),
                "chainState": record.meta.get("chainState", "unknown"),
                "chainVerificationProgress": record.meta.get("chainVerificationProgress"),
                "activityMode": record.meta.get("activityMode"),
                "activityDataSource": record.meta.get("activityDataSource"),
                "activityDataStatus": record.meta.get("activityDataStatus"),
                "activityWindowSeconds": record.meta.get("activityWindowSeconds"),
                "activityLastShareAt": record.meta.get("activityLastShareAt"),
                "activityWarningCount": record.meta.get("activityWarningCount"),
                "activityDerivedFromShares": record.meta.get("activityDerivedFromShares"),
                "blockchainVerified": record.meta.get("blockchainVerified"),
                "templateModeConfigured": record.meta.get("templateModeConfigured"),
                "templateModeEffective": record.meta.get("templateModeEffective"),
                "templateDaemonRpcStatus": record.meta.get("templateDaemonRpcStatus"),
                "templateDaemonRpcReachable": record.meta.get("templateDaemonRpcReachable"),
                "templateFetchStatus": record.meta.get("templateFetchStatus"),
                "templateLastAttemptAt": record.meta.get("templateLastAttemptAt"),
                "templateLastSuccessAt": record.meta.get("templateLastSuccessAt"),
                "templateLatestTemplateAgeSeconds": record.meta.get("templateLatestTemplateAgeSeconds"),
                "templateLatestTemplateAnchor": record.meta.get("templateLatestTemplateAnchor"),
                "templateLastError": record.meta.get("templateLastError"),
                "activeJobCount": record.meta.get("activeJobCount"),
                "assumedShareDifficulty": record.meta.get("assumedShareDifficulty"),
                "hashratePolicy": record.meta.get("hashratePolicy"),
                "submitValidationMode": record.meta.get("submitValidationMode"),
                "submitHashValidCount": record.meta.get("submitHashValidCount"),
                "submitHashInvalidCount": record.meta.get("submitHashInvalidCount"),
                "submitDuplicateWindowSize": record.meta.get("submitDuplicateWindowSize"),
                "submitCandidatePossibleCount": record.meta.get("submitCandidatePossibleCount"),
                "shareHashValidationMode": record.meta.get("shareHashValidationMode"),
                "realSubmitblockEnabled": record.meta.get("realSubmitblockEnabled"),
                "realSubmitblockSendBudget": record.meta.get("realSubmitblockSendBudget"),
                "realSubmitblockSendBudgetRemaining": record.meta.get("realSubmitblockSendBudgetRemaining"),
                "realSubmitblockAttemptCount": record.meta.get("realSubmitblockAttemptCount"),
                "realSubmitblockSentCount": record.meta.get("realSubmitblockSentCount"),
                "realSubmitblockErrorCount": record.meta.get("realSubmitblockErrorCount"),
                "realSubmitblockLastStatus": record.meta.get("realSubmitblockLastStatus"),
                "realSubmitblockLastAttemptAt": record.meta.get("realSubmitblockLastAttemptAt"),
                "realSubmitblockLastError": record.meta.get("realSubmitblockLastError"),
                "submitClassificationCounts": record.meta.get("submitClassificationCounts"),
                "submitRejectReasonCounts": record.meta.get("submitRejectReasonCounts"),
                "submitTargetValidationCounts": record.meta.get("submitTargetValidationCounts"),
                "submitShareHashValidationCounts": record.meta.get("submitShareHashValidationCounts"),
                "runtimeSnapshotPath": str(app_config.runtime_snapshot_path),
                "fallbackSnapshotPath": str(app_config.fallback_snapshot_path),
                "activitySnapshotPath": str(app_config.activity_snapshot_path),
                "lastError": record.last_error,
            }
        )

    @app.get("/api/pool/summary")
    def pool_summary():
        record = get_snapshot_record()
        payload = dict(record.data["pool"])
        payload.update(
            {
                "dataStatus": record.data_status,
                "placeholderFields": _placeholder_fields(record.data),
                "snapshotSource": record.source,
                "generatedAt": record.generated_at,
                "activityMode": record.meta.get("activityMode"),
                "activityDataStatus": record.meta.get("activityDataStatus"),
                "activityWindowSeconds": record.meta.get("activityWindowSeconds"),
                "activityDerivedFromShares": record.meta.get("activityDerivedFromShares"),
                "blockchainVerified": record.meta.get("blockchainVerified"),
                "templateModeEffective": record.meta.get("templateModeEffective"),
                "activeJobCount": record.meta.get("activeJobCount"),
                "assumedShareDifficulty": record.meta.get("assumedShareDifficulty"),
                "hashratePolicy": record.meta.get("hashratePolicy"),
            }
        )
        return jsonify(payload)

    @app.get("/api/network/summary")
    def network_summary():
        record = get_snapshot_record()
        payload = dict(record.data["network"])
        payload.update(
            {
                "dataStatus": record.data_status,
                "placeholderFields": _placeholder_fields(record.data),
                "snapshotSource": record.source,
                "generatedAt": record.generated_at,
                "chainState": record.meta.get("chainState"),
                "chainVerificationProgress": record.meta.get("chainVerificationProgress"),
                "blockFeedKind": record.meta.get("blockFeedKind"),
            }
        )
        return jsonify(payload)

    @app.get("/api/hashrate/history")
    def hashrate_history():
        record = get_snapshot_record()
        history = app.config["HASHRATE_HISTORY"]
        _append_hashrate_history_sample(history, record)
        return jsonify(
            {
                "generatedAt": _now_iso(),
                "maxAgeSeconds": HASHRATE_HISTORY_MAX_AGE_SECONDS,
                "maxPoints": HASHRATE_HISTORY_MAX_POINTS,
                "pool": history["pool"],
                "network": history["network"],
            }
        )

    @app.get("/api/blocks")
    def blocks():
        record = get_snapshot_record()
        return jsonify(
            {
                "items": record.data["blocks"],
                "kind": record.meta.get("blockFeedKind", "unknown"),
                "dataStatus": record.data_status,
                "generatedAt": record.generated_at,
                "chainState": record.meta.get("chainState"),
            }
        )

    @app.get("/api/accepted-candidates")
    def accepted_candidates():
        items = []
        for c in _load_json_items(
            app_config.activity_snapshot_path.parent / "accepted-candidates.json",
            app_config.runtime_snapshot_path.parent / "accepted-candidates.json",
            "accepted_candidates",
        ):
            items.append(
                {
                    "candidateHash": c.get("candidate_hash"),
                    "jobId": c.get("job_id"),
                    "submitTimestamp": c.get("submit_timestamp"),
                    "submitblockDaemonResult": c.get("daemon_result"),
                    "followupStatus": c.get("followup_status"),
                    "matchedHeight": c.get("matched_height"),
                    "matchedBlockHash": c.get("matched_block_hash"),
                    "lifecycleStatus": c.get("lifecycle_status"),
                    "confirmations": c.get("confirmations"),
                    "maturityLabel": c.get("maturity_label"),
                }
            )
        return jsonify({"items": items})

    @app.get("/api/rounds")
    def rounds():
        rounds_list = _load_json_items(
            app_config.activity_snapshot_path.parent / "rounds-snapshot.json",
            app_config.runtime_snapshot_path.parent / "rounds-snapshot.json",
            "rounds",
        )
        items = []
        for r in rounds_list:
            item = {
                "roundId": r.get("round_id"),
                "candidateHash": r.get("candidate_hash"),
                "height": r.get("height"),
                "matchedHeight": r.get("height"),
                "status": r.get("status"),
                "roundStatus": r.get("status"),
                "lifecycleStatus": r.get("status"),
                "submitTimestamp": r.get("submit_timestamp"),
                "confirmations": r.get("confirmations"),
                "totalShareCount": r.get("total_share_count", 0),
                "totalShareScore": r.get("total_share_score", 0.0),
                "walletCount": r.get("wallet_count", len(r.get("shares", {}))),
                "workerCount": r.get("worker_count", 0),
                "shares": _map_round_shares(r.get("shares", {})),
            }
            if "payable" in r:
                item["payable"] = r["payable"]
            items.append(item)
        items.reverse()
        return jsonify({"items": items[:50]})

    @app.get("/api/operator-status")
    def operator_status():
        data = _load_json_dict(
            app_config.activity_snapshot_path.parent / "operator-status.json",
            app_config.runtime_snapshot_path.parent / "operator-status.json",
        )
        return jsonify(_sanitize_operator_status_payload(data))

    @app.get("/api/payments")
    def payments():
        data = _load_json_dict(
            app_config.activity_snapshot_path.parent / "payments-snapshot.json",
            app_config.runtime_snapshot_path.parent / "payments-snapshot.json",
        )
        if isinstance(data.get("items"), list):
            return jsonify(data)
        return jsonify({"items": []})

    @app.get("/api/miner/<wallet>")
    def miner(wallet: str):
        if not wallet_pattern.fullmatch(wallet):
            return json_error(HTTPStatus.BAD_REQUEST, "Wallet format is invalid")

        recent_payments, total_paid_manual = _recent_payments_for_wallet(
            wallet,
            app_config.activity_snapshot_path.parent / "payments-snapshot.json",
            app_config.runtime_snapshot_path.parent / "payments-snapshot.json",
        )
        record = get_snapshot_record()
        base = {
            "wallet": wallet,
            "payments": [],
            "recentPayments": recent_payments,
            "totalPaidManual": total_paid_manual,
            "dataStatus": record.data_status,
            "activityMode": record.meta.get("activityMode"),
            "activityDataStatus": record.meta.get("activityDataStatus"),
        }
        if not bool(record.meta.get("minerLookupImplemented", False)):
            return jsonify({**base, "found": False, "summary": None, "workers": [], "implemented": False, "status": "not-implemented"})

        miners = record.data.get("miners", {})
        miner_record = miners.get(wallet) if isinstance(miners, dict) else None
        if miner_record is None:
            return jsonify({**base, "found": False, "summary": None, "workers": [], "implemented": True, "status": "ok"})

        return jsonify(
            {
                **base,
                "found": True,
                "summary": miner_record.get("summary", {}),
                "workers": miner_record.get("workers", []),
                "payments": miner_record.get("payments", []),
                "implemented": True,
                "status": "ok",
                "activityDerivedFromShares": record.meta.get("activityDerivedFromShares"),
                "blockchainVerified": record.meta.get("blockchainVerified"),
                "hashratePolicy": record.meta.get("hashratePolicy"),
            }
        )

    @app.get("/api/stats")
    def mining_pool_stats():
        try:
            record = get_snapshot_record()
        except SnapshotUnavailableError:
            record = None
        return jsonify(
            _build_mining_pool_stats_payload(
                record,
                _load_json_items(
                    app_config.activity_snapshot_path.parent / "accepted-candidates.json",
                    app_config.runtime_snapshot_path.parent / "accepted-candidates.json",
                    "accepted_candidates",
                ),
                _load_json_items(
                    app_config.activity_snapshot_path.parent / "payments-snapshot.json",
                    app_config.runtime_snapshot_path.parent / "payments-snapshot.json",
                    "items",
                ),
            )
        )

    @app.get("/api/status")
    def mining_pool_status():
        try:
            record = get_snapshot_record()
        except SnapshotUnavailableError:
            record = None
        pool_hashrate = _pool_hashrate(record)
        active_workers = _active_worker_count(record)
        return jsonify(
            {
                "hoohashv110": {
                    "name": "hoohashv110",
                    "port": 39333,
                    "coins": 1,
                    "fees": 1,
                    "hashrate": pool_hashrate,
                    "workers": active_workers,
                    "hashrate_last24h": pool_hashrate,
                }
            }
        )

    @app.get("/api/price/pepew-usdt")
    def pepew_usdt_price():
        cache: PriceCache = app.config["PRICE_CACHE"]
        return jsonify(cache.get_price_info())

    return app


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _placeholder_fields(snapshot: dict[str, Any]) -> list[str]:
    meta = snapshot.get("meta", {})
    fields = meta.get("placeholderFields", [])
    return [field for field in fields if isinstance(field, str)] if isinstance(fields, list) else []


def _load_json_dict(primary_path, fallback_path) -> dict[str, Any]:
    path = primary_path if primary_path.exists() else fallback_path
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_items(primary_path, fallback_path, item_key: str) -> list[dict[str, Any]]:
    data = _load_json_dict(primary_path, fallback_path)
    items = data.get(item_key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:
        return default
    return parsed


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_time_ms(value: Any) -> int:
    if not isinstance(value, str) or not value:
        return int(time.time() * 1000)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return int(time.time() * 1000)


def _normalize_history_series(points: Any, now_ms: int) -> list[dict[str, Any]]:
    cutoff = now_ms - HASHRATE_HISTORY_MAX_AGE_SECONDS * 1000
    if not isinstance(points, list):
        return []
    normalized = []
    for point in points:
        if not isinstance(point, dict):
            continue
        t = _as_int(point.get("t"), -1)
        h = _as_float(point.get("h"), -1.0)
        if t >= cutoff and h >= 0:
            normalized.append({"t": t, "h": h})
    normalized.sort(key=lambda item: item["t"])
    return normalized[-HASHRATE_HISTORY_MAX_POINTS:]


def _append_history_point(points: Any, t: int, hashrate: float, now_ms: int) -> list[dict[str, Any]]:
    normalized = _normalize_history_series(points, now_ms)
    if hashrate < 0:
        return normalized
    if normalized and t - _as_int(normalized[-1].get("t")) < int(HASHRATE_HISTORY_SAMPLE_MS * 0.75):
        normalized[-1] = {"t": t, "h": hashrate}
    else:
        normalized.append({"t": t, "h": hashrate})
    return _normalize_history_series(normalized, now_ms)


def _network_hashrate(record: SnapshotRecord | None) -> float:
    if record is None:
        return 0.0
    network = record.data.get("network", {})
    if not isinstance(network, dict):
        return 0.0
    for key in ("networkHashrate", "network_hashrate", "hashrate"):
        if key in network:
            return _as_float(network.get(key))
    return 0.0


def _append_hashrate_history_sample(history: dict[str, Any], record: SnapshotRecord) -> None:
    now_ms = int(time.time() * 1000)
    sample_ms = _parse_time_ms(record.generated_at)
    history["pool"] = _append_history_point(history.get("pool"), sample_ms, _pool_hashrate(record), now_ms)
    history["network"] = _append_history_point(history.get("network"), sample_ms, _network_hashrate(record), now_ms)


def _format_hashrate(value: Any) -> str:
    hashrate = _as_float(value)
    units = ("H", "KH", "MH", "GH")
    unit_index = 0
    while abs(hashrate) >= 1000 and unit_index < len(units) - 1:
        hashrate /= 1000.0
        unit_index += 1
    if hashrate == 0:
        rendered = "0"
    elif abs(hashrate) >= 100:
        rendered = f"{hashrate:.0f}"
    elif abs(hashrate) >= 10:
        rendered = f"{hashrate:.1f}"
    else:
        rendered = f"{hashrate:.2f}".rstrip("0").rstrip(".")
    return f"{rendered} {units[unit_index]}"


def _pool_hashrate(record: SnapshotRecord | None) -> float:
    if record is None:
        return 0.0
    pool = record.data.get("pool", {})
    if not isinstance(pool, dict):
        return 0.0
    return _as_float(pool.get("poolHashrate"))


def _active_worker_count(record: SnapshotRecord | None) -> int:
    if record is None:
        return 0
    pool = record.data.get("pool", {})
    if not isinstance(pool, dict):
        return 0
    return _as_int(pool.get("activeWorkers"))


def _active_miner_workers(record: SnapshotRecord | None) -> dict[str, dict[str, Any]]:
    if record is None:
        return {}
    miners = record.data.get("miners", {})
    if not isinstance(miners, dict):
        return {}
    workers: dict[str, dict[str, Any]] = {}
    for wallet, miner_data in miners.items():
        if not isinstance(wallet, str) or not isinstance(miner_data, dict):
            continue
        for worker in miner_data.get("workers", []):
            if not isinstance(worker, dict):
                continue
            worker_name = str(worker.get("name") or "default")
            hashrate = _as_float(worker.get("hashrate"))
            share_count = _as_float(worker.get("shareCount", worker.get("acceptedShares", 0.0)))
            workers[f"{wallet}.{worker_name}"] = {
                "shares": share_count,
                "invalidshares": 0,
                "hashrateString": _format_hashrate(hashrate),
            }
    return workers


def _share_counts(record: SnapshotRecord | None) -> tuple[int, int]:
    if record is None:
        return 0, 0
    miners = record.data.get("miners", {})
    if not isinstance(miners, dict):
        return 0, 0
    accepted = 0
    rejected = 0
    for miner_data in miners.values():
        if not isinstance(miner_data, dict):
            continue
        summary = miner_data.get("summary", {})
        if not isinstance(summary, dict):
            continue
        accepted += _as_int(summary.get("acceptedShares"))
        rejected += _as_int(summary.get("rejectedShares"))
    return accepted, rejected


def _normalize_block_status(candidate: dict[str, Any]) -> str:
    status = str(_first_present(candidate, "lifecycle_status", "lifecycleStatus") or "").lower()
    maturity = str(_first_present(candidate, "maturity_label", "maturityLabel") or "").lower()
    followup = str(_first_present(candidate, "followup_status", "followupStatus") or "").lower()
    if status == "confirmed" or maturity == "mature":
        return "confirmed"
    if status == "orphan" or "orphan" in maturity or "orphan" in followup:
        return "orphan"
    if status in {"immature", "chain_match_found", "submit_accepted"} or maturity == "immature":
        return "immature"
    return "pending"


def _block_counts(accepted_candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"pending": 0, "confirmed": 0, "orphaned": 0}
    for candidate in accepted_candidates:
        status = _normalize_block_status(candidate)
        if status == "confirmed":
            counts["confirmed"] += 1
        elif status == "orphan":
            counts["orphaned"] += 1
        else:
            counts["pending"] += 1
    return counts


def _pool_block_records(accepted_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = []
    for candidate in accepted_candidates:
        height_value = _first_present(candidate, "matched_height", "matchedHeight", "height")
        height = None if height_value is None else _as_int(height_value, -1)
        if height == -1:
            height = None
        block_hash = _first_present(
            candidate,
            "matched_block_hash",
            "matchedBlockHash",
            "blockHash",
            "candidate_hash",
            "candidateHash",
        )
        timestamp = _first_present(candidate, "submit_timestamp", "submitTimestamp", "timestamp", "time")
        if height is None and not block_hash:
            continue
        blocks.append(
            {
                "height": height,
                "hash": block_hash,
                "time": timestamp,
                "timeUnix": _parse_time_ms(timestamp) // 1000 if timestamp else None,
                "status": _normalize_block_status(candidate),
                "confirmations": _as_int(_first_present(candidate, "confirmations", "confirms"), 0),
            }
        )
    blocks.sort(
        key=lambda item: (
            item["height"] if isinstance(item.get("height"), int) else -1,
            item["timeUnix"] if isinstance(item.get("timeUnix"), int) else -1,
        ),
        reverse=True,
    )
    return blocks[:100]


def _current_chain_height(record: SnapshotRecord | None) -> int | None:
    if record is None:
        return None
    network = record.data.get("network", {})
    if not isinstance(network, dict):
        return None
    for key in ("height", "blockHeight", "currentHeight"):
        if network.get(key) is not None:
            return _as_int(network.get(key), -1)
    return None


def _blocks_last_100(record: SnapshotRecord | None, recent_blocks: list[dict[str, Any]]) -> int:
    current_height = _current_chain_height(record)
    if current_height is None or current_height < 0:
        return len([block for block in recent_blocks[:100] if block.get("status") != "orphan"])
    lower_bound = current_height - 99
    return len(
        [
            block
            for block in recent_blocks
            if block.get("status") != "orphan"
            and isinstance(block.get("height"), int)
            and block["height"] >= lower_bound
        ]
    )


def _total_paid(payments: list[dict[str, Any]]) -> float:
    total = 0.0
    for payment in payments:
        total += _as_float(payment.get("amount"))
    return total


def _build_mining_pool_stats_payload(
    record: SnapshotRecord | None,
    accepted_candidates: list[dict[str, Any]],
    payments: list[dict[str, Any]],
) -> dict[str, Any]:
    pool_hashrate = _pool_hashrate(record)
    active_workers = _active_worker_count(record)
    accepted_shares, rejected_shares = _share_counts(record)
    block_counts = _block_counts(accepted_candidates)
    recent_blocks = _pool_block_records(accepted_candidates)
    last_block = recent_blocks[0] if recent_blocks else {}
    block_fields = {
        "recentBlocks": recent_blocks,
        "lastBlockHeight": last_block.get("height"),
        "lastBlockHash": last_block.get("hash"),
        "lastBlockTime": last_block.get("time"),
        "lastBlockTimeUnix": last_block.get("timeUnix"),
        "blocksLast100": _blocks_last_100(record, recent_blocks),
    }
    total_paid = _total_paid(payments)
    workers = _active_miner_workers(record)
    hashrate_string = _format_hashrate(pool_hashrate)
    pool_payload = {
        "name": "hoohashv110-pepew",
        "symbol": "PEPEW",
        "algorithm": "hoohashv110",
        "fee": "1",
        "feeType": "PPLNS",
        "poolStats": {
            "validShares": str(accepted_shares),
            "validBlocks": str(block_counts["confirmed"]),
            "invalidShares": str(rejected_shares),
            "totalPaid": str(total_paid),
        },
        "blocks": block_counts,
        "workers": workers,
        "hashrate": pool_hashrate,
        "workerCount": active_workers,
        "hashrateString": hashrate_string,
        **block_fields,
    }
    return {
        "time": int(time.time()),
        **block_fields,
        "global": {"workers": active_workers, "hashrate": pool_hashrate},
        "algos": {
            "hoohashv110": {
                "workers": active_workers,
                "hashrate": pool_hashrate,
                "hashrateString": hashrate_string,
            }
        },
        "pools": {"hoohashv110-pepew": pool_payload},
    }


def _unknown_operator_status_payload() -> dict[str, Any]:
    return {
        "generatedAt": _now_iso(),
        "status": "unknown",
        "items": [
            {"key": key, "label": label, "status": "unknown", "message": message}
            for key, label, message in OPERATOR_STATUS_ITEMS
        ],
    }


def _safe_public_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in PUBLIC_STATUSES else "unknown"


def _safe_public_message(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if text in {
        "Snapshots fresh",
        "Snapshot delayed",
        "Pool health review",
        "Status unavailable",
        "Wallet growth normal",
        "Review wallet growth",
        "Wallet balance unavailable",
        "Explorer balance timeout",
        "Payments consistent",
        "Payment records need review",
    }:
        return text
    return fallback


def _sanitize_operator_status_payload(data: Any) -> dict[str, Any]:
    unknown = _unknown_operator_status_payload()
    if not isinstance(data, dict) or not data:
        return unknown
    by_key = {}
    raw_items = data.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                by_key[item["key"]] = item
    items = []
    for key, label, fallback_message in OPERATOR_STATUS_ITEMS:
        item = by_key.get(key, {})
        items.append(
            {
                "key": key,
                "label": label,
                "status": _safe_public_status(item.get("status") if isinstance(item, dict) else None),
                "message": _safe_public_message(
                    item.get("message") if isinstance(item, dict) else None,
                    fallback_message,
                ),
            }
        )
    return {
        "generatedAt": data.get("generatedAt") if isinstance(data.get("generatedAt"), str) else unknown["generatedAt"],
        "status": _safe_public_status(data.get("status")),
        "items": items,
    }


def _map_round_shares(shares_dict: Any) -> dict[str, Any]:
    if not isinstance(shares_dict, dict):
        return {}
    mapped = {}
    for wallet, data in shares_dict.items():
        if isinstance(data, dict):
            wallet_mapped = {
                "shareCount": data.get("share_count"),
                "shareScore": data.get("share_score"),
                "sharePercent": data.get("share_percent"),
            }
            if isinstance(data.get("workers"), dict):
                wallet_mapped["workers"] = {
                    worker: {
                        "shareCount": w_data.get("share_count"),
                        "shareScore": w_data.get("share_score"),
                        "sharePercent": w_data.get("share_percent"),
                        "walletSharePercent": w_data.get("wallet_share_percent"),
                    }
                    if isinstance(w_data, dict)
                    else w_data
                    for worker, w_data in data["workers"].items()
                }
            mapped[wallet] = wallet_mapped
        else:
            mapped[wallet] = {"shareCount": None, "shareScore": data, "sharePercent": None}
    return mapped


def _normalize_payment_item(item: dict[str, Any]) -> dict[str, Any]:
    paid_at = item.get("paidAt") or item.get("timestamp")
    timestamp = item.get("timestamp") or item.get("paidAt")
    return {
        "paidAt": paid_at,
        "timestamp": timestamp,
        "amount": item.get("amount"),
        "txid": item.get("txid"),
        "wallet": item.get("wallet"),
        "candidateId": item.get("candidateId") or item.get("candidate_id"),
        "blockHeight": _first_present(item, "blockHeight", "height", "matchedHeight", "block_height"),
        "blockHeights": item.get("blockHeights") or item.get("block_heights"),
        "blockHeightRange": item.get("blockHeightRange") or item.get("block_height_range"),
        "blockCount": item.get("blockCount") or item.get("sourceCount") or item.get("source_count"),
        "sourceCandidateIds": item.get("sourceCandidateIds") or item.get("source_candidate_ids"),
        "blockHash": item.get("blockHash"),
        "status": item.get("status"),
        "confirmations": _first_present(item, "confirmations", "confirms", "txConfirmations", "candidateConfirmations"),
        "note": item.get("note"),
    }


def _recent_payments_for_wallet(wallet: str, primary_path, fallback_path) -> tuple[list[dict[str, Any]], float]:
    data = _load_json_dict(primary_path, fallback_path)
    items = data.get("items", [])
    recent = []
    total = 0.0
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("wallet") == wallet:
                recent.append(_normalize_payment_item(item))
                total += _as_float(item.get("amount"))
    recent.sort(key=lambda item: str(item.get("paidAt") or item.get("timestamp") or ""), reverse=True)
    return recent[:50], total


app = create_app()


if __name__ == "__main__":
    config = app.config["APP_CONFIG"]
    serve(app, host=config.host, port=config.port)

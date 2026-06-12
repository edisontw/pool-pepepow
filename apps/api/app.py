from __future__ import annotations

import json
import re
import time
import urllib.request
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from flask import Flask, jsonify
from waitress import serve

from config import AppConfig, load_config
from store import SnapshotRecord, SnapshotStore, SnapshotUnavailableError


def parse_price_defensively(data: Any) -> float | None:
    if not data:
        return None
    if isinstance(data, list):
        if len(data) > 0:
            data = data[0]
        else:
            return None
    if not isinstance(data, dict):
        return None

    # Unpack nested ticker/data if present
    if "ticker" in data and isinstance(data["ticker"], dict):
        data = data["ticker"]
    elif "data" in data and isinstance(data["data"], dict):
        data = data["data"]

    for key in ["last_price", "last", "price"]:
        if key in data and data[key] is not None:
            try:
                return float(data[key])
            except (ValueError, TypeError):
                pass

    # Try bid/ask midpoint
    bid = None
    ask = None
    for key in ["bid", "buy"]:
        if key in data and data[key] is not None:
            try:
                bid = float(data[key])
                break
            except (ValueError, TypeError):
                pass
    for key in ["ask", "sell"]:
        if key in data and data[key] is not None:
            try:
                ask = float(data[key])
                break
            except (ValueError, TypeError):
                pass

    if bid is not None and ask is not None:
        return (bid + ask) / 2.0

    return None


class PriceCache:
    def __init__(self, cache_ttl_seconds: int = 120) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self.price: float | None = None
        self.updated_at: str | None = None
        self.last_fetch_success: float = 0.0
        self.last_fetch_attempt: float = 0.0
        self.lock = threading.Lock()

    def get_price_info(self) -> dict[str, Any]:
        now = time.time()
        with self.lock:
            should_fetch = (now - self.last_fetch_success >= self.cache_ttl_seconds) and (now - self.last_fetch_attempt >= 10.0)
            if should_fetch:
                self.last_fetch_attempt = now

        if should_fetch:
            try:
                req = urllib.request.Request(
                    "https://api.nonkyc.io/api/v2/ticker/PEPEW_USDT",
                    headers={"User-Agent": "pepepow-pool-api/0.1.0"}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    raw_data = response.read().decode("utf-8")
                    data = json.loads(raw_data)
                    new_price = parse_price_defensively(data)
                    if new_price is not None:
                        new_updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        with self.lock:
                            self.price = new_price
                            self.updated_at = new_updated_at
                            self.last_fetch_success = now
            except Exception as e:
                print(f"Error fetching PEPEW price from NonKYC: {e}")

        with self.lock:
            return {
                "symbol": "PEPEW_USDT",
                "price": self.price,
                "source": "nonkyc",
                "updatedAt": self.updated_at,
                "cacheSeconds": self.cache_ttl_seconds
            }



LOCAL_SERVICE_BASELINE = {
    "core": True,
    "api": True,
    "stratum": True,
    "frontendExpected": False,
    "deploymentVariant": "core-api-stratum-no-local-frontend",
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
    wallet_pattern = re.compile(app_config.allowed_wallet_pattern)

    def json_error(status: HTTPStatus, message: str):
        response = jsonify(
            {
                "error": {
                    "code": status.value,
                    "message": message,
                }
            }
        )
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
        status = "ok" if not record.degraded else "degraded"
        return jsonify(
            {
                "service": app_config.app_name,
                "localServiceBaseline": LOCAL_SERVICE_BASELINE,
                "status": status,
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
                "chainVerificationProgress": record.meta.get(
                    "chainVerificationProgress"
                ),
                "activityMode": record.meta.get("activityMode"),
                "activityDataSource": record.meta.get("activityDataSource"),
                "activityDataStatus": record.meta.get("activityDataStatus"),
                "activityWindowSeconds": record.meta.get("activityWindowSeconds"),
                "activityLastShareAt": record.meta.get("activityLastShareAt"),
                "activityWarningCount": record.meta.get("activityWarningCount"),
                "activityDerivedFromShares": record.meta.get(
                    "activityDerivedFromShares"
                ),
                "blockchainVerified": record.meta.get("blockchainVerified"),
                "templateModeConfigured": record.meta.get("templateModeConfigured"),
                "templateModeEffective": record.meta.get("templateModeEffective"),
                "templateDaemonRpcStatus": record.meta.get(
                    "templateDaemonRpcStatus"
                ),
                "templateDaemonRpcReachable": record.meta.get(
                    "templateDaemonRpcReachable"
                ),
                "templateFetchStatus": record.meta.get("templateFetchStatus"),
                "templateLastAttemptAt": record.meta.get("templateLastAttemptAt"),
                "templateLastSuccessAt": record.meta.get("templateLastSuccessAt"),
                "templateLatestTemplateAgeSeconds": record.meta.get(
                    "templateLatestTemplateAgeSeconds"
                ),
                "templateLatestTemplateAnchor": record.meta.get(
                    "templateLatestTemplateAnchor"
                ),
                "templateLastError": record.meta.get("templateLastError"),
                "activeJobCount": record.meta.get("activeJobCount"),
                "assumedShareDifficulty": record.meta.get("assumedShareDifficulty"),
                "hashratePolicy": record.meta.get("hashratePolicy"),
                "submitValidationMode": record.meta.get("submitValidationMode"),
                "submitHashValidCount": record.meta.get("submitHashValidCount"),
                "submitHashInvalidCount": record.meta.get("submitHashInvalidCount"),
                "submitDuplicateWindowSize": record.meta.get(
                    "submitDuplicateWindowSize"
                ),
                "submitCandidatePossibleCount": record.meta.get(
                    "submitCandidatePossibleCount"
                ),
                "shareHashValidationMode": record.meta.get(
                    "shareHashValidationMode"
                ),
                "realSubmitblockEnabled": record.meta.get(
                    "realSubmitblockEnabled"
                ),
                "realSubmitblockSendBudget": record.meta.get(
                    "realSubmitblockSendBudget"
                ),
                "realSubmitblockSendBudgetRemaining": record.meta.get(
                    "realSubmitblockSendBudgetRemaining"
                ),
                "realSubmitblockAttemptCount": record.meta.get(
                    "realSubmitblockAttemptCount"
                ),
                "realSubmitblockSentCount": record.meta.get(
                    "realSubmitblockSentCount"
                ),
                "realSubmitblockErrorCount": record.meta.get(
                    "realSubmitblockErrorCount"
                ),
                "realSubmitblockLastStatus": record.meta.get(
                    "realSubmitblockLastStatus"
                ),
                "realSubmitblockLastAttemptAt": record.meta.get(
                    "realSubmitblockLastAttemptAt"
                ),
                "realSubmitblockLastError": record.meta.get(
                    "realSubmitblockLastError"
                ),
                "submitClassificationCounts": record.meta.get(
                    "submitClassificationCounts"
                ),
                "submitRejectReasonCounts": record.meta.get(
                    "submitRejectReasonCounts"
                ),
                "submitTargetValidationCounts": record.meta.get(
                    "submitTargetValidationCounts"
                ),
                "submitShareHashValidationCounts": record.meta.get(
                    "submitShareHashValidationCounts"
                ),
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
        payload["dataStatus"] = record.data_status
        payload["placeholderFields"] = _placeholder_fields(record.data)
        payload["snapshotSource"] = record.source
        payload["generatedAt"] = record.generated_at
        payload["activityMode"] = record.meta.get("activityMode")
        payload["activityDataStatus"] = record.meta.get("activityDataStatus")
        payload["activityWindowSeconds"] = record.meta.get("activityWindowSeconds")
        payload["activityDerivedFromShares"] = record.meta.get(
            "activityDerivedFromShares"
        )
        payload["blockchainVerified"] = record.meta.get("blockchainVerified")
        payload["templateModeEffective"] = record.meta.get("templateModeEffective")
        payload["activeJobCount"] = record.meta.get("activeJobCount")
        payload["assumedShareDifficulty"] = record.meta.get(
            "assumedShareDifficulty"
        )
        payload["hashratePolicy"] = record.meta.get("hashratePolicy")
        return jsonify(payload)

    @app.get("/api/network/summary")
    def network_summary():
        record = get_snapshot_record()
        payload = dict(record.data["network"])
        payload["dataStatus"] = record.data_status
        payload["placeholderFields"] = _placeholder_fields(record.data)
        payload["snapshotSource"] = record.source
        payload["generatedAt"] = record.generated_at
        payload["chainState"] = record.meta.get("chainState")
        payload["chainVerificationProgress"] = record.meta.get(
            "chainVerificationProgress"
        )
        payload["blockFeedKind"] = record.meta.get("blockFeedKind")
        return jsonify(payload)

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
        import json
        path = app_config.activity_snapshot_path.parent / "accepted-candidates.json"
        if not path.exists():
            path = app_config.runtime_snapshot_path.parent / "accepted-candidates.json"
        if not path.exists():
            return jsonify({"items": []})
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            candidates = data.get("accepted_candidates", [])
        except Exception:
            return jsonify({"items": []})

        items = []
        for c in candidates:
            items.append({
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
            })
        return jsonify({"items": items})

    @app.get("/api/rounds")
    def rounds():
        import json
        from pathlib import Path
        path = app_config.activity_snapshot_path.parent / "rounds-snapshot.json"
        if not path.exists():
            path = app_config.runtime_snapshot_path.parent / "rounds-snapshot.json"
        if not path.exists():
            return jsonify({"items": []})
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            rounds_list = data.get("rounds", [])
        except Exception:
            return jsonify({"items": []})

        def map_shares(shares_dict: dict[str, Any]) -> dict[str, Any]:
            mapped = {}
            for wallet, data in shares_dict.items():
                if isinstance(data, dict):
                    wallet_mapped = {
                        "shareCount": data.get("share_count"),
                        "shareScore": data.get("share_score"),
                        "sharePercent": data.get("share_percent"),
                    }
                    if "workers" in data and isinstance(data["workers"], dict):
                        workers_mapped = {}
                        for worker, w_data in data["workers"].items():
                            if isinstance(w_data, dict):
                                workers_mapped[worker] = {
                                    "shareCount": w_data.get("share_count"),
                                    "shareScore": w_data.get("share_score"),
                                    "sharePercent": w_data.get("share_percent"),
                                    "walletSharePercent": w_data.get("wallet_share_percent"),
                                }
                            else:
                                workers_mapped[worker] = w_data
                        wallet_mapped["workers"] = workers_mapped
                    mapped[wallet] = wallet_mapped
                else:
                    # Fallback for legacy format
                    mapped[wallet] = {
                        "shareCount": None,
                        "shareScore": data,
                        "sharePercent": None,
                    }
            return mapped

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
                "shares": map_shares(r.get("shares", {})),
            }
            if "payable" in r:
                item["payable"] = r["payable"]
            items.append(item)

        items.reverse()
        items = items[:50]
        return jsonify({"items": items})

    @app.get("/api/payments")
    def payments():
        import json
        path = app_config.activity_snapshot_path.parent / "payments-snapshot.json"
        if not path.exists():
            path = app_config.runtime_snapshot_path.parent / "payments-snapshot.json"
        if not path.exists():
            return jsonify({"items": []})
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "items" in data:
                return jsonify(data)
            return jsonify({"items": []})
        except Exception:
            return jsonify({"items": []})

    @app.get("/api/miner/<wallet>")
    def miner(wallet: str):
        if not wallet_pattern.fullmatch(wallet):
            return json_error(HTTPStatus.BAD_REQUEST, "Wallet format is invalid")

        # Load recorded manual payments from payments-snapshot.json
        recent_payments = []
        total_paid_manual = 0.0

        import json
        payments_path = app_config.activity_snapshot_path.parent / "payments-snapshot.json"
        if not payments_path.exists():
            payments_path = app_config.runtime_snapshot_path.parent / "payments-snapshot.json"

        if payments_path.exists():
            try:
                with payments_path.open("r", encoding="utf-8") as f:
                    payments_data = json.load(f)
                if isinstance(payments_data, dict) and isinstance(payments_data.get("items"), list):
                    for item in payments_data["items"]:
                        if isinstance(item, dict) and item.get("wallet") == wallet:
                            recent_payments.append(item)
                            try:
                                total_paid_manual += float(item.get("amount", 0.0))
                            except (ValueError, TypeError):
                                pass
            except Exception:
                pass

        record = get_snapshot_record()
        if not bool(record.meta.get("minerLookupImplemented", False)):
            return jsonify(
                {
                    "found": False,
                    "wallet": wallet,
                    "summary": None,
                    "workers": [],
                    "payments": [],
                    "recentPayments": recent_payments,
                    "totalPaidManual": total_paid_manual,
                    "implemented": False,
                    "status": "not-implemented",
                    "dataStatus": record.data_status,
                    "activityMode": record.meta.get("activityMode"),
                    "activityDataStatus": record.meta.get("activityDataStatus"),
                }
            )

        miners = record.data.get("miners", {})
        miner_record = miners.get(wallet)

        if miner_record is None:
            return jsonify(
                {
                    "found": False,
                    "wallet": wallet,
                    "summary": None,
                    "workers": [],
                    "payments": [],
                    "recentPayments": recent_payments,
                    "totalPaidManual": total_paid_manual,
                    "implemented": True,
                    "status": "ok",
                    "dataStatus": record.data_status,
                    "activityMode": record.meta.get("activityMode"),
                    "activityDataStatus": record.meta.get("activityDataStatus"),
                }
            )

        return jsonify(
            {
                "found": True,
                "wallet": wallet,
                "summary": miner_record.get("summary", {}),
                "workers": miner_record.get("workers", []),
                "payments": miner_record.get("payments", []),
                "recentPayments": recent_payments,
                "totalPaidManual": total_paid_manual,
                "implemented": True,
                "status": "ok",
                "dataStatus": record.data_status,
                "activityMode": record.meta.get("activityMode"),
                "activityDataStatus": record.meta.get("activityDataStatus"),
                "activityDerivedFromShares": record.meta.get(
                    "activityDerivedFromShares"
                ),
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


def _placeholder_fields(snapshot: dict[str, Any]) -> list[str]:
    meta = snapshot.get("meta", {})
    placeholder_fields = meta.get("placeholderFields", [])
    if isinstance(placeholder_fields, list):
        return [field for field in placeholder_fields if isinstance(field, str)]
    return []


def _load_json_items(primary_path, fallback_path, item_key: str) -> list[dict[str, Any]]:
    path = primary_path if primary_path.exists() else fallback_path
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    items = data.get(item_key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


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
            key = f"{wallet}.{worker_name}"
            hashrate = _as_float(worker.get("hashrate"))
            share_count = _as_float(
                worker.get("shareCount", worker.get("acceptedShares", 0.0))
            )
            workers[key] = {
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


def _block_counts(accepted_candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"pending": 0, "confirmed": 0, "orphaned": 0}
    for candidate in accepted_candidates:
        status = str(candidate.get("lifecycle_status") or candidate.get("lifecycleStatus") or "").lower()
        maturity = str(candidate.get("maturity_label") or candidate.get("maturityLabel") or "").lower()
        if status == "confirmed" or maturity == "mature":
            counts["confirmed"] += 1
        elif status == "orphan" or "orphan" in maturity:
            counts["orphaned"] += 1
        elif status:
            counts["pending"] += 1
    return counts


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
    total_paid = _total_paid(payments)
    workers = _active_miner_workers(record)
    hashrate_string = _format_hashrate(pool_hashrate)

    return {
        "time": int(time.time()),
        "global": {
            "workers": active_workers,
            "hashrate": pool_hashrate,
        },
        "algos": {
            "hoohashv110": {
                "workers": active_workers,
                "hashrate": pool_hashrate,
                "hashrateString": hashrate_string,
            }
        },
        "pools": {
            "hoohashv110-pepew": {
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
            }
        },
    }


app = create_app()


if __name__ == "__main__":
    config = app.config["APP_CONFIG"]
    serve(app, host=config.host, port=config.port)

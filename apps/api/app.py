from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any

from flask import Flask, jsonify
from waitress import serve

from config import AppConfig, load_config
from store import SnapshotRecord, SnapshotStore, SnapshotUnavailableError


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
                "assumedShareDifficulty": record.meta.get("assumedShareDifficulty"),
                "hashratePolicy": record.meta.get("hashratePolicy"),
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

    @app.get("/api/payments")
    def payments():
        record = get_snapshot_record()
        return jsonify(
            {
                "items": record.data["payments"],
                "status": record.meta.get("paymentsStatus", "placeholder"),
                "dataStatus": record.data_status,
            }
        )

    @app.get("/api/miner/<wallet>")
    def miner(wallet: str):
        if not wallet_pattern.fullmatch(wallet):
            return json_error(HTTPStatus.BAD_REQUEST, "Wallet format is invalid")

        record = get_snapshot_record()
        if not bool(record.meta.get("minerLookupImplemented", False)):
            return jsonify(
                {
                    "found": False,
                    "wallet": wallet,
                    "summary": None,
                    "workers": [],
                    "payments": [],
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

    return app


def _placeholder_fields(snapshot: dict[str, Any]) -> list[str]:
    meta = snapshot.get("meta", {})
    placeholder_fields = meta.get("placeholderFields", [])
    if isinstance(placeholder_fields, list):
        return [field for field in placeholder_fields if isinstance(field, str)]
    return []


app = create_app()


if __name__ == "__main__":
    config = app.config["APP_CONFIG"]
    serve(app, host=config.host, port=config.port)

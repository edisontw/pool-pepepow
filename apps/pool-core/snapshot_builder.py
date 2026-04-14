from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def isoformat_from_timestamp(timestamp: int | float | None) -> str | None:
    if timestamp is None:
        return None

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")


def is_synced(blockchain_info: dict[str, Any]) -> bool:
    blocks = int(blockchain_info.get("blocks", 0))
    headers = int(blockchain_info.get("headers", blocks))
    verification_progress = float(
        blockchain_info.get("verificationprogress", 0.0)
    )
    return (headers - blocks) <= 2 and verification_progress >= 0.999


def derive_chain_state(blockchain_info: dict[str, Any]) -> str:
    if is_synced(blockchain_info):
        return "synced"

    blocks = int(blockchain_info.get("blocks", 0))
    headers = int(blockchain_info.get("headers", blocks))
    verification_progress = float(
        blockchain_info.get("verificationprogress", 0.0)
    )
    if blocks == 0 and headers > 0 and verification_progress < 0.01:
        return "reindexing"
    return "syncing"


def build_snapshot(
    *,
    generated_at: str,
    blockchain_info: dict[str, Any],
    best_block_header: dict[str, Any],
    recent_headers: list[dict[str, Any]],
    coin_name: str,
    algorithm: str,
    fee_percent: float,
    min_payout: float,
    stratum_host: str,
    stratum_port: int,
    stratum_tls: bool,
    producer_name: str,
    network_info: dict[str, Any] | None = None,
    mining_info: dict[str, Any] | None = None,
    degraded: bool = False,
    last_error: str | None = None,
    last_successful_runtime_at: str | None = None,
    activity_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    synced = is_synced(blockchain_info)
    chain_state = derive_chain_state(blockchain_info)
    if degraded:
        pool_status = "degraded"
    else:
        pool_status = "online" if synced else "syncing"

    blocks = [
        {
            "height": int(header.get("height", 0)),
            "hash": str(header.get("hash", "")),
            "status": "observed-network",
            "foundAt": isoformat_from_timestamp(header.get("time")),
            "reward": None,
            "confirmations": int(header.get("confirmations", 0)),
        }
        for header in recent_headers
    ]

    network_hashrate: float | None = None
    if mining_info is not None:
        raw_network_hashrate = mining_info.get("networkhashps")
        if isinstance(raw_network_hashrate, (int, float)):
            network_hashrate = float(raw_network_hashrate)

    activity = activity_snapshot or {
        "mode": "testing-local-ingest",
        "dataSource": "local-jsonl-share-log",
        "windowSeconds": 900,
        "dataStatus": "empty",
        "lastShareAt": None,
        "warningCount": 0,
        "derivedFromShares": False,
        "blockchainVerified": True,
        "assumedShareDifficulty": None,
        "poolHashrate": None,
        "workerDistribution": [],
        "rolling": {},
        "activeMiners": 0,
        "activeWorkers": 0,
        "miners": {},
        "implemented": True,
    }
    snapshot = {
        "generatedAt": generated_at,
        "meta": {
            "schemaVersion": "2.2",
            "producer": producer_name,
            "degraded": degraded,
            "stale": False,
            "daemonReachable": True,
            "lastSuccessfulRuntimeAt": last_successful_runtime_at or generated_at,
            "lastError": last_error,
            "blockFeedKind": "observed-network-blocks",
            "chainDataSource": "pepepowd-rpc-read-only",
            "chainState": chain_state,
            "chainVerificationProgress": float(
                blockchain_info.get("verificationprogress", 0.0)
            ),
            "minerLookupImplemented": bool(activity.get("implemented", True)),
            "paymentsStatus": "placeholder",
            "activityMode": activity.get("mode", "testing-local-ingest"),
            "activityDataSource": activity.get(
                "dataSource", "local-jsonl-share-log"
            ),
            "activityWindowSeconds": int(activity.get("windowSeconds", 900)),
            "activityDataStatus": activity.get("dataStatus", "empty"),
            "activityLastShareAt": activity.get("lastShareAt"),
            "activityWarningCount": int(activity.get("warningCount", 0)),
            "activityDerivedFromShares": bool(
                activity.get("derivedFromShares", False)
            ),
            "blockchainVerified": bool(activity.get("blockchainVerified", True)),
            "assumedShareDifficulty": activity.get("assumedShareDifficulty"),
            "hashratePolicy": activity.get("hashratePolicy", "not-computed"),
            "placeholderFields": [],
        },
        "pool": {
            "coin": coin_name,
            "algorithm": algorithm,
            "poolStatus": pool_status,
            "feePercent": fee_percent,
            "minPayout": min_payout,
            "poolHashrate": activity.get("poolHashrate"),
            "activeMiners": int(activity.get("activeMiners", 0)),
            "activeWorkers": int(activity.get("activeWorkers", 0)),
            "workerDistribution": deepcopy(
                activity.get("workerDistribution", [])
                if isinstance(activity.get("workerDistribution", []), list)
                else []
            ),
            "lastBlockFoundAt": None,
            "stratum": {
                "host": stratum_host,
                "port": stratum_port,
                "tls": stratum_tls,
            },
        },
        "network": {
            "height": int(blockchain_info.get("blocks", 0)),
            "difficulty": float(blockchain_info.get("difficulty", 0.0)),
            "networkHashrate": network_hashrate,
            "lastBlockAt": isoformat_from_timestamp(best_block_header.get("time")),
            "reward": None,
            "synced": synced,
        },
        "blocks": blocks,
        "payments": [],
        "miners": activity.get("miners", {}),
    }

    if network_info is not None:
        warnings = network_info.get("warnings")
        if warnings:
            existing_error = snapshot["meta"].get("lastError")
            warning_message = str(warnings)
            snapshot["meta"]["lastError"] = (
                f"{existing_error}; {warning_message}"
                if isinstance(existing_error, str) and existing_error
                else warning_message
            )
            snapshot["meta"]["degraded"] = True
            snapshot["pool"]["poolStatus"] = "degraded"

    snapshot["meta"]["placeholderFields"] = _build_placeholder_fields(snapshot)
    return snapshot


def _build_placeholder_fields(snapshot: dict[str, Any]) -> list[str]:
    placeholders: list[str] = []
    pool = snapshot.get("pool", {})
    network = snapshot.get("network", {})
    blocks = snapshot.get("blocks", [])
    payments = snapshot.get("payments", [])
    miners = snapshot.get("miners", {})

    if not isinstance(pool, dict):
        return placeholders

    if pool.get("poolHashrate") is None:
        placeholders.append("pool.poolHashrate")
    if pool.get("lastBlockFoundAt") is None:
        placeholders.append("pool.lastBlockFoundAt")
    if isinstance(network, dict) and network.get("reward") is None:
        placeholders.append("network.reward")
    if isinstance(blocks, list) and any(
        isinstance(block, dict) and block.get("reward") is None for block in blocks
    ):
        placeholders.append("blocks.reward")
    if isinstance(payments, list) and not payments:
        placeholders.append("payments")
    if isinstance(miners, dict) and not miners:
        placeholders.append("miners")

    return placeholders

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path

from accounting import build_activity_snapshot
from activity_ingest import ShareEventLoadError, load_share_events
from config import PoolCoreConfig, load_config
from daemon_rpc import DaemonRpcClient, DaemonRpcError
from runtime_io import write_json_atomic
from snapshot_builder import build_snapshot


LOGGER = logging.getLogger("pepepow.pool_core")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


class SnapshotProducer:
    def __init__(
        self, config: PoolCoreConfig, rpc_client: DaemonRpcClient | None = None
    ) -> None:
        self._config = config
        self._rpc_client = rpc_client or DaemonRpcClient(
            rpc_url=config.rpc_url,
            rpc_user=config.rpc_user,
            rpc_password=config.rpc_password,
            timeout_seconds=config.rpc_timeout_seconds,
            cache_ttl_seconds=config.rpc_cache_ttl_seconds,
        )
        self._consecutive_failures = 0
        self._last_successful_runtime_at: str | None = None

    def run_once(self) -> dict:
        blockchain_info = self._rpc_client.get_blockchain_info()
        best_block_hash = blockchain_info.get("bestblockhash")
        if not isinstance(best_block_hash, str) or not best_block_hash:
            raise DaemonRpcError("bestblockhash is missing from getblockchaininfo")

        best_block_header = self._rpc_client.get_block_header(best_block_hash)
        recent_headers = self._rpc_client.get_recent_block_headers(
            int(best_block_header.get("height", blockchain_info.get("blocks", 0))),
            self._config.recent_blocks_limit,
        )

        degraded = False
        last_errors: list[str] = []
        mining_info = None
        network_info = None
        activity_snapshot, activity_degraded, activity_error = self._load_activity()

        if activity_degraded:
            degraded = True
        if activity_error:
            last_errors.append(activity_error)

        try:
            mining_info = self._rpc_client.get_mining_info()
        except DaemonRpcError as exc:
            degraded = True
            last_errors.append(str(exc))

        try:
            network_info = self._rpc_client.get_network_info()
        except DaemonRpcError as exc:
            degraded = True
            last_errors.append(str(exc))

        generated_at = utc_now_iso()
        snapshot = build_snapshot(
            generated_at=generated_at,
            blockchain_info=blockchain_info,
            best_block_header=best_block_header,
            recent_headers=recent_headers,
            coin_name=self._config.coin_name,
            algorithm=self._config.algorithm,
            fee_percent=self._config.fee_percent,
            min_payout=self._config.min_payout,
            stratum_host=self._config.stratum_host,
            stratum_port=self._config.stratum_port,
            stratum_tls=self._config.stratum_tls,
            producer_name=self._config.producer_name,
            network_info=network_info,
            mining_info=mining_info,
            degraded=degraded,
            last_error="; ".join(last_errors) if last_errors else None,
            last_successful_runtime_at=generated_at,
            activity_snapshot=activity_snapshot,
        )
        write_snapshot_atomic(snapshot, self._config.snapshot_output_path)
        self._last_successful_runtime_at = generated_at
        self._consecutive_failures = 0
        return snapshot

    def run_forever(self) -> None:
        while True:
            try:
                snapshot = self.run_once()
                LOGGER.info(
                    "Wrote snapshot to %s at %s",
                    self._config.snapshot_output_path,
                    snapshot.get("generatedAt"),
                )
            except DaemonRpcError as exc:
                self._consecutive_failures += 1
                if self._should_log_failure():
                    LOGGER.warning(
                        "Snapshot refresh failed (%s): %s",
                        self._consecutive_failures,
                        exc,
                    )
            time.sleep(self._config.snapshot_interval_seconds)

    def _should_log_failure(self) -> bool:
        return self._consecutive_failures == 1 or self._consecutive_failures % 10 == 0

    def _load_activity(self) -> tuple[dict, bool, str | None]:
        try:
            load_result = load_share_events(self._config.activity_log_path)
        except ShareEventLoadError as exc:
            preserved = self._load_previous_activity_snapshot()
            if preserved is not None:
                preserved["dataStatus"] = "stale"
                preserved["warningCount"] = int(preserved.get("warningCount", 0)) + 1
                return preserved, True, str(exc)
            return self._empty_activity_snapshot(warning_count=1), True, str(exc)

        activity = build_activity_snapshot(
            load_result.events,
            activity_window_seconds=self._config.activity_window_seconds,
            warning_count=len(load_result.warnings),
            assumed_share_difficulty=self._config.estimated_hashrate_assumed_share_difficulty,
        )
        payload = {
            "mode": self._config.activity_mode,
            "dataSource": "local-jsonl-share-log",
            "windowSeconds": self._config.activity_window_seconds,
            "dataStatus": activity.data_status,
            "lastShareAt": activity.last_share_at,
            "warningCount": activity.warning_count,
            "derivedFromShares": activity.activity_derived_from_shares,
            "blockchainVerified": activity.blockchain_verified,
            "assumedShareDifficulty": activity.assumed_share_difficulty,
            "hashratePolicy": activity.hashrate_policy,
            "poolHashrate": activity.pool_hashrate,
            "workerDistribution": activity.worker_distribution,
            "rolling": activity.rolling,
            "activeMiners": activity.active_miners,
            "activeWorkers": activity.active_workers,
            "miners": activity.miners,
            "implemented": True,
        }

        errors: list[str] = []
        degraded = False
        if activity.data_status == "stale":
            degraded = True
            errors.append("Local share activity is stale")
        if load_result.warnings:
            degraded = True
            errors.append(
                f"Share event log had {len(load_result.warnings)} invalid line(s)"
            )

        return payload, degraded, "; ".join(errors) if errors else None

    def _empty_activity_snapshot(self, warning_count: int = 0) -> dict:
        return {
            "mode": self._config.activity_mode,
            "dataSource": "local-jsonl-share-log",
            "windowSeconds": self._config.activity_window_seconds,
            "dataStatus": "empty",
            "lastShareAt": None,
            "warningCount": warning_count,
            "derivedFromShares": True,
            "blockchainVerified": False,
            "assumedShareDifficulty": self._config.estimated_hashrate_assumed_share_difficulty,
            "hashratePolicy": "share-rate-assumed-diff",
            "poolHashrate": None,
            "workerDistribution": [],
            "rolling": {},
            "activeMiners": 0,
            "activeWorkers": 0,
            "miners": {},
            "implemented": True,
        }

    def _load_previous_activity_snapshot(self) -> dict | None:
        snapshot_path = self._config.snapshot_output_path
        if not snapshot_path.exists():
            return None

        try:
            existing = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            return None

        if not isinstance(existing, dict):
            return None

        meta = existing.get("meta", {})
        pool = existing.get("pool", {})
        miners = existing.get("miners", {})
        if not isinstance(meta, dict) or not isinstance(pool, dict) or not isinstance(
            miners, dict
        ):
            return None

        return {
            "mode": meta.get("activityMode", self._config.activity_mode),
            "dataSource": meta.get("activityDataSource", "local-jsonl-share-log"),
            "windowSeconds": int(
                meta.get(
                    "activityWindowSeconds", self._config.activity_window_seconds
                )
            ),
            "dataStatus": meta.get("activityDataStatus", "stale"),
            "lastShareAt": meta.get("activityLastShareAt"),
            "warningCount": int(meta.get("activityWarningCount", 0)),
            "derivedFromShares": bool(meta.get("activityDerivedFromShares", True)),
            "blockchainVerified": bool(meta.get("blockchainVerified", False)),
            "assumedShareDifficulty": meta.get(
                "assumedShareDifficulty",
                self._config.estimated_hashrate_assumed_share_difficulty,
            ),
            "hashratePolicy": meta.get("hashratePolicy", "share-rate-assumed-diff"),
            "poolHashrate": pool.get("poolHashrate"),
            "workerDistribution": pool.get("workerDistribution", []),
            "rolling": pool.get("rolling", {}),
            "activeMiners": int(pool.get("activeMiners", 0) or 0),
            "activeWorkers": int(pool.get("activeWorkers", 0) or 0),
            "miners": miners,
            "implemented": bool(meta.get("minerLookupImplemented", True)),
        }


def write_snapshot_atomic(snapshot: dict, output_path: Path) -> None:
    write_json_atomic(snapshot, output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PEPEPOW pool snapshot producer")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Write a single snapshot and exit",
    )
    return parser.parse_args(argv)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    config = load_config()
    producer = SnapshotProducer(config)

    if args.once:
        producer.run_once()
        return 0

    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
    producer.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

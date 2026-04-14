from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PoolCoreConfig:
    coin_name: str
    algorithm: str
    fee_percent: float
    min_payout: float
    stratum_host: str
    stratum_port: int
    stratum_tls: bool
    stratum_bind_host: str
    stratum_bind_port: int
    rpc_url: str
    rpc_user: str
    rpc_password: str
    rpc_timeout_seconds: float
    snapshot_output_path: Path
    activity_snapshot_output_path: Path
    snapshot_interval_seconds: int
    activity_snapshot_interval_seconds: float
    rpc_cache_ttl_seconds: int
    recent_blocks_limit: int
    stale_after_seconds: int
    producer_name: str
    activity_log_path: Path
    activity_window_seconds: int
    activity_mode: str
    stratum_queue_maxsize: int
    hashrate_assumed_share_difficulty: float
    synthetic_job_interval_seconds: float
    activity_log_rotate_bytes: int
    activity_log_retention_files: int


def load_config() -> PoolCoreConfig:
    default_snapshot_path = Path("/var/lib/pepepow-pool/pool-snapshot.json")
    default_activity_log_path = Path("/var/lib/pepepow-pool/share-events.jsonl")
    default_activity_snapshot_path = Path("/var/lib/pepepow-pool/activity-snapshot.json")
    rpc_host = os.getenv("PEPEPOWD_RPC_HOST", "127.0.0.1")
    rpc_port = int(os.getenv("PEPEPOWD_RPC_PORT", "8834"))
    stratum_port = int(os.getenv("PEPEPOW_POOL_CORE_STRATUM_PORT", "3333"))

    return PoolCoreConfig(
        coin_name=os.getenv("PEPEPOW_POOL_CORE_COIN_NAME", "PEPEPOW"),
        algorithm=os.getenv(
            "PEPEPOW_POOL_CORE_ALGORITHM", "hoohashv110-pepew"
        ),
        fee_percent=float(os.getenv("PEPEPOW_POOL_CORE_FEE_PERCENT", "1.0")),
        min_payout=float(
            os.getenv("PEPEPOW_POOL_CORE_MIN_PAYOUT", "10.0")
        ),
        stratum_host=os.getenv(
            "PEPEPOW_POOL_CORE_STRATUM_HOST", "pool.example.com"
        ),
        stratum_port=stratum_port,
        stratum_tls=_env_bool("PEPEPOW_POOL_CORE_STRATUM_TLS", False),
        stratum_bind_host=os.getenv(
            "PEPEPOW_POOL_CORE_STRATUM_BIND_HOST", "0.0.0.0"
        ),
        stratum_bind_port=int(
            os.getenv(
                "PEPEPOW_POOL_CORE_STRATUM_BIND_PORT", str(stratum_port)
            )
        ),
        rpc_url=os.getenv(
            "PEPEPOWD_RPC_URL", f"http://{rpc_host}:{rpc_port}"
        ),
        rpc_user=os.getenv("PEPEPOWD_RPC_USER", ""),
        rpc_password=os.getenv("PEPEPOWD_RPC_PASSWORD", ""),
        rpc_timeout_seconds=max(
            1.0, float(os.getenv("PEPEPOWD_RPC_TIMEOUT_SECONDS", "5"))
        ),
        snapshot_output_path=Path(
            os.getenv(
                "PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT",
                str(default_snapshot_path),
            )
        ).expanduser(),
        activity_snapshot_output_path=Path(
            os.getenv(
                "PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT",
                str(default_activity_snapshot_path),
            )
        ).expanduser(),
        snapshot_interval_seconds=max(
            10, int(os.getenv("PEPEPOW_POOL_CORE_INTERVAL_SECONDS", "60"))
        ),
        activity_snapshot_interval_seconds=max(
            0.25,
            float(
                os.getenv(
                    "PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS",
                    "1",
                )
            ),
        ),
        rpc_cache_ttl_seconds=max(
            1, int(os.getenv("PEPEPOW_POOL_CORE_RPC_CACHE_TTL_SECONDS", "5"))
        ),
        recent_blocks_limit=max(
            1, int(os.getenv("PEPEPOW_POOL_CORE_RECENT_BLOCKS_LIMIT", "10"))
        ),
        stale_after_seconds=max(
            60, int(os.getenv("PEPEPOW_POOL_CORE_STALE_AFTER_SECONDS", "180"))
        ),
        producer_name=os.getenv(
            "PEPEPOW_POOL_CORE_PRODUCER_NAME", "pepepow-pool-core"
        ),
        activity_log_path=Path(
            os.getenv(
                "PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH",
                str(default_activity_log_path),
            )
        ).expanduser(),
        activity_window_seconds=max(
            60, int(os.getenv("PEPEPOW_POOL_CORE_ACTIVITY_WINDOW_SECONDS", "900"))
        ),
        activity_mode=os.getenv(
            "PEPEPOW_POOL_CORE_ACTIVITY_MODE", "testing-local-ingest"
        ),
        stratum_queue_maxsize=max(
            100, int(os.getenv("PEPEPOW_POOL_CORE_STRATUM_QUEUE_MAXSIZE", "50000"))
        ),
        hashrate_assumed_share_difficulty=max(
            0.00000001,
            float(
                os.getenv(
                    "PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY",
                    "1.0",
                )
            ),
        ),
        synthetic_job_interval_seconds=max(
            1.0,
            float(
                os.getenv(
                    "PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS",
                    "30",
                )
            ),
        ),
        activity_log_rotate_bytes=max(
            1048576,
            int(
                os.getenv(
                    "PEPEPOW_POOL_CORE_ACTIVITY_LOG_ROTATE_BYTES",
                    str(32 * 1024 * 1024),
                )
            ),
        ),
        activity_log_retention_files=max(
            1,
            int(
                os.getenv(
                    "PEPEPOW_POOL_CORE_ACTIVITY_LOG_RETENTION_FILES",
                    "8",
                )
            ),
        ),
    )

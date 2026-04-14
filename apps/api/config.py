from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WALLET_PATTERN = r"^[A-Za-z0-9]{26,128}$"


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    version: str
    host: str
    port: int
    runtime_snapshot_path: Path
    fallback_snapshot_path: Path
    activity_snapshot_path: Path
    cache_ttl_seconds: int
    stale_after_seconds: int
    allowed_wallet_pattern: str


def load_config() -> AppConfig:
    base_dir = Path(__file__).resolve().parent
    default_fallback_snapshot = base_dir / "data" / "mock" / "pool-snapshot.json"
    default_runtime_snapshot = Path("/var/lib/pepepow-pool/pool-snapshot.json")
    default_activity_snapshot = Path("/var/lib/pepepow-pool/activity-snapshot.json")
    legacy_snapshot_path = os.getenv("PEPEPOW_POOL_API_SNAPSHOT_PATH")

    runtime_snapshot_path = os.getenv(
        "PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH",
        legacy_snapshot_path or str(default_runtime_snapshot),
    )

    return AppConfig(
        app_name="pepepow-pool-api",
        version=os.getenv("PEPEPOW_POOL_API_VERSION", "0.1.0-mvp"),
        host=os.getenv("PEPEPOW_POOL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("PEPEPOW_POOL_API_PORT", "8080")),
        runtime_snapshot_path=Path(runtime_snapshot_path).expanduser(),
        fallback_snapshot_path=Path(
            os.getenv(
                "PEPEPOW_POOL_API_FALLBACK_SNAPSHOT_PATH",
                str(default_fallback_snapshot),
            )
        ).expanduser(),
        activity_snapshot_path=Path(
            os.getenv(
                "PEPEPOW_POOL_API_ACTIVITY_SNAPSHOT_PATH",
                str(default_activity_snapshot),
            )
        ).expanduser(),
        cache_ttl_seconds=max(
            1, int(os.getenv("PEPEPOW_POOL_API_CACHE_TTL_SECONDS", "15"))
        ),
        stale_after_seconds=max(
            60, int(os.getenv("PEPEPOW_POOL_API_STALE_AFTER_SECONDS", "180"))
        ),
        allowed_wallet_pattern=os.getenv(
            "PEPEPOW_POOL_API_ALLOWED_WALLET_PATTERN", DEFAULT_WALLET_PATTERN
        ),
    )

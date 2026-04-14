from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from activity_engine import (
    ActivityEngine,
    DEFAULT_ASSUMED_SHARE_DIFFICULTY,
)
from activity_ingest import ShareEvent


@dataclass(frozen=True)
class ActivitySnapshot:
    active_miners: int
    active_workers: int
    miners: dict[str, Any]
    data_status: str
    last_share_at: str | None
    warning_count: int
    pool_hashrate: float | None
    worker_distribution: list[dict[str, Any]]
    rolling: dict[str, Any]
    hashrate_policy: str
    activity_derived_from_shares: bool
    blockchain_verified: bool
    assumed_share_difficulty: float


def build_activity_snapshot(
    events: list[ShareEvent],
    *,
    activity_window_seconds: int,
    warning_count: int = 0,
    now: datetime | None = None,
    assumed_share_difficulty: float = DEFAULT_ASSUMED_SHARE_DIFFICULTY,
) -> ActivitySnapshot:
    engine = ActivityEngine(
        assumed_share_difficulty=assumed_share_difficulty,
    )
    for event in sorted(events, key=lambda item: item.occurred_at):
        engine.ingest_event(event)

    snapshot = engine.build_snapshot(
        now=now,
        activity_mode="testing-local-ingest",
        activity_data_source="local-jsonl-share-log",
        synthetic_job_mode="disabled",
        share_validation_mode="none",
        live_window_seconds=activity_window_seconds,
        warning_count=warning_count,
    )
    meta = snapshot["meta"]
    pool = snapshot["pool"]
    miners = snapshot["miners"]
    last_share_at = meta.get("lastShareAt")

    return ActivitySnapshot(
        active_miners=int(pool.get("activeMiners", 0)),
        active_workers=int(pool.get("activeWorkers", 0)),
        miners=miners if isinstance(miners, dict) else {},
        data_status=str(meta.get("dataStatus", "empty")),
        last_share_at=last_share_at if isinstance(last_share_at, str) else None,
        warning_count=warning_count,
        pool_hashrate=pool.get("poolHashrate")
        if isinstance(pool.get("poolHashrate"), (int, float))
        else None,
        worker_distribution=pool.get("workerDistribution", [])
        if isinstance(pool.get("workerDistribution"), list)
        else [],
        rolling=pool.get("rolling", {}) if isinstance(pool.get("rolling"), dict) else {},
        hashrate_policy=str(meta.get("hashratePolicy", "share-rate-assumed-diff")),
        activity_derived_from_shares=bool(meta.get("activityDerivedFromShares", True)),
        blockchain_verified=bool(meta.get("blockchainVerified", False)),
        assumed_share_difficulty=float(
            meta.get("assumedShareDifficulty", assumed_share_difficulty)
        ),
    )

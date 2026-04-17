from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SnapshotUnavailableError(RuntimeError):
    """Raised when no usable snapshot file can be loaded safely."""


@dataclass
class CachedSnapshot:
    data: dict[str, Any]
    loaded_at: float
    source_mtime: float


@dataclass(frozen=True)
class SnapshotRecord:
    data: dict[str, Any]
    meta: dict[str, Any]
    source: str
    path: Path
    generated_at: str | None
    age_seconds: float | None
    stale: bool
    degraded: bool
    last_error: str | None
    data_status: str


class SnapshotStore:
    def __init__(
        self,
        runtime_snapshot_path: Path,
        fallback_snapshot_path: Path,
        activity_snapshot_path: Path,
        cache_ttl_seconds: int,
        stale_after_seconds: int,
    ) -> None:
        self._runtime_snapshot_path = runtime_snapshot_path
        self._fallback_snapshot_path = fallback_snapshot_path
        self._activity_snapshot_path = activity_snapshot_path
        self._cache_ttl_seconds = cache_ttl_seconds
        self._stale_after_seconds = stale_after_seconds
        self._cache: dict[Path, CachedSnapshot] = {}

    def get_snapshot(self) -> dict[str, Any]:
        return self.get_snapshot_record().data

    def get_snapshot_record(self) -> SnapshotRecord:
        runtime_error: str | None = None

        try:
            runtime_snapshot = self._load_cached_snapshot(
                self._runtime_snapshot_path,
                required_keys=("generatedAt", "pool", "network", "blocks", "payments", "miners"),
            )
            record = self._build_record(
                data=runtime_snapshot,
                source="runtime",
                path=self._runtime_snapshot_path,
                last_error=None,
            )
        except SnapshotUnavailableError as exc:
            runtime_error = str(exc)
            try:
                fallback_snapshot = self._load_cached_snapshot(
                    self._fallback_snapshot_path,
                    required_keys=("generatedAt", "pool", "network", "blocks", "payments", "miners"),
                )
                record = self._build_record(
                    data=fallback_snapshot,
                    source="fallback",
                    path=self._fallback_snapshot_path,
                    last_error=(
                        f"Runtime snapshot failed: {runtime_error}"
                        if runtime_error
                        else None
                    ),
                )
            except SnapshotUnavailableError as fallback_exc:
                raise SnapshotUnavailableError(
                    f"Runtime snapshot failed ({runtime_error}); fallback snapshot failed ({fallback_exc})"
                ) from fallback_exc

        return self._apply_activity_overlay(record)

    def get_snapshot_age_seconds(self) -> float | None:
        return self.get_snapshot_record().age_seconds

    def _apply_activity_overlay(self, record: SnapshotRecord) -> SnapshotRecord:
        if not self._activity_snapshot_path.exists():
            return record

        try:
            activity_snapshot = self._load_cached_snapshot(
                self._activity_snapshot_path,
                required_keys=("generatedAt", "meta", "pool", "miners"),
            )
        except SnapshotUnavailableError as exc:
            return SnapshotRecord(
                data=record.data,
                meta=record.meta,
                source=record.source,
                path=record.path,
                generated_at=record.generated_at,
                age_seconds=record.age_seconds,
                stale=record.stale,
                degraded=True,
                last_error=_append_error(record.last_error, f"Activity snapshot failed: {exc}"),
                data_status=record.data_status,
            )

        merged = copy.deepcopy(record.data)
        _overlay_activity_snapshot(merged, activity_snapshot)
        meta = merged.get("meta", {})
        last_error = _append_error(record.last_error, _as_string_or_none(meta.get("lastError")))
        degraded = record.degraded or bool(meta.get("degraded", False))

        return SnapshotRecord(
            data=merged,
            meta=meta if isinstance(meta, dict) else {},
            source=record.source,
            path=record.path,
            generated_at=record.generated_at,
            age_seconds=record.age_seconds,
            stale=record.stale,
            degraded=degraded,
            last_error=last_error,
            data_status=record.data_status,
        )

    def _build_record(
        self,
        *,
        data: dict[str, Any],
        source: str,
        path: Path,
        last_error: str | None,
    ) -> SnapshotRecord:
        age_seconds = _calculate_snapshot_age_seconds(data)
        stale = age_seconds is not None and age_seconds > self._stale_after_seconds
        meta = data.get("meta", {})
        source_degraded = bool(meta.get("degraded", False))
        degraded = source != "runtime" or stale or source_degraded

        if source == "runtime":
            data_status = "stale" if stale else "live"
        else:
            data_status = "fallback"

        return SnapshotRecord(
            data=data,
            meta=meta if isinstance(meta, dict) else {},
            source=source,
            path=path,
            generated_at=data.get("generatedAt")
            if isinstance(data.get("generatedAt"), str)
            else None,
            age_seconds=age_seconds,
            stale=stale,
            degraded=degraded,
            last_error=last_error or _as_string_or_none(meta.get("lastError")),
            data_status=data_status,
        )

    def _load_cached_snapshot(
        self, snapshot_path: Path, *, required_keys: tuple[str, ...]
    ) -> dict[str, Any]:
        now = time.time()
        stat = self._safe_stat(snapshot_path)
        cached = self._cache.get(snapshot_path)

        if cached is not None:
            cache_fresh = now - cached.loaded_at < self._cache_ttl_seconds
            same_source = stat.st_mtime == cached.source_mtime
            if cache_fresh and same_source:
                return cached.data

        data = self._load_snapshot(snapshot_path, required_keys=required_keys)
        self._cache[snapshot_path] = CachedSnapshot(
            data=data,
            loaded_at=now,
            source_mtime=stat.st_mtime,
        )
        return data

    def _safe_stat(self, snapshot_path: Path):
        try:
            return snapshot_path.stat()
        except OSError as exc:
            raise SnapshotUnavailableError(
                f"Snapshot file is unavailable: {snapshot_path}"
            ) from exc

    def _load_snapshot(
        self, snapshot_path: Path, *, required_keys: tuple[str, ...]
    ) -> dict[str, Any]:
        try:
            raw = snapshot_path.read_text(encoding="utf-8")
            snapshot = json.loads(raw)
        except FileNotFoundError as exc:
            raise SnapshotUnavailableError(
                f"Snapshot file not found: {snapshot_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise SnapshotUnavailableError(
                f"Snapshot file is not valid JSON: {snapshot_path}"
            ) from exc

        if not isinstance(snapshot, dict):
            raise SnapshotUnavailableError("Snapshot payload must be a JSON object")

        for key in required_keys:
            if key not in snapshot:
                raise SnapshotUnavailableError(f"Snapshot payload is missing '{key}'")

        return snapshot


def _overlay_activity_snapshot(
    base_snapshot: dict[str, Any], activity_snapshot: dict[str, Any]
) -> None:
    base_meta = base_snapshot.setdefault("meta", {})
    base_pool = base_snapshot.setdefault("pool", {})
    activity_meta = activity_snapshot.get("meta", {})
    activity_pool = activity_snapshot.get("pool", {})
    activity_miners = activity_snapshot.get("miners", {})

    if not isinstance(base_meta, dict) or not isinstance(base_pool, dict):
        return
    if not isinstance(activity_meta, dict) or not isinstance(activity_pool, dict):
        return

    window_seconds = activity_meta.get("windowSeconds", [])
    max_window_seconds = (
        max(value for value in window_seconds if isinstance(value, int))
        if isinstance(window_seconds, list)
        else None
    )

    base_meta["activityMode"] = activity_meta.get("activityMode", base_meta.get("activityMode"))
    base_meta["activityDataSource"] = activity_meta.get(
        "activityDataSource", base_meta.get("activityDataSource")
    )
    if max_window_seconds is not None:
        base_meta["activityWindowSeconds"] = max_window_seconds
    base_meta["activityDataStatus"] = activity_meta.get(
        "dataStatus", activity_meta.get("activityDataStatus", base_meta.get("activityDataStatus"))
    )
    base_meta["activityLastShareAt"] = activity_meta.get(
        "lastShareAt", base_meta.get("activityLastShareAt")
    )
    base_meta["activityWarningCount"] = int(activity_meta.get("warningCount", 0))
    base_meta["activityDerivedFromShares"] = bool(
        activity_meta.get("activityDerivedFromShares", True)
    )
    base_meta["blockchainVerified"] = bool(activity_meta.get("blockchainVerified", False))
    base_meta["syntheticJobMode"] = activity_meta.get(
        "syntheticJobMode", base_meta.get("syntheticJobMode")
    )
    base_meta["shareValidationMode"] = activity_meta.get(
        "shareValidationMode", base_meta.get("shareValidationMode")
    )
    base_meta["templateModeConfigured"] = activity_meta.get(
        "templateModeConfigured", base_meta.get("templateModeConfigured")
    )
    base_meta["templateModeEffective"] = activity_meta.get(
        "templateModeEffective", base_meta.get("templateModeEffective")
    )
    base_meta["templateDaemonRpcStatus"] = activity_meta.get(
        "templateDaemonRpcStatus", base_meta.get("templateDaemonRpcStatus")
    )
    base_meta["templateDaemonRpcReachable"] = activity_meta.get(
        "templateDaemonRpcReachable", base_meta.get("templateDaemonRpcReachable")
    )
    base_meta["templateFetchStatus"] = activity_meta.get(
        "templateFetchStatus", base_meta.get("templateFetchStatus")
    )
    base_meta["templateLastAttemptAt"] = activity_meta.get(
        "templateLastAttemptAt", base_meta.get("templateLastAttemptAt")
    )
    base_meta["templateLastSuccessAt"] = activity_meta.get(
        "templateLastSuccessAt", base_meta.get("templateLastSuccessAt")
    )
    base_meta["templateLatestTemplateAgeSeconds"] = activity_meta.get(
        "templateLatestTemplateAgeSeconds",
        base_meta.get("templateLatestTemplateAgeSeconds"),
    )
    base_meta["templateLatestTemplateAnchor"] = activity_meta.get(
        "templateLatestTemplateAnchor",
        base_meta.get("templateLatestTemplateAnchor"),
    )
    base_meta["templateLastError"] = activity_meta.get(
        "templateLastError", base_meta.get("templateLastError")
    )
    base_meta["activeJobCount"] = int(activity_meta.get("activeJobCount", 0) or 0)
    base_meta["assumedShareDifficulty"] = activity_meta.get("assumedShareDifficulty")
    base_meta["hashratePolicy"] = activity_meta.get(
        "hashratePolicy", base_meta.get("hashratePolicy")
    )
    base_meta["submitValidationMode"] = activity_meta.get(
        "submitValidationMode", base_meta.get("submitValidationMode")
    )
    base_meta["submitAcceptedCount"] = int(
        activity_meta.get("submitAcceptedCount", 0) or 0
    )
    base_meta["submitRejectedCount"] = int(
        activity_meta.get("submitRejectedCount", 0) or 0
    )
    base_meta["submitDuplicateWindowSize"] = int(
        activity_meta.get("submitDuplicateWindowSize", 0) or 0
    )
    base_meta["submitCandidatePossibleCount"] = int(
        activity_meta.get("submitCandidatePossibleCount", 0) or 0
    )
    base_meta["shareHashValidationMode"] = activity_meta.get(
        "shareHashValidationMode", base_meta.get("shareHashValidationMode")
    )
    base_meta["submitClassificationCounts"] = (
        activity_meta.get("submitClassificationCounts", {})
        if isinstance(activity_meta.get("submitClassificationCounts", {}), dict)
        else {}
    )
    base_meta["submitRejectReasonCounts"] = (
        activity_meta.get("submitRejectReasonCounts", {})
        if isinstance(activity_meta.get("submitRejectReasonCounts", {}), dict)
        else {}
    )
    base_meta["submitTargetValidationCounts"] = (
        activity_meta.get("submitTargetValidationCounts", {})
        if isinstance(activity_meta.get("submitTargetValidationCounts", {}), dict)
        else {}
    )
    base_meta["submitShareHashValidationCounts"] = (
        activity_meta.get("submitShareHashValidationCounts", {})
        if isinstance(activity_meta.get("submitShareHashValidationCounts", {}), dict)
        else {}
    )
    if isinstance(activity_miners, dict):
        base_meta["minerLookupImplemented"] = True
        base_snapshot["miners"] = activity_miners

    base_pool["poolHashrate"] = activity_pool.get("poolHashrate")
    base_pool["activeMiners"] = int(activity_pool.get("activeMiners", 0) or 0)
    base_pool["activeWorkers"] = int(activity_pool.get("activeWorkers", 0) or 0)
    base_pool["workerDistribution"] = (
        activity_pool.get("workerDistribution", [])
        if isinstance(activity_pool.get("workerDistribution", []), list)
        else []
    )
    base_pool["rolling"] = (
        activity_pool.get("rolling", {})
        if isinstance(activity_pool.get("rolling", {}), dict)
        else {}
    )

    placeholder_fields = _placeholder_fields(base_snapshot)
    base_meta["placeholderFields"] = placeholder_fields


def _placeholder_fields(snapshot: dict[str, Any]) -> list[str]:
    placeholders: list[str] = []
    pool = snapshot.get("pool", {})
    network = snapshot.get("network", {})
    blocks = snapshot.get("blocks", [])
    payments = snapshot.get("payments", [])
    miners = snapshot.get("miners", {})

    if isinstance(pool, dict):
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


def _calculate_snapshot_age_seconds(snapshot: dict[str, Any]) -> float | None:
    generated_at = snapshot.get("generatedAt")
    if not isinstance(generated_at, str):
        return None

    try:
        generated_at_dt = datetime.fromisoformat(
            generated_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except ValueError:
        return None

    return max(
        0.0, (datetime.now(timezone.utc) - generated_at_dt).total_seconds()
    )


def _as_string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _append_error(current: str | None, extra: str | None) -> str | None:
    if not extra:
        return current
    if not current:
        return extra
    if extra in current:
        return current
    return f"{current}; {extra}"

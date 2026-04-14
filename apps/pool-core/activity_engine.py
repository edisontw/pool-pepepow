from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from activity_ingest import ShareEvent


WINDOW_DEFINITIONS: tuple[tuple[str, int], ...] = (
    ("1m", 60),
    ("5m", 300),
    ("15m", 900),
)
WINDOW_SECONDS = {label: seconds for label, seconds in WINDOW_DEFINITIONS}
MAX_WINDOW_SECONDS = max(WINDOW_SECONDS.values())
HEADLINE_WINDOW_LABEL = "5m"
DEFAULT_ASSUMED_SHARE_DIFFICULTY = 1.0
HASHES_PER_SHARE = float(2**32)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


class WindowCounter:
    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._buckets = [0] * window_seconds
        self._stamps = [-1] * window_seconds
        self._total = 0
        self._last_seen_second: int | None = None

    def increment(self, second: int, count: int = 1) -> None:
        self._advance(second)
        index = second % self.window_seconds
        if self._stamps[index] != second:
            self._stamps[index] = second
            self._buckets[index] = 0
        self._buckets[index] += count
        self._total += count

    def total(self, second: int) -> int:
        self._advance(second)
        return self._total

    def _advance(self, second: int) -> None:
        if self._last_seen_second is None:
            self._last_seen_second = second
            self._prepare_bucket(second)
            return

        if second <= self._last_seen_second:
            return

        delta = second - self._last_seen_second
        if delta >= self.window_seconds:
            self._buckets = [0] * self.window_seconds
            self._stamps = [-1] * self.window_seconds
            self._total = 0
            self._last_seen_second = second
            self._prepare_bucket(second)
            return

        for current in range(self._last_seen_second + 1, second + 1):
            self._prepare_bucket(current)

        self._last_seen_second = second

    def _prepare_bucket(self, second: int) -> None:
        index = second % self.window_seconds
        if self._stamps[index] == second:
            return
        self._total -= self._buckets[index]
        self._buckets[index] = 0
        self._stamps[index] = second


def _new_window_counters() -> dict[str, WindowCounter]:
    return {
        label: WindowCounter(window_seconds)
        for label, window_seconds in WINDOW_DEFINITIONS
    }


@dataclass
class WorkerState:
    last_share_at: datetime | None = None
    accepted_shares: int = 0
    rejected_shares: int = 0
    accepted_windows: dict[str, WindowCounter] = field(default_factory=_new_window_counters)
    rejected_windows: dict[str, WindowCounter] = field(default_factory=_new_window_counters)

    @property
    def share_count(self) -> int:
        return self.accepted_shares + self.rejected_shares


@dataclass
class WalletState:
    last_share_at: datetime | None = None
    accepted_shares: int = 0
    rejected_shares: int = 0
    workers: dict[str, WorkerState] = field(default_factory=dict)
    accepted_windows: dict[str, WindowCounter] = field(default_factory=_new_window_counters)
    rejected_windows: dict[str, WindowCounter] = field(default_factory=_new_window_counters)

    @property
    def share_count(self) -> int:
        return self.accepted_shares + self.rejected_shares


class ActivityEngine:
    def __init__(
        self,
        *,
        assumed_share_difficulty: float = DEFAULT_ASSUMED_SHARE_DIFFICULTY,
    ) -> None:
        self.assumed_share_difficulty = assumed_share_difficulty
        self._wallets: dict[str, WalletState] = {}
        self._accepted_windows = _new_window_counters()
        self._rejected_windows = _new_window_counters()
        self._last_share_at: datetime | None = None
        self._sequence = 0

    @property
    def sequence(self) -> int:
        return self._sequence

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def restore_sequence(self, sequence: int) -> None:
        self._sequence = max(self._sequence, sequence)

    def ingest_event(
        self,
        event: ShareEvent,
        *,
        sequence: int | None = None,
        update_lifetime: bool = True,
    ) -> None:
        second = int(event.occurred_at.timestamp())
        wallet_state = self._wallets.setdefault(event.wallet, WalletState())
        worker_state = wallet_state.workers.setdefault(event.worker, WorkerState())

        wallet_state.last_share_at = _max_datetime(wallet_state.last_share_at, event.occurred_at)
        worker_state.last_share_at = _max_datetime(worker_state.last_share_at, event.occurred_at)
        self._last_share_at = _max_datetime(self._last_share_at, event.occurred_at)

        if event.accepted:
            self._accepted_windows = self._bump_counters(self._accepted_windows, second)
            wallet_state.accepted_windows = self._bump_counters(
                wallet_state.accepted_windows, second
            )
            worker_state.accepted_windows = self._bump_counters(
                worker_state.accepted_windows, second
            )
            if update_lifetime:
                wallet_state.accepted_shares += 1
                worker_state.accepted_shares += 1
        else:
            self._rejected_windows = self._bump_counters(self._rejected_windows, second)
            wallet_state.rejected_windows = self._bump_counters(
                wallet_state.rejected_windows, second
            )
            worker_state.rejected_windows = self._bump_counters(
                worker_state.rejected_windows, second
            )
            if update_lifetime:
                wallet_state.rejected_shares += 1
                worker_state.rejected_shares += 1

        if sequence is not None:
            self._sequence = max(self._sequence, sequence)

    def seed_from_snapshot(self, snapshot: dict[str, Any]) -> None:
        meta = snapshot.get("meta", {})
        miners = snapshot.get("miners", {})
        if not isinstance(meta, dict) or not isinstance(miners, dict):
            return

        sequence = meta.get("sequence")
        if isinstance(sequence, int):
            self._sequence = max(self._sequence, sequence)

        for wallet, payload in miners.items():
            if not isinstance(wallet, str) or not isinstance(payload, dict):
                continue

            summary = payload.get("summary", {})
            workers = payload.get("workers", [])
            if not isinstance(summary, dict) or not isinstance(workers, list):
                continue

            wallet_state = self._wallets.setdefault(wallet, WalletState())
            wallet_state.last_share_at = _parse_iso_datetime(summary.get("lastShareAt"))
            wallet_state.accepted_shares = _safe_int(summary.get("acceptedShares"))
            wallet_state.rejected_shares = _safe_int(summary.get("rejectedShares"))

            for worker_payload in workers:
                if not isinstance(worker_payload, dict):
                    continue
                worker_name = worker_payload.get("name")
                if not isinstance(worker_name, str) or not worker_name:
                    continue
                worker_state = wallet_state.workers.setdefault(worker_name, WorkerState())
                worker_state.last_share_at = _parse_iso_datetime(
                    worker_payload.get("lastShareAt")
                )
                worker_state.accepted_shares = _safe_int(
                    worker_payload.get("acceptedShares")
                )
                worker_state.rejected_shares = _safe_int(
                    worker_payload.get("rejectedShares")
                )

        self._last_share_at = _parse_iso_datetime(meta.get("lastShareAt"))

    def build_snapshot(
        self,
        *,
        now: datetime | None = None,
        activity_mode: str,
        activity_data_source: str,
        synthetic_job_mode: str,
        share_validation_mode: str,
        live_window_seconds: int = MAX_WINDOW_SECONDS,
        warning_count: int = 0,
        log_path: str | None = None,
        log_offset: int = 0,
        log_inode: int | None = None,
        window_replay_offset: int = 0,
        window_replay_sequence_floor: int = 0,
    ) -> dict[str, Any]:
        effective_now = now or utc_now()
        now_second = int(effective_now.timestamp())

        pool_rolling = self._build_rolling_payload(
            self._accepted_windows, self._rejected_windows, now_second
        )
        active_miners = 0
        active_workers = 0
        miners: dict[str, Any] = {}
        worker_distribution: list[dict[str, Any]] = []

        for wallet in sorted(self._wallets):
            wallet_state = self._wallets[wallet]
            worker_items: list[dict[str, Any]] = []
            wallet_active_workers = 0

            for worker_name in sorted(wallet_state.workers):
                worker_state = wallet_state.workers[worker_name]
                rolling = self._build_rolling_payload(
                    worker_state.accepted_windows,
                    worker_state.rejected_windows,
                    now_second,
                )
                is_active = rolling["15m"]["shareCount"] > 0
                if is_active:
                    active_workers += 1
                    wallet_active_workers += 1

                worker_items.append(
                    {
                        "name": worker_name,
                        "hashrate": rolling[HEADLINE_WINDOW_LABEL]["hashrate"],
                        "lastShareAt": isoformat(worker_state.last_share_at),
                        "acceptedShares": worker_state.accepted_shares,
                        "rejectedShares": worker_state.rejected_shares,
                        "shareCount": worker_state.share_count,
                        "rolling": rolling,
                    }
                )

            wallet_rolling = self._build_rolling_payload(
                wallet_state.accepted_windows,
                wallet_state.rejected_windows,
                now_second,
            )
            if wallet_rolling["15m"]["shareCount"] > 0:
                active_miners += 1

            worker_distribution.append(
                {
                    "wallet": wallet,
                    "workers": len(wallet_state.workers),
                    "activeWorkers": wallet_active_workers,
                    "shares15m": wallet_rolling["15m"]["shareCount"],
                    "hashrate": wallet_rolling[HEADLINE_WINDOW_LABEL]["hashrate"],
                }
            )

            miners[wallet] = {
                "summary": {
                    "hashrate": wallet_rolling[HEADLINE_WINDOW_LABEL]["hashrate"],
                    "pendingBalance": None,
                    "totalPaid": None,
                    "lastShareAt": isoformat(wallet_state.last_share_at),
                    "acceptedShares": wallet_state.accepted_shares,
                    "rejectedShares": wallet_state.rejected_shares,
                    "shareCount": wallet_state.share_count,
                    "activeWorkers": wallet_active_workers,
                    "rolling": wallet_rolling,
                },
                "workers": worker_items,
                "payments": [],
            }

        worker_distribution.sort(
            key=lambda item: (-item["shares15m"], item["wallet"])
        )

        data_status = "empty"
        if self._last_share_at is not None:
            data_status = (
                "live"
                if (effective_now - self._last_share_at).total_seconds()
                <= live_window_seconds
                else "stale"
            )

        meta: dict[str, Any] = {
            "schemaVersion": "1.0",
            "activityMode": activity_mode,
            "activityDataSource": activity_data_source,
            "activityDerivedFromShares": True,
            "blockchainVerified": False,
            "syntheticJobMode": synthetic_job_mode,
            "shareValidationMode": share_validation_mode,
            "hashratePolicy": "share-rate-assumed-diff",
            "assumedShareDifficulty": self.assumed_share_difficulty,
            "windowSeconds": [seconds for _label, seconds in WINDOW_DEFINITIONS],
            "lastShareAt": isoformat(self._last_share_at),
            "warningCount": warning_count,
            "sequence": self._sequence,
            "logPath": log_path,
            "logOffset": log_offset,
            "logInode": log_inode,
            "windowReplayOffset": window_replay_offset,
            "windowReplaySequenceFloor": window_replay_sequence_floor,
            "dataStatus": data_status,
        }

        return {
            "generatedAt": isoformat(effective_now),
            "meta": meta,
            "pool": {
                "poolHashrate": pool_rolling[HEADLINE_WINDOW_LABEL]["hashrate"],
                "activeMiners": active_miners,
                "activeWorkers": active_workers,
                "workerDistribution": worker_distribution,
                "rolling": pool_rolling,
            },
            "miners": miners,
        }

    def _build_rolling_payload(
        self,
        accepted_windows: dict[str, WindowCounter],
        rejected_windows: dict[str, WindowCounter],
        now_second: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for label, window_seconds in WINDOW_DEFINITIONS:
            accepted = accepted_windows[label].total(now_second)
            rejected = rejected_windows[label].total(now_second)
            payload[label] = {
                "windowSeconds": window_seconds,
                "shareCount": accepted + rejected,
                "acceptedShares": accepted,
                "rejectedShares": rejected,
                "hashrate": self._hashrate_for_window(accepted, window_seconds),
            }
        return payload

    def _bump_counters(
        self, counters: dict[str, WindowCounter], second: int
    ) -> dict[str, WindowCounter]:
        for label in WINDOW_SECONDS:
            counters[label].increment(second, 1)
        return counters

    def _hashrate_for_window(
        self, accepted_shares: int, window_seconds: int
    ) -> float | None:
        if accepted_shares <= 0 or window_seconds <= 0:
            return None
        shares_per_second = accepted_shares / float(window_seconds)
        return shares_per_second * self.assumed_share_difficulty * HASHES_PER_SHARE


def _max_datetime(left: datetime | None, right: datetime) -> datetime:
    if left is None or right > left:
        return right
    return left


def _parse_iso_datetime(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def _safe_int(raw_value: Any) -> int:
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    return 0

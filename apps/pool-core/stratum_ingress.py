from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from activity_engine import ActivityEngine
from activity_ingest import ShareEvent, ShareEventLoadError, read_share_event_records
from activity_log import discover_log_segments, prune_rotated_logs, rotated_log_path
from config import PoolCoreConfig, load_config
from runtime_io import write_json_atomic
from stratum_protocol import (
    ConnectionState,
    StratumProtocolError,
    authorize_identity,
    difficulty_notification,
    error_response,
    new_connection_state,
    notify_notification,
    parse_request,
    resolve_submit_identity,
    subscribe_result,
    success_response,
)


LOGGER = logging.getLogger("pepepow.stratum_ingress")
APPEND_FLUSH_INTERVAL_SECONDS = 0.1
APPEND_BATCH_SIZE = 500
SYNTHETIC_JOB_MODE = "synthetic-stratum-v1"
SHARE_VALIDATION_MODE = "none"
SYNTHETIC_PREVHASH = "0" * 64
SYNTHETIC_COINB1 = "0100000001"
SYNTHETIC_COINB2 = "ffffffff"
SYNTHETIC_VERSION = "20000000"
SYNTHETIC_NBITS = "1d00ffff"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ShareEnvelope:
    sequence: int
    event: ShareEvent
    remote_address: str
    payload: dict[str, Any]

    @property
    def serialized(self) -> str:
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class DispatchResult:
    response: dict[str, Any]
    notifications: list[dict[str, Any]] = field(default_factory=list)
    start_notify_loop: bool = False


@dataclass
class SessionStats:
    accepted_share_count: int = 0
    first_share_at: datetime | None = None
    last_share_at: datetime | None = None
    last_submitted_job_id: str | None = None
    unexpected_job_status_warning_emitted: bool = False


class RecoveryTracker:
    def __init__(self) -> None:
        self.current_offset = 0
        self.log_inode: int | None = None
        self.current_sequence = 0
        self._window_sequences: deque[tuple[int, int]] = deque()

    @property
    def window_replay_sequence_floor(self) -> int:
        self._trim(int(utc_now().timestamp()))
        if self._window_sequences:
            return self._window_sequences[0][1]
        if self.current_sequence > 0:
            return self.current_sequence + 1
        return 0

    @property
    def window_replay_offset(self) -> int:
        return self.current_offset

    def restore(self, *, sequence: int) -> None:
        self.current_sequence = max(self.current_sequence, sequence)

    def record(self, occurred_at_second: int, sequence: int) -> None:
        if sequence <= 0:
            return

        self.current_sequence = max(self.current_sequence, sequence)
        if (
            not self._window_sequences
            or self._window_sequences[-1][0] != occurred_at_second
        ):
            self._window_sequences.append((occurred_at_second, sequence))

        self._trim(occurred_at_second)

    def _trim(self, occurred_at_second: int) -> None:
        cutoff = occurred_at_second - 900
        while self._window_sequences and self._window_sequences[0][0] <= cutoff:
            self._window_sequences.popleft()


class StratumIngressService:
    def __init__(self, config: PoolCoreConfig) -> None:
        self._config = config
        self._engine = ActivityEngine(
            assumed_share_difficulty=config.hashrate_assumed_share_difficulty
        )
        self._queue: asyncio.Queue[ShareEnvelope] = asyncio.Queue(
            maxsize=config.stratum_queue_maxsize
        )
        self._state_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None
        self._append_task: asyncio.Task[None] | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self._recovery = RecoveryTracker()
        self._warning_count = 0
        self._dirty_snapshot = False
        self._job_counter = 0
        self._active_log_first_sequence: int | None = None
        self._active_log_last_sequence: int | None = None
        self._client_writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        await self._bootstrap_state()
        self._append_task = asyncio.create_task(self._append_loop(), name="append-loop")
        self._snapshot_task = asyncio.create_task(
            self._snapshot_loop(), name="activity-snapshot-loop"
        )
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._config.stratum_bind_host,
            port=self._config.stratum_bind_port,
        )
        sockets = self._server.sockets or []
        endpoints = ", ".join(
            str(socket.getsockname()) for socket in sockets
        ) or f"{self._config.stratum_bind_host}:{self._config.stratum_bind_port}"
        LOGGER.info("Stratum ingress listening on %s", endpoints)

    async def run(self) -> None:
        await self.start()
        assert self._server is not None

        async with self._server:
            await self._stop_event.wait()

        await self.stop()

    async def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

        client_writers = list(self._client_writers)
        for writer in client_writers:
            writer.close()
        if client_writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in client_writers),
                return_exceptions=True,
            )

        if self._append_task is not None:
            await self._append_task

        if self._snapshot_task is not None:
            await self._snapshot_task

    async def _bootstrap_state(self) -> None:
        previous_snapshot = self._load_previous_activity_snapshot()
        snapshot_sequence = 0
        replay_sequence_floor = 0
        seeded_from_snapshot = False

        if previous_snapshot is not None:
            meta = previous_snapshot.get("meta", {})
            if isinstance(meta, dict):
                snapshot_sequence = _safe_int(meta.get("sequence"))
                replay_sequence_floor = _safe_int(
                    meta.get("windowReplaySequenceFloor")
                )
                self._engine.seed_from_snapshot(previous_snapshot)
                self._engine.restore_sequence(snapshot_sequence)
                self._recovery.restore(sequence=snapshot_sequence)
                seeded_from_snapshot = True

        segments = discover_log_segments(self._config.activity_log_path)
        earliest_replayed_sequence: int | None = None

        for segment in self._select_replay_segments(segments, replay_sequence_floor):
            try:
                records, warnings = read_share_event_records(segment.path)
            except ShareEventLoadError as exc:
                LOGGER.warning("Unable to replay share log segment %s: %s", segment.path, exc)
                self._warning_count += 1
                continue

            self._warning_count += len(warnings)
            first_sequence_in_segment: int | None = None
            last_sequence_in_segment: int | None = None

            for record in records:
                if record.sequence > 0:
                    if first_sequence_in_segment is None:
                        first_sequence_in_segment = record.sequence
                    last_sequence_in_segment = record.sequence

                if replay_sequence_floor > 0 and 0 < record.sequence < replay_sequence_floor:
                    continue

                if record.sequence > 0:
                    if (
                        earliest_replayed_sequence is None
                        or record.sequence < earliest_replayed_sequence
                    ):
                        earliest_replayed_sequence = record.sequence

                update_lifetime = (
                    not seeded_from_snapshot
                    or record.sequence <= 0
                    or record.sequence > snapshot_sequence
                )
                self._engine.ingest_event(
                    record.event,
                    sequence=record.sequence if record.sequence > 0 else None,
                    update_lifetime=update_lifetime,
                )
                self._recovery.record(
                    int(record.event.occurred_at.timestamp()),
                    record.sequence,
                )

            if segment.active:
                self._active_log_first_sequence = first_sequence_in_segment
                self._active_log_last_sequence = last_sequence_in_segment
                if segment.path.exists():
                    stat = segment.path.stat()
                    self._recovery.current_offset = stat.st_size
                    self._recovery.log_inode = stat.st_ino

            if records or warnings:
                self._dirty_snapshot = True

        if (
            seeded_from_snapshot
            and replay_sequence_floor > 0
            and earliest_replayed_sequence is not None
            and earliest_replayed_sequence > replay_sequence_floor
        ):
            self._warning_count += 1
            LOGGER.warning(
                "Replay coverage truncated by retention: wanted sequence %s but earliest replayed was %s",
                replay_sequence_floor,
                earliest_replayed_sequence,
            )

        if self._dirty_snapshot or self._warning_count:
            await self._write_activity_snapshot(force=True)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        state = new_connection_state()
        session_stats = SessionStats()
        remote_address = _format_peer(writer.get_extra_info("peername"))
        send_lock = asyncio.Lock()
        notify_task: asyncio.Task[None] | None = None
        self._client_writers.add(writer)
        LOGGER.info(
            "Miner connected: remote=%s session=%s",
            remote_address,
            state.session_id,
        )

        try:
            while not reader.at_eof():
                raw_line = await reader.readline()
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                dispatch = await self._dispatch_line(
                    line,
                    state,
                    remote_address,
                    session_stats,
                )
                await self._send_message(writer, send_lock, dispatch.response)
                for message in dispatch.notifications:
                    await self._send_message(writer, send_lock, message)

                if dispatch.start_notify_loop and notify_task is None:
                    notify_task = asyncio.create_task(
                        self._notify_loop(state, writer, send_lock),
                        name=f"synthetic-notify-{state.session_id}",
                    )
        except ConnectionError:
            LOGGER.debug("Miner disconnected: %s", remote_address)
        finally:
            if notify_task is not None:
                notify_task.cancel()
                with suppress(asyncio.CancelledError):
                    await notify_task
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            self._client_writers.discard(writer)
            LOGGER.info(
                "Miner disconnected: remote=%s session=%s acceptedShares=%s firstShareAt=%s lastShareAt=%s lastJobId=%s",
                remote_address,
                state.session_id,
                session_stats.accepted_share_count,
                _isoformat_or_none(session_stats.first_share_at),
                _isoformat_or_none(session_stats.last_share_at),
                session_stats.last_submitted_job_id,
            )

    async def _dispatch_line(
        self,
        line: str,
        state: ConnectionState,
        remote_address: str,
        session_stats: SessionStats,
    ) -> DispatchResult:
        try:
            request = parse_request(line)
        except StratumProtocolError as exc:
            return DispatchResult(error_response(None, exc.code, exc.message))

        if request.method == "mining.subscribe":
            return DispatchResult(
                success_response(request.request_id, subscribe_result(state))
            )

        if request.method == "mining.extranonce.subscribe":
            return DispatchResult(success_response(request.request_id, True))

        if request.method == "mining.authorize":
            login = request.params[0] if request.params else None
            wallet, worker, normalized_login = authorize_identity(
                login if isinstance(login, str) else None
            )
            state.authorized = True
            state.authorized_login = normalized_login
            state.authorized_wallet = wallet
            state.authorized_worker = worker
            LOGGER.info(
                "Miner authorized: session=%s wallet=%s worker=%s login=%s",
                state.session_id,
                wallet,
                worker,
                normalized_login,
            )

            notifications: list[dict[str, Any]] = []
            desired_difficulty = self._synthetic_difficulty()
            if state.current_difficulty != desired_difficulty:
                state.current_difficulty = desired_difficulty
                notifications.append(difficulty_notification(desired_difficulty))
                LOGGER.info(
                    "Difficulty sent: session=%s difficulty=%s",
                    state.session_id,
                    desired_difficulty,
                )
            notify_message = self._new_notify_message(state)
            LOGGER.info(
                "Notify sent: session=%s jobId=%s previousJobId=%s cleanJobs=%s",
                state.session_id,
                state.current_job_id,
                state.previous_job_id,
                notify_message["params"][8],
            )
            notifications.append(notify_message)

            return DispatchResult(
                success_response(request.request_id, True),
                notifications=notifications,
                start_notify_loop=True,
            )

        if request.method == "mining.submit":
            wallet, worker, login = resolve_submit_identity(request.params, state)
            sequence = self._engine.next_sequence()
            observed_at = utc_now()
            submit_job_id = _extract_submit_job_id(request.params)
            job_status = _classify_submit_job_id(
                submit_job_id,
                current_job_id=state.current_job_id,
                previous_job_id=state.previous_job_id,
            )
            session_stats.accepted_share_count += 1
            session_stats.last_submitted_job_id = submit_job_id
            session_stats.last_share_at = observed_at
            if session_stats.first_share_at is None:
                session_stats.first_share_at = observed_at
                LOGGER.info(
                    "First accepted share: session=%s wallet=%s worker=%s jobId=%s jobStatus=%s",
                    state.session_id,
                    wallet,
                    worker,
                    submit_job_id,
                    job_status,
                )
            if (
                job_status == "unexpected"
                and not session_stats.unexpected_job_status_warning_emitted
            ):
                LOGGER.warning(
                    "Unexpected job id accepted in synthetic mode: session=%s remote=%s submittedJobId=%s currentJobId=%s previousJobId=%s",
                    state.session_id,
                    remote_address,
                    submit_job_id,
                    state.current_job_id,
                    state.previous_job_id,
                )
                session_stats.unexpected_job_status_warning_emitted = True
            LOGGER.info(
                "Submit received: session=%s shareCount=%s submittedJobId=%s currentJobId=%s previousJobId=%s jobStatus=%s",
                state.session_id,
                session_stats.accepted_share_count,
                submit_job_id,
                state.current_job_id,
                state.previous_job_id,
                job_status,
            )
            event = ShareEvent(
                wallet=wallet,
                worker=worker,
                occurred_at=observed_at,
                accepted=True,
            )
            payload = {
                "timestamp": observed_at.replace(microsecond=0)
                .astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "wallet": wallet,
                "worker": worker,
                "login": login,
                "accepted": True,
                "status": "accepted",
                "source": "stratum",
                "remoteAddress": remote_address,
                "sessionId": state.session_id,
                "sequence": sequence,
                "jobId": submit_job_id,
                "jobStatus": job_status,
                "difficulty": state.current_difficulty or self._synthetic_difficulty(),
                "syntheticWork": True,
                "blockchainVerified": False,
                "shareValidationMode": SHARE_VALIDATION_MODE,
                "submit": request.params,
            }
            envelope = ShareEnvelope(
                sequence=sequence,
                event=event,
                remote_address=remote_address,
                payload=payload,
            )
            try:
                self._queue.put_nowait(envelope)
            except asyncio.QueueFull:
                await self._queue.put(envelope)
            return DispatchResult(success_response(request.request_id, True))

        return DispatchResult(
            error_response(request.request_id, -32601, "Method not found")
        )

    async def _notify_loop(
        self,
        state: ConnectionState,
        writer: asyncio.StreamWriter,
        send_lock: asyncio.Lock,
    ) -> None:
        while not self._stop_event.is_set() and not writer.is_closing():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.synthetic_job_interval_seconds,
                )
            except asyncio.TimeoutError:
                if not state.authorized:
                    continue
                try:
                    notify_message = self._new_notify_message(state)
                    LOGGER.info(
                        "Notify sent: session=%s jobId=%s previousJobId=%s cleanJobs=%s",
                        state.session_id,
                        state.current_job_id,
                        state.previous_job_id,
                        notify_message["params"][8],
                    )
                    await self._send_message(
                        writer,
                        send_lock,
                        notify_message,
                    )
                except ConnectionError:
                    return

    async def _send_message(
        self,
        writer: asyncio.StreamWriter,
        send_lock: asyncio.Lock,
        payload: dict[str, Any],
    ) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        async with send_lock:
            writer.write(encoded)
            await writer.drain()

    async def _append_loop(self) -> None:
        log_path = self._config.activity_log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("ab")

        try:
            handle.seek(0, os.SEEK_END)
            current_offset = handle.tell()
            self._recovery.current_offset = max(self._recovery.current_offset, current_offset)
            self._recovery.log_inode = os.fstat(handle.fileno()).st_ino
            active_first_sequence = self._active_log_first_sequence
            active_last_sequence = self._active_log_last_sequence

            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    first = await asyncio.wait_for(
                        self._queue.get(), timeout=APPEND_FLUSH_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    continue

                batch = [first]
                deadline = asyncio.get_running_loop().time() + APPEND_FLUSH_INTERVAL_SECONDS
                while len(batch) < APPEND_BATCH_SIZE:
                    timeout = deadline - asyncio.get_running_loop().time()
                    if timeout <= 0:
                        break
                    try:
                        batch.append(await asyncio.wait_for(self._queue.get(), timeout=timeout))
                    except asyncio.TimeoutError:
                        break

                appended: list[tuple[int, ShareEnvelope]] = []
                for item in batch:
                    if active_first_sequence is None:
                        active_first_sequence = item.sequence
                    active_last_sequence = item.sequence
                    encoded = item.serialized.encode("utf-8") + b"\n"
                    handle.write(encoded)
                    current_offset += len(encoded)
                    appended.append((int(item.event.occurred_at.timestamp()), item))

                handle.flush()
                os.fsync(handle.fileno())

                if (
                    current_offset >= self._config.activity_log_rotate_bytes
                    and active_first_sequence is not None
                    and active_last_sequence is not None
                ):
                    rotated_path = rotated_log_path(
                        log_path,
                        active_first_sequence,
                        active_last_sequence,
                    )
                    handle.close()
                    os.replace(log_path, rotated_path)
                    removed_logs = prune_rotated_logs(
                        log_path,
                        self._config.activity_log_retention_files,
                    )
                    for removed_log in removed_logs:
                        LOGGER.info("Pruned rotated share log %s", removed_log.name)
                    LOGGER.info("Rotated share log to %s", rotated_path.name)
                    handle = log_path.open("ab")
                    current_offset = handle.tell()
                    active_first_sequence = None
                    active_last_sequence = None

                async with self._state_lock:
                    self._active_log_first_sequence = active_first_sequence
                    self._active_log_last_sequence = active_last_sequence
                    self._recovery.current_offset = current_offset
                    self._recovery.log_inode = os.fstat(handle.fileno()).st_ino
                    for occurred_at_second, item in appended:
                        self._recovery.record(occurred_at_second, item.sequence)
                        self._engine.ingest_event(
                            item.event,
                            sequence=item.sequence,
                            update_lifetime=True,
                        )
                    self._dirty_snapshot = True

                for _item in batch:
                    self._queue.task_done()
        finally:
            handle.close()

        await self._write_activity_snapshot(force=True)

    async def _snapshot_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.activity_snapshot_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            await self._write_activity_snapshot()

        await self._write_activity_snapshot(force=True)

    async def _write_activity_snapshot(self, *, force: bool = False) -> None:
        async with self._state_lock:
            if not force and not self._dirty_snapshot:
                return

            snapshot = self._engine.build_snapshot(
                now=utc_now(),
                activity_mode="stratum-share-ingest",
                activity_data_source="stratum-jsonl-share-log",
                synthetic_job_mode=SYNTHETIC_JOB_MODE,
                share_validation_mode=SHARE_VALIDATION_MODE,
                live_window_seconds=self._config.activity_window_seconds,
                warning_count=self._warning_count,
                log_path=str(self._config.activity_log_path),
                log_offset=self._recovery.current_offset,
                log_inode=self._recovery.log_inode,
                window_replay_offset=self._recovery.window_replay_offset,
                window_replay_sequence_floor=self._recovery.window_replay_sequence_floor,
            )
            snapshot_sequence = _safe_int(snapshot["meta"].get("sequence"))
            snapshot_offset = _safe_int(snapshot["meta"].get("logOffset"))

        try:
            write_json_atomic(snapshot, self._config.activity_snapshot_output_path)
        except OSError:
            LOGGER.exception(
                "Failed to write activity snapshot to %s",
                self._config.activity_snapshot_output_path,
            )
            return

        async with self._state_lock:
            if (
                self._engine.sequence <= snapshot_sequence
                and self._recovery.current_offset <= snapshot_offset
            ):
                self._dirty_snapshot = False

    def _new_notify_message(self, state: ConnectionState) -> dict[str, Any]:
        self._job_counter += 1
        state.previous_job_id = state.current_job_id
        state.current_job_id = f"job-{self._job_counter:016x}"
        return notify_notification(
            job_id=state.current_job_id,
            prevhash=SYNTHETIC_PREVHASH,
            coinb1=SYNTHETIC_COINB1,
            coinb2=SYNTHETIC_COINB2,
            merkle_branch=[],
            version=SYNTHETIC_VERSION,
            nbits=SYNTHETIC_NBITS,
            ntime=f"{int(utc_now().timestamp()):08x}",
            clean_jobs=True,
        )

    def _select_replay_segments(self, segments: list[Any], sequence_floor: int) -> list[Any]:
        if sequence_floor <= 0:
            return segments

        selected = []
        for segment in segments:
            if segment.active or segment.last_sequence is None:
                selected.append(segment)
                continue
            if segment.last_sequence >= sequence_floor:
                selected.append(segment)
        return selected

    def _synthetic_difficulty(self) -> float:
        return self._config.hashrate_assumed_share_difficulty

    def _load_previous_activity_snapshot(self) -> dict[str, Any] | None:
        path = self._config.activity_snapshot_output_path
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        return payload if isinstance(payload, dict) else None


def _extract_submit_job_id(params: list[Any]) -> str | None:
    if len(params) >= 2 and isinstance(params[1], str) and params[1].strip():
        return params[1].strip()
    return None


def _classify_submit_job_id(
    submit_job_id: str | None,
    *,
    current_job_id: str | None,
    previous_job_id: str | None,
) -> str:
    if submit_job_id is None:
        return "missing"
    if current_job_id is not None and submit_job_id == current_job_id:
        return "current"
    if previous_job_id is not None and submit_job_id == previous_job_id:
        return "previous"
    return "unexpected"


def _format_peer(peer: Any) -> str:
    if isinstance(peer, tuple) and len(peer) >= 2:
        return f"{peer[0]}:{peer[1]}"
    return str(peer or "unknown")


def _isoformat_or_none(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _safe_int(raw_value: Any) -> int:
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    return 0


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _run() -> None:
    config = load_config()
    service = StratumIngressService(config)
    loop = asyncio.get_running_loop()

    for signame in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signame, None)
        if signum is None:
            continue
        try:
            loop.add_signal_handler(signum, service._stop_event.set)
        except NotImplementedError:
            signal.signal(signum, lambda _signum, _frame: service._stop_event.set())

    await service.run()


def main() -> int:
    configure_logging()
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

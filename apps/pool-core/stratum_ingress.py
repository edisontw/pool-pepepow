from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
from collections import OrderedDict, deque
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
from pepepow_pow import PepepowPowError, blake3_hash, hoohash_v110
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
from template_jobs import TemplateJobManager


LOGGER = logging.getLogger("pepepow.stratum_ingress")
APPEND_FLUSH_INTERVAL_SECONDS = 0.1
APPEND_BATCH_SIZE = 500
SYNTHETIC_JOB_MODE = "synthetic-stratum-v1"
SHARE_VALIDATION_MODE = "structural-skeleton"
SHARE_HASH_VALIDATION_MODE = "hoohashv110-pepew-header80"
SYNTHETIC_PREVHASH = "0" * 64
SYNTHETIC_COINB1 = "0100000001"
SYNTHETIC_COINB2 = "ffffffff"
SYNTHETIC_VERSION = "20000000"
SYNTHETIC_NBITS = "1d00ffff"
SUBMIT_DUPLICATE_WINDOW_SECONDS = 900
REJECT_LOG_SUPPRESS_REASONS = frozenset({"unknown-job", "stale-job"})
INTERNAL_JOB_ID_PATTERN = re.compile(r"^job-([0-9a-f]{16})$")
HEX_STRING_PATTERN = re.compile(r"^[0-9a-fA-F]+$")


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
    rejected_share_count: int = 0
    first_share_at: datetime | None = None
    last_share_at: datetime | None = None
    last_submitted_job_id: str | None = None
    reject_log_key: tuple[Any, ...] | None = None
    suppressed_reject_logs: int = 0
    reject_log_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubmitAssessment:
    job_status: str
    submit_job_id: str | None
    cached_job: Any | None
    accepted: bool
    reject_reason: str | None = None
    detail: str | None = None
    duplicate_submit: bool = False
    target_validation_status: str | None = None
    candidate_possible: bool = False
    share_hash_validation_status: str | None = None
    share_hash_valid: bool | None = None


@dataclass(frozen=True)
class TargetContextCheck:
    status: str | None
    reject_reason: str | None
    detail: str | None = None
    candidate_possible: bool = False


@dataclass(frozen=True)
class ShareHashCheck:
    status: str | None
    reject_reason: str | None
    detail: str | None = None
    valid: bool | None = None


@dataclass(frozen=True)
class ShareHeaderPreimage:
    status: str
    reject_reason: str | None
    detail: str | None = None
    header: bytes | None = None


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
    def __init__(
        self,
        config: PoolCoreConfig,
        *,
        rpc_client: Any | None = None,
    ) -> None:
        self._config = config
        self._engine = ActivityEngine(
            assumed_share_difficulty=config.hashrate_assumed_share_difficulty
        )
        self._job_manager = TemplateJobManager(config, rpc_client=rpc_client)
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
        self._duplicate_submit_cache_size = max(
            512, config.template_job_cache_size * 64
        )
        self._submit_fingerprints: OrderedDict[str, datetime] = OrderedDict()
        self._submit_validation_counts: dict[str, Any] = {
            "mode": "structural-skeleton",
            "accepted": 0,
            "rejected": 0,
            "duplicateWindowSize": self._duplicate_submit_cache_size,
            "candidatePossibleCount": 0,
            "shareHashValidationMode": SHARE_HASH_VALIDATION_MODE,
            "classificationCounts": {
                "current": 0,
                "previous": 0,
                "stale": 0,
                "unknown": 0,
                "malformed": 0,
            },
            "rejectReasonCounts": {},
            "targetValidationCounts": {
                "candidate-possible": 0,
                "target-context-missing": 0,
                "target-context-mismatch": 0,
            },
            "shareHashValidationCounts": {
                "share-hash-valid": 0,
                "share-hash-invalid": 0,
                "preimage-missing": 0,
                "preimage-mismatch": 0,
            },
        }

    async def start(self) -> None:
        await self._bootstrap_state()
        await self._job_manager.start()
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

        await self._job_manager.stop()

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
            self._flush_reject_log_summary(
                session_id=state.session_id,
                remote_address=remote_address,
                session_stats=session_stats,
            )
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            self._client_writers.discard(writer)
            LOGGER.info(
                "Miner disconnected: remote=%s session=%s acceptedShares=%s rejectedShares=%s firstShareAt=%s lastShareAt=%s lastJobId=%s",
                remote_address,
                state.session_id,
                session_stats.accepted_share_count,
                session_stats.rejected_share_count,
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
            assessment = self._assess_submit(
                request.params,
                state=state,
                login=login,
                observed_at=observed_at,
            )
            submit_job_id = assessment.submit_job_id
            cached_job = assessment.cached_job
            session_stats.last_submitted_job_id = submit_job_id
            session_stats.last_share_at = observed_at
            if session_stats.first_share_at is None:
                session_stats.first_share_at = observed_at
            if assessment.accepted:
                session_stats.accepted_share_count += 1
                if session_stats.accepted_share_count == 1:
                    LOGGER.info(
                        "First accepted share: session=%s wallet=%s worker=%s jobId=%s jobStatus=%s",
                        state.session_id,
                        wallet,
                        worker,
                        submit_job_id,
                        assessment.job_status,
                    )
            else:
                session_stats.rejected_share_count += 1

            self._record_submit_validation(assessment)
            self._log_submit_outcome(
                session_id=state.session_id,
                remote_address=remote_address,
                share_count=(
                    session_stats.accepted_share_count
                    if assessment.accepted
                    else session_stats.rejected_share_count
                ),
                submit_job_id=submit_job_id,
                current_job_id=state.current_job_id,
                previous_job_id=state.previous_job_id,
                assessment=assessment,
                session_stats=session_stats,
            )
            event = ShareEvent(
                wallet=wallet,
                worker=worker,
                occurred_at=observed_at,
                accepted=assessment.accepted,
            )
            payload = {
                "timestamp": observed_at.replace(microsecond=0)
                .astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "wallet": wallet,
                "worker": worker,
                "login": login,
                "accepted": assessment.accepted,
                "status": "accepted" if assessment.accepted else "rejected",
                "source": "stratum",
                "remoteAddress": remote_address,
                "sessionId": state.session_id,
                "sequence": sequence,
                "jobId": submit_job_id,
                "jobStatus": assessment.job_status,
                "difficulty": state.current_difficulty or self._synthetic_difficulty(),
                "syntheticWork": cached_job is None or cached_job.source == "synthetic",
                "blockchainVerified": False,
                "shareValidationMode": SHARE_VALIDATION_MODE,
                "rejectReason": assessment.reject_reason,
                "rejectDetail": assessment.detail,
                "duplicateSubmit": assessment.duplicate_submit,
                "targetValidationStatus": assessment.target_validation_status,
                "candidatePossible": assessment.candidate_possible,
                "shareHashValidationStatus": assessment.share_hash_validation_status,
                "shareHashValid": assessment.share_hash_valid,
                "jobSource": cached_job.source if cached_job is not None else None,
                "templateAnchor": (
                    cached_job.template_anchor if cached_job is not None else None
                ),
                "targetContext": (
                    cached_job.target_context if cached_job is not None else None
                ),
                "preimageContext": (
                    cached_job.preimage_context if cached_job is not None else None
                ),
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
            return DispatchResult(
                success_response(request.request_id, assessment.accepted)
            )

        return DispatchResult(
            error_response(request.request_id, -32601, "Method not found")
        )

    def _assess_submit(
        self,
        params: list[Any],
        *,
        state: ConnectionState,
        login: str,
        observed_at: datetime,
    ) -> SubmitAssessment:
        malformed_detail = _validate_submit_params(params)
        if malformed_detail is not None:
            return SubmitAssessment(
                job_status="malformed",
                submit_job_id=_extract_submit_job_id(params),
                cached_job=None,
                accepted=False,
                reject_reason="malformed-submit",
                detail=malformed_detail,
            )

        submit_job_id = _extract_submit_job_id(params)
        cached_job = self._job_manager.get_job(submit_job_id, now=observed_at)
        job_status = _classify_submit_job_id(
            submit_job_id,
            current_job_id=state.current_job_id,
            previous_job_id=state.previous_job_id,
            cached_job=cached_job,
            is_stale_job=self._job_manager.is_stale_job(
                submit_job_id, now=observed_at
            ),
        )
        if job_status == "unknown":
            return SubmitAssessment(
                job_status=job_status,
                submit_job_id=submit_job_id,
                cached_job=cached_job,
                accepted=False,
                reject_reason="unknown-job",
                detail=_restart_backlog_unknown_detail(
                    submit_job_id,
                    current_job_id=state.current_job_id,
                    previous_job_id=state.previous_job_id,
                ),
            )
        if job_status == "stale":
            return SubmitAssessment(
                job_status=job_status,
                submit_job_id=submit_job_id,
                cached_job=cached_job,
                accepted=False,
                reject_reason="stale-job",
            )

        target_context_check = self._assess_target_context(
            params,
            cached_job=cached_job,
        )
        if target_context_check.reject_reason is not None:
            return SubmitAssessment(
                job_status=job_status,
                submit_job_id=submit_job_id,
                cached_job=cached_job,
                accepted=False,
                reject_reason=target_context_check.reject_reason,
                detail=target_context_check.detail,
                target_validation_status=target_context_check.status,
            )

        share_hash_check = self._assess_share_hash(
            params,
            state=state,
            cached_job=cached_job,
            target_context_check=target_context_check,
        )
        if share_hash_check.reject_reason is not None:
            return SubmitAssessment(
                job_status=job_status,
                submit_job_id=submit_job_id,
                cached_job=cached_job,
                accepted=False,
                reject_reason=share_hash_check.reject_reason,
                detail=share_hash_check.detail,
                target_validation_status=target_context_check.status,
                candidate_possible=target_context_check.candidate_possible,
                share_hash_validation_status=share_hash_check.status,
                share_hash_valid=share_hash_check.valid,
            )

        fingerprint = _submit_fingerprint(login, params)
        if self._is_duplicate_submit(fingerprint, observed_at):
            return SubmitAssessment(
                job_status=job_status,
                submit_job_id=submit_job_id,
                cached_job=cached_job,
                accepted=False,
                reject_reason="duplicate-submit",
                duplicate_submit=True,
                target_validation_status=target_context_check.status,
                candidate_possible=target_context_check.candidate_possible,
                share_hash_validation_status=share_hash_check.status,
                share_hash_valid=share_hash_check.valid,
            )

        self._remember_submit_fingerprint(fingerprint, observed_at)
        return SubmitAssessment(
            job_status=job_status,
            submit_job_id=submit_job_id,
            cached_job=cached_job,
            accepted=True,
            target_validation_status=target_context_check.status,
            candidate_possible=target_context_check.candidate_possible,
            share_hash_validation_status=share_hash_check.status,
            share_hash_valid=share_hash_check.valid,
        )

    def _log_submit_outcome(
        self,
        *,
        session_id: str,
        remote_address: str,
        share_count: int,
        submit_job_id: str | None,
        current_job_id: str | None,
        previous_job_id: str | None,
        assessment: SubmitAssessment,
        session_stats: SessionStats,
    ) -> None:
        if assessment.accepted:
            self._flush_reject_log_summary(
                session_id=session_id,
                remote_address=remote_address,
                session_stats=session_stats,
            )
            LOGGER.info(
                "Submit accepted: session=%s shareCount=%s submittedJobId=%s currentJobId=%s previousJobId=%s jobStatus=%s",
                session_id,
                share_count,
                submit_job_id,
                current_job_id,
                previous_job_id,
                assessment.job_status,
            )
            return

        if self._should_suppress_reject_log(assessment):
            reject_key = (
                assessment.reject_reason,
                assessment.job_status,
                submit_job_id,
                current_job_id,
                previous_job_id,
                assessment.detail,
            )
            if session_stats.reject_log_key == reject_key:
                session_stats.suppressed_reject_logs += 1
                return

            self._flush_reject_log_summary(
                session_id=session_id,
                remote_address=remote_address,
                session_stats=session_stats,
            )
            session_stats.reject_log_key = reject_key
            session_stats.reject_log_context = {
                "submitJobId": submit_job_id,
                "currentJobId": current_job_id,
                "previousJobId": previous_job_id,
                "jobStatus": assessment.job_status,
                "rejectReason": assessment.reject_reason,
                "detail": assessment.detail,
            }
        else:
            self._flush_reject_log_summary(
                session_id=session_id,
                remote_address=remote_address,
                session_stats=session_stats,
            )

        LOGGER.warning(
            "Submit rejected: session=%s remote=%s rejectCount=%s submittedJobId=%s currentJobId=%s previousJobId=%s jobStatus=%s rejectReason=%s detail=%s",
            session_id,
            remote_address,
            share_count,
            submit_job_id,
            current_job_id,
            previous_job_id,
            assessment.job_status,
            assessment.reject_reason,
            assessment.detail,
        )

    def _assess_target_context(
        self,
        params: list[Any],
        *,
        cached_job: Any | None,
    ) -> TargetContextCheck:
        if cached_job is None:
            return TargetContextCheck(status=None, reject_reason=None)

        target_context = cached_job.target_context
        if not isinstance(target_context, dict):
            return TargetContextCheck(
                status="target-context-missing",
                reject_reason="target-context-missing",
                detail="issued job is missing target context",
            )

        required_fields = {"bits", "version", "curtime"}
        if cached_job.source == "daemon-template":
            required_fields.add("target")
            if not isinstance(cached_job.template_anchor, str) or not cached_job.template_anchor:
                return TargetContextCheck(
                    status="target-context-missing",
                    reject_reason="target-context-missing",
                    detail="daemon-template job is missing template anchor",
                )

        missing_fields = [
            field_name
            for field_name in sorted(required_fields)
            if target_context.get(field_name) in (None, "")
        ]
        if missing_fields:
            return TargetContextCheck(
                status="target-context-missing",
                reject_reason="target-context-missing",
                detail=f"issued job target context is missing {', '.join(missing_fields)}",
            )

        context_bits = target_context.get("bits")
        context_version = target_context.get("version")
        context_curtime = _parse_uint32(target_context.get("curtime"))
        issued_ntime = _parse_hex_u32(cached_job.ntime)
        if (
            not isinstance(context_bits, str)
            or context_bits.strip().lower() != cached_job.nbits.lower()
            or not isinstance(context_version, str)
            or context_version.strip().lower() != cached_job.version.lower()
            or context_curtime is None
            or issued_ntime is None
            or context_curtime != issued_ntime
        ):
            return TargetContextCheck(
                status="target-context-mismatch",
                reject_reason="target-context-mismatch",
                detail="issued job target context does not match cached header fields",
            )

        submit_extranonce2 = params[2]
        submit_ntime = _parse_hex_u32(params[3])
        submit_nonce = _parse_hex_u32(params[4])
        if not _is_hex_string(submit_extranonce2):
            return TargetContextCheck(
                status="target-context-mismatch",
                reject_reason="target-context-mismatch",
                detail="submit extranonce2 must be hex for target-context checks",
            )
        if submit_ntime is None:
            return TargetContextCheck(
                status="target-context-mismatch",
                reject_reason="target-context-mismatch",
                detail="submit ntime must be 8-character hex for target-context checks",
            )
        if submit_nonce is None:
            return TargetContextCheck(
                status="target-context-mismatch",
                reject_reason="target-context-mismatch",
                detail="submit nonce must be 8-character hex for target-context checks",
            )

        max_submit_ntime = context_curtime + max(15, self._config.template_job_ttl_seconds)
        if submit_ntime < context_curtime or submit_ntime > max_submit_ntime:
            return TargetContextCheck(
                status="target-context-mismatch",
                reject_reason="target-context-mismatch",
                detail=(
                    "submit ntime is outside the issued target-context window "
                    f"({context_curtime:08x}-{max_submit_ntime:08x})"
                ),
            )

        if cached_job.source != "daemon-template":
            return TargetContextCheck(status="context-valid", reject_reason=None)

        target_value = target_context.get("target")
        if not isinstance(target_value, str) or not target_value.strip():
            return TargetContextCheck(
                status="target-context-missing",
                reject_reason="target-context-missing",
                detail="daemon-template job is missing target value",
            )
        if not _is_hex_string(target_value):
            return TargetContextCheck(
                status="target-context-mismatch",
                reject_reason="target-context-mismatch",
                detail="daemon-template target value must be hex",
            )

        return TargetContextCheck(
            status="candidate-possible",
            reject_reason=None,
            candidate_possible=True,
        )

    def _assess_share_hash(
        self,
        params: list[Any],
        *,
        state: ConnectionState,
        cached_job: Any | None,
        target_context_check: TargetContextCheck,
    ) -> ShareHashCheck:
        if cached_job is None or cached_job.source != "daemon-template":
            return ShareHashCheck(status=None, reject_reason=None)
        if not target_context_check.candidate_possible:
            return ShareHashCheck(status=None, reject_reason=None)

        preimage = _build_share_header_preimage(
            cached_job,
            extranonce1=state.extranonce1,
            extranonce2=params[2],
            ntime=params[3],
            nonce=params[4],
        )
        if preimage.reject_reason is not None:
            return ShareHashCheck(
                status=preimage.status,
                reject_reason=preimage.reject_reason,
                detail=preimage.detail,
            )

        assert preimage.header is not None
        target_context = cached_job.target_context if isinstance(cached_job.target_context, dict) else {}
        target_value = target_context.get("target")
        if not isinstance(target_value, str) or not target_value.strip():
            return ShareHashCheck(
                status="preimage-missing",
                reject_reason="preimage-missing",
                detail="daemon-template job is missing target for local hash check",
            )
        if not _is_hex_string(target_value):
            return ShareHashCheck(
                status="preimage-mismatch",
                reject_reason="preimage-mismatch",
                detail="daemon-template target must be hex for local hash check",
            )

        try:
            share_hash = _calculate_pepepow_share_hash(preimage.header)
        except PepepowPowError as exc:
            LOGGER.warning("PEPEPOW local hash check unavailable: %s", exc)
            return ShareHashCheck(status=None, reject_reason=None, detail=str(exc))
        share_hash_int = int.from_bytes(share_hash, byteorder="big", signed=False)
        target_int = int(target_value.strip(), 16)
        if share_hash_int <= target_int:
            return ShareHashCheck(
                status="share-hash-valid",
                reject_reason=None,
                valid=True,
            )

        return ShareHashCheck(
            status="share-hash-invalid",
            reject_reason=None,
            valid=False,
        )

    def _should_suppress_reject_log(self, assessment: SubmitAssessment) -> bool:
        return assessment.reject_reason in REJECT_LOG_SUPPRESS_REASONS

    def _flush_reject_log_summary(
        self,
        *,
        session_id: str,
        remote_address: str,
        session_stats: SessionStats,
    ) -> None:
        if session_stats.suppressed_reject_logs <= 0:
            session_stats.reject_log_key = None
            session_stats.reject_log_context = None
            return

        context = session_stats.reject_log_context or {}
        LOGGER.warning(
            "Submit rejected repeatedly: session=%s remote=%s suppressedCount=%s submittedJobId=%s currentJobId=%s previousJobId=%s jobStatus=%s rejectReason=%s detail=%s",
            session_id,
            remote_address,
            session_stats.suppressed_reject_logs,
            context.get("submitJobId"),
            context.get("currentJobId"),
            context.get("previousJobId"),
            context.get("jobStatus"),
            context.get("rejectReason"),
            context.get("detail"),
        )
        session_stats.reject_log_key = None
        session_stats.suppressed_reject_logs = 0
        session_stats.reject_log_context = None

    def _record_submit_validation(self, assessment: SubmitAssessment) -> None:
        if assessment.accepted:
            self._submit_validation_counts["accepted"] += 1
        else:
            self._submit_validation_counts["rejected"] += 1

        if assessment.candidate_possible:
            self._submit_validation_counts["candidatePossibleCount"] += 1

        classification_counts = self._submit_validation_counts["classificationCounts"]
        classification_counts.setdefault(assessment.job_status, 0)
        classification_counts[assessment.job_status] += 1

        if assessment.reject_reason is not None:
            reject_reason_counts = self._submit_validation_counts["rejectReasonCounts"]
            reject_reason_counts.setdefault(assessment.reject_reason, 0)
            reject_reason_counts[assessment.reject_reason] += 1

        if assessment.target_validation_status is not None:
            target_validation_counts = self._submit_validation_counts[
                "targetValidationCounts"
            ]
            target_validation_counts.setdefault(assessment.target_validation_status, 0)
            target_validation_counts[assessment.target_validation_status] += 1

        if assessment.share_hash_validation_status is not None:
            share_hash_validation_counts = self._submit_validation_counts[
                "shareHashValidationCounts"
            ]
            share_hash_validation_counts.setdefault(
                assessment.share_hash_validation_status, 0
            )
            share_hash_validation_counts[assessment.share_hash_validation_status] += 1

        self._dirty_snapshot = True

    def _is_duplicate_submit(self, fingerprint: str, observed_at: datetime) -> bool:
        self._prune_submit_fingerprints(observed_at)
        return fingerprint in self._submit_fingerprints

    def _remember_submit_fingerprint(
        self, fingerprint: str, observed_at: datetime
    ) -> None:
        self._prune_submit_fingerprints(observed_at)
        self._submit_fingerprints.pop(fingerprint, None)
        self._submit_fingerprints[fingerprint] = observed_at
        while len(self._submit_fingerprints) > self._duplicate_submit_cache_size:
            self._submit_fingerprints.popitem(last=False)

    def _prune_submit_fingerprints(self, observed_at: datetime) -> None:
        cutoff = observed_at.timestamp() - SUBMIT_DUPLICATE_WINDOW_SECONDS
        expired = [
            fingerprint
            for fingerprint, seen_at in self._submit_fingerprints.items()
            if seen_at.timestamp() <= cutoff
        ]
        for fingerprint in expired:
            self._submit_fingerprints.pop(fingerprint, None)

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
            if not force and not self._dirty_snapshot and not self._job_manager.has_dirty_updates():
                return

            job_cache_snapshot = self._job_manager.snapshot(now=utc_now())
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
                job_cache_snapshot=job_cache_snapshot,
                submit_validation_snapshot=self._submit_validation_counts,
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
            self._job_manager.clear_dirty_updates()

    def _new_notify_message(self, state: ConnectionState) -> dict[str, Any]:
        observed_at = utc_now()
        self._job_counter += 1
        state.previous_job_id = state.current_job_id
        state.current_job_id = f"job-{self._job_counter:016x}"
        job = self._job_manager.issue_job(state.current_job_id, now=observed_at)
        self._dirty_snapshot = True
        return notify_notification(
            job_id=state.current_job_id,
            prevhash=job.prevhash,
            coinb1=job.coinb1,
            coinb2=job.coinb2,
            merkle_branch=list(job.merkle_branch),
            version=job.version,
            nbits=job.nbits,
            ntime=job.ntime,
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


def _validate_submit_params(params: list[Any]) -> str | None:
    if len(params) < 5:
        return "submit params must include login, job id, extranonce2, ntime, and nonce"
    if not isinstance(params[0], str):
        return "submit login must be a string"
    if not isinstance(params[1], str) or not params[1].strip():
        return "submit job id must be a non-empty string"
    if not isinstance(params[2], str) or not params[2].strip():
        return "submit extranonce2 must be a non-empty string"
    if not isinstance(params[3], str) or not params[3].strip():
        return "submit ntime must be a non-empty string"
    if not isinstance(params[4], str) or not params[4].strip():
        return "submit nonce must be a non-empty string"
    return None


def _classify_submit_job_id(
    submit_job_id: str | None,
    *,
    current_job_id: str | None,
    previous_job_id: str | None,
    cached_job: Any | None,
    is_stale_job: bool,
) -> str:
    if submit_job_id is None:
        return "malformed"
    if current_job_id is not None and submit_job_id == current_job_id and cached_job is not None:
        return "current"
    if previous_job_id is not None and submit_job_id == previous_job_id and cached_job is not None:
        return "previous"
    if is_stale_job or submit_job_id in {current_job_id, previous_job_id}:
        return "stale"
    return "unknown"


def _submit_fingerprint(login: str, params: list[Any]) -> str:
    fingerprint_payload = {
        "login": login,
        "jobId": params[1],
        "extranonce2": params[2],
        "ntime": params[3],
        "nonce": params[4],
    }
    return hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _double_sha256(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()


def _calculate_pepepow_share_hash(header: bytes) -> bytes:
    if len(header) != 80:
        raise PepepowPowError(
            f"PEPEPOW header must be 80 bytes, got {len(header)}"
        )
    masked_header = header[:76] + (b"\x00" * 4)
    header_hash = blake3_hash(header)
    matrix_seed = blake3_hash(masked_header)
    nonce = int.from_bytes(header[76:80], byteorder="little", signed=False)
    return hoohash_v110(matrix_seed, header_hash, nonce)


def _build_share_header_preimage(
    cached_job: Any,
    *,
    extranonce1: str | None,
    extranonce2: str,
    ntime: str,
    nonce: str,
) -> ShareHeaderPreimage:
    required_hex_fields = {
        "version": getattr(cached_job, "version", None),
        "prevhash": getattr(cached_job, "prevhash", None),
        "nbits": getattr(cached_job, "nbits", None),
        "job_ntime": getattr(cached_job, "ntime", None),
        "nonce": nonce,
        "submit_ntime": ntime,
        "extranonce1": extranonce1,
        "extranonce2": extranonce2,
        "coinb1": getattr(cached_job, "coinb1", None),
        "coinb2": getattr(cached_job, "coinb2", None),
    }
    missing_fields = [
        field_name
        for field_name, value in required_hex_fields.items()
        if value in (None, "")
    ]
    if missing_fields:
        return ShareHeaderPreimage(
            status="preimage-missing",
            reject_reason="preimage-missing",
            detail=f"header preimage is missing {', '.join(sorted(missing_fields))}",
        )

    version = str(required_hex_fields["version"]).strip()
    prevhash = str(required_hex_fields["prevhash"]).strip()
    nbits = str(required_hex_fields["nbits"]).strip()
    job_ntime = str(required_hex_fields["job_ntime"]).strip()
    extranonce1_value = str(required_hex_fields["extranonce1"]).strip()
    extranonce2_value = str(required_hex_fields["extranonce2"]).strip()
    submit_ntime = str(required_hex_fields["submit_ntime"]).strip()
    submit_nonce = str(required_hex_fields["nonce"]).strip()
    coinb1 = str(required_hex_fields["coinb1"]).strip()
    coinb2 = str(required_hex_fields["coinb2"]).strip()
    merkle_branch = getattr(cached_job, "merkle_branch", None)
    if merkle_branch is None:
        return ShareHeaderPreimage(
            status="preimage-missing",
            reject_reason="preimage-missing",
            detail="header preimage is missing merkle branch",
        )
    if not isinstance(merkle_branch, (list, tuple)):
        return ShareHeaderPreimage(
            status="preimage-mismatch",
            reject_reason="preimage-mismatch",
            detail="header preimage merkle branch must be an array of hex hashes",
        )

    exact_length_fields = {
        "version": version,
        "nbits": nbits,
        "job_ntime": job_ntime,
        "submit_ntime": submit_ntime,
        "nonce": submit_nonce,
        "prevhash": prevhash,
    }
    exact_lengths = {
        "version": 8,
        "nbits": 8,
        "job_ntime": 8,
        "submit_ntime": 8,
        "nonce": 8,
        "prevhash": 64,
    }
    for field_name, expected_length in exact_lengths.items():
        value = exact_length_fields[field_name]
        if not isinstance(value, str) or len(value) != expected_length or not _is_hex_string(value):
            return ShareHeaderPreimage(
                status="preimage-mismatch",
                reject_reason="preimage-mismatch",
                detail=f"header preimage field {field_name} must be {expected_length}-char hex",
            )

    variable_hex_fields = {
        "coinb1": coinb1,
        "coinb2": coinb2,
        "extranonce1": extranonce1_value,
        "extranonce2": extranonce2_value,
    }
    for field_name, value in variable_hex_fields.items():
        if len(value) % 2 != 0 or not _is_hex_string(value):
            return ShareHeaderPreimage(
                status="preimage-mismatch",
                reject_reason="preimage-mismatch",
                detail=f"header preimage field {field_name} must be even-length hex",
            )
    for index, sibling_hash in enumerate(merkle_branch):
        if (
            not isinstance(sibling_hash, str)
            or len(sibling_hash.strip()) != 64
            or not _is_hex_string(sibling_hash)
        ):
            return ShareHeaderPreimage(
                status="preimage-mismatch",
                reject_reason="preimage-mismatch",
                detail=(
                    "header preimage merkle branch entry "
                    f"{index} must be 64-character hex"
                ),
            )

    if submit_ntime != job_ntime:
        return ShareHeaderPreimage(
            status="preimage-mismatch",
            reject_reason="preimage-mismatch",
            detail="submitted ntime does not match the issued job ntime for local hash check",
        )

    try:
        coinbase = bytes.fromhex(coinb1 + extranonce1_value + extranonce2_value + coinb2)
        version_le = bytes.fromhex(version)[::-1]
        prevhash_le = bytes.fromhex(prevhash)[::-1]
        ntime_le = bytes.fromhex(submit_ntime)[::-1]
        nbits_le = bytes.fromhex(nbits)[::-1]
        nonce_le = bytes.fromhex(submit_nonce)[::-1]
    except ValueError:
        return ShareHeaderPreimage(
            status="preimage-mismatch",
            reject_reason="preimage-mismatch",
            detail="unable to decode header preimage components from hex",
        )

    coinbase_hash = _double_sha256(coinbase)
    merkle_root = _apply_merkle_branch(coinbase_hash, merkle_branch)
    header = version_le + prevhash_le + merkle_root + ntime_le + nbits_le + nonce_le
    if len(header) != 80:
        return ShareHeaderPreimage(
            status="preimage-mismatch",
            reject_reason="preimage-mismatch",
            detail=f"assembled header preimage must be 80 bytes, got {len(header)}",
        )

    return ShareHeaderPreimage(
        status="preimage-ready",
        reject_reason=None,
        header=header,
    )


def _is_hex_string(raw_value: Any) -> bool:
    return isinstance(raw_value, str) and bool(HEX_STRING_PATTERN.fullmatch(raw_value.strip()))


def _apply_merkle_branch(coinbase_hash: bytes, merkle_branch: list[str] | tuple[str, ...]) -> bytes:
    merkle_root = coinbase_hash
    for sibling_hash in merkle_branch:
        sibling = bytes.fromhex(sibling_hash.strip())[::-1]
        merkle_root = _double_sha256(merkle_root + sibling)
    return merkle_root


def _parse_hex_u32(raw_value: Any) -> int | None:
    if not isinstance(raw_value, str):
        return None

    value = raw_value.strip()
    if len(value) != 8 or not HEX_STRING_PATTERN.fullmatch(value):
        return None

    return int(value, 16)


def _parse_uint32(raw_value: Any) -> int | None:
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None
    if isinstance(raw_value, float):
        return int(raw_value) if raw_value >= 0 else None
    return None


def _parse_internal_job_sequence(job_id: str | None) -> int | None:
    if not isinstance(job_id, str):
        return None

    match = INTERNAL_JOB_ID_PATTERN.match(job_id.strip())
    if match is None:
        return None

    return int(match.group(1), 16)


def _restart_backlog_unknown_detail(
    submit_job_id: str | None,
    *,
    current_job_id: str | None,
    previous_job_id: str | None,
) -> str | None:
    submit_sequence = _parse_internal_job_sequence(submit_job_id)
    if submit_sequence is None:
        return None

    known_sequences = [
        sequence
        for sequence in (
            _parse_internal_job_sequence(current_job_id),
            _parse_internal_job_sequence(previous_job_id),
        )
        if sequence is not None
    ]
    if not known_sequences:
        return None
    if submit_sequence <= max(known_sequences):
        return None

    return (
        "job id not present in active or retired cache; "
        "possible restart backlog from prior ingress process"
    )


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

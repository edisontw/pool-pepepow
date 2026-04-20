from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
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
from daemon_rpc import append_candidate_outcome_event, candidate_followup_defaults
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
from template_jobs import PLACEHOLDER_PAYOUT_SCRIPT, TemplateJobManager


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
HEADER80_FIELD_LAYOUT = (
    ("version", 0, 4),
    ("prevHash", 4, 32),
    ("merkleRoot", 36, 32),
    ("ntime", 68, 4),
    ("bits", 72, 4),
    ("nonce", 76, 4),
)
HEADER80_FIELD_OFFSET_MAP = {
    field_name: offset for field_name, offset, _size in HEADER80_FIELD_LAYOUT
}
STRATUM_DIFF1_TARGET_BITCOIN = int(
    "00000000ffff0000000000000000000000000000000000000000000000000000", 16
)
# Use the standard Bitcoin Diff-1 target. The pool difficulty values are expressed
# in Bitcoin-compatible units, as used by pools like Foztor (e.g. 0.1, 76, 327).
STRATUM_DIFF1_TARGET = STRATUM_DIFF1_TARGET_BITCOIN
MAX_UINT256_TARGET = (1 << 256) - 1


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
    submits_received: int = 0
    reject_reason_counts: dict[str, int] = field(default_factory=dict)
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
    share_hash_diagnostic: dict[str, Any] | None = None

    @property
    def counts_as_accepted_share(self) -> bool:
        if not self.accepted:
            return False
        if self.share_hash_validation_status is None:
            return True
        return self.share_hash_valid is True


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
    diagnostic: dict[str, Any] | None = None


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
        self._active_sessions: dict[str, tuple[ConnectionState, SessionStats]] = {}
        self._duplicate_submit_cache_size = max(
            512, config.template_job_cache_size * 64
        )
        self._submit_fingerprints: OrderedDict[str, datetime] = OrderedDict()
        self._candidate_event_log_path = config.activity_log_path.with_name(
            "candidate-events.jsonl"
        )
        self._candidate_outcome_event_log_path = config.activity_log_path.with_name(
            "candidate-outcome-events.jsonl"
        )
        self._share_hash_probe_log_path = config.activity_log_path.with_name(
            "share-hash-probe.jsonl"
        )
        self._submit_evidence_path = config.activity_log_path.with_name(
            "submit-evidence.jsonl"
        )
        self._share_hash_probe_captured = False
        self._submit_validation_counts: dict[str, Any] = {
            "mode": "structural-skeleton",
            "accepted": 0,
            "rejected": 0,
            "duplicateWindowSize": self._duplicate_submit_cache_size,
            "candidatePossibleCount": 0,
            "shareHashValidationMode": SHARE_HASH_VALIDATION_MODE,
            "realSubmitblockEnabled": config.enable_real_submitblock,
            "realSubmitblockSendBudget": config.real_submitblock_max_sends,
            "realSubmitblockSendBudgetRemaining": config.real_submitblock_max_sends,
            "realSubmitblockAttemptCount": 0,
            "realSubmitblockSentCount": 0,
            "realSubmitblockErrorCount": 0,
            "realSubmitblockLastStatus": "never-attempted",
            "realSubmitblockLastAttemptAt": None,
            "realSubmitblockLastError": None,
            "classificationCounts": {
                "current": 0,
                "previous": 0,
                "stale": 0,
                "unknown": 0,
                "malformed": 0,
            },
            "rejectReasonCounts": {},
            "targetValidationCounts": {
                "context-valid": 0,
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
        if self._config.enable_real_submitblock:
            LOGGER.warning(
                "REAL submitblock ENABLED via PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true; block-target shares may call daemon submitblock; send_budget=%s remaining=%s",
                self._config.real_submitblock_max_sends,
                self._submit_validation_counts["realSubmitblockSendBudgetRemaining"],
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
        self._active_sessions[state.session_id] = (state, session_stats, remote_address)
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
            self._active_sessions.pop(state.session_id, None)
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
            state.clean_jobs_legacy = self._config.stratum_notify_clean_jobs_legacy
            LOGGER.info(
                "Miner authorized: session=%s wallet=%s worker=%s login=%s legacyNotify=%s",
                state.session_id,
                wallet,
                worker,
                normalized_login,
                state.clean_jobs_legacy,
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
            session_stats.submits_received += 1
            accepted_share = assessment.counts_as_accepted_share
            accepted_submit = assessment.accepted
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
                reason = assessment.reject_reason or "unknown"
                session_stats.reject_reason_counts[reason] = (
                    session_stats.reject_reason_counts.get(reason, 0) + 1
                )

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
                accepted=accepted_submit,
            )
            share_event_candidate_possible = assessment.candidate_possible
            if (
                isinstance(assessment.share_hash_diagnostic, dict)
                and assessment.share_hash_diagnostic.get("meetsBlockTarget") is not True
            ):
                share_event_candidate_possible = False
            # Export the final post-resolution assessment values verbatim.
            payload = {
                "timestamp": observed_at.replace(microsecond=0)
                .astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "wallet": wallet,
                "worker": worker,
                "login": login,
                "accepted": accepted_submit,
                "status": "accepted" if accepted_submit else "rejected",
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
                "candidatePossible": share_event_candidate_possible,
                "shareHashValidationStatus": assessment.share_hash_validation_status,
                "shareHashValid": assessment.share_hash_valid,
                "countsAsAcceptedShare": accepted_share,
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
            if assessment.share_hash_diagnostic is not None:
                candidate_artifact = assessment.share_hash_diagnostic.get("candidateArtifact")
                if isinstance(candidate_artifact, dict):
                    candidate_artifact.setdefault(
                        "attribution",
                        {
                            "wallet": wallet,
                            "worker": worker,
                            "login": login,
                        },
                    )
                payload["shareHashDiagnostic"] = assessment.share_hash_diagnostic
            self._maybe_append_share_hash_probe(
                assessment=assessment,
                state=state,
                wallet=wallet,
                worker=worker,
                observed_at=observed_at,
                remote_address=remote_address,
                submit_params=request.params,
            )
            self._append_submit_evidence(
                assessment=assessment,
                state=state,
                remote_address=remote_address,
                params=request.params,
                observed_at=observed_at,
            )
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
            wallet=state.authorized_wallet,
            worker=state.authorized_worker,
            login=login,
        )
        resolved_target_validation_status, resolved_candidate_possible = (
            _resolve_target_validation_outcome(
                target_context_status=target_context_check.status,
                target_context_candidate_possible=target_context_check.candidate_possible,
                share_hash_diagnostic=share_hash_check.diagnostic,
            )
        )
        if share_hash_check.reject_reason is not None:
            return SubmitAssessment(
                job_status=job_status,
                submit_job_id=submit_job_id,
                cached_job=cached_job,
                accepted=False,
                reject_reason=share_hash_check.reject_reason,
                detail=share_hash_check.detail,
                target_validation_status=resolved_target_validation_status,
                candidate_possible=resolved_candidate_possible,
                share_hash_validation_status=share_hash_check.status,
                share_hash_valid=share_hash_check.valid,
                share_hash_diagnostic=share_hash_check.diagnostic,
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
                target_validation_status=resolved_target_validation_status,
                candidate_possible=resolved_candidate_possible,
                share_hash_validation_status=share_hash_check.status,
                share_hash_valid=share_hash_check.valid,
                share_hash_diagnostic=share_hash_check.diagnostic,
            )

        self._remember_submit_fingerprint(fingerprint, observed_at)
        return SubmitAssessment(
            job_status=job_status,
            submit_job_id=submit_job_id,
            cached_job=cached_job,
            accepted=True,
            target_validation_status=resolved_target_validation_status,
            candidate_possible=resolved_candidate_possible,
            share_hash_validation_status=share_hash_check.status,
            share_hash_valid=share_hash_check.valid,
            share_hash_diagnostic=share_hash_check.diagnostic,
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

    def _append_submit_evidence(
        self,
        assessment: SubmitAssessment,
        state: ConnectionState,
        remote_address: str,
        params: list[Any],
        observed_at: datetime,
    ) -> None:
        cached_job = assessment.cached_job
        job_source = getattr(cached_job, "source", None)
        if job_source != "daemon-template":
            return

        diag = assessment.share_hash_diagnostic or {}
        coinbase_sum = diag.get("coinbaseAssemblySummary") or {}
        merkle_sum = diag.get("merkleSummary") or {}
        
        is_interesting = (
            assessment.share_hash_validation_status in ("share-hash-invalid", "share-hash-valid", "block-candidate", "low-difficulty-share")
            or diag.get("meetsBlockTarget") is True
            or assessment.reject_reason not in (None, "unknown-job", "stale-job", "duplicate-submit")
        )
        if not is_interesting:
            return

        record = {
            "timestamp": observed_at.replace(microsecond=0).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sessionId": state.session_id,
            "remoteAddress": remote_address,
            "wallet": state.authorized_wallet,
            "worker": state.authorized_worker,
            "jobId": assessment.submit_job_id,
            "jobSource": job_source,
            "jobStatus": assessment.job_status,
            "cleanJobsLegacy": state.clean_jobs_legacy,
            "shareHashValidationMode": SHARE_HASH_VALIDATION_MODE,
            "extranonce1": state.extranonce1,
            "extranonce2": params[2] if len(params) > 2 else None,
            "ntime": params[3] if len(params) > 3 else None,
            "nonce": params[4] if len(params) > 4 else None,
            "preimageVersion": getattr(cached_job, "version", None),
            "preimagePrevhash": getattr(cached_job, "prevhash", None),
            "preimageNbits": getattr(cached_job, "nbits", None),
            "preimageJobNtime": getattr(cached_job, "ntime", None),
            "coinbaseHashLocal": coinbase_sum.get("coinbaseHash"),
            "coinbaseLocalHex": coinbase_sum.get("coinbaseLocalHex"),
            "merkleRoot": merkle_sum.get("merkleRoot"),
            "header80Hex": diag.get("header80Hex"),
            "matrixSeed": diag.get("matrixSeed") or diag.get("matrixSeedBlake3"),
            "headerHashBlake3": diag.get("headerHashBlake3"),
            "localComputedHash": diag.get("localComputedHash"),
            "independentAuthoritativeShareHash": diag.get("independentAuthoritativeShareHash"),
            "shareTarget": diag.get("shareTarget") or diag.get("shareTargetUsed"),
            "blockTarget": diag.get("blockTarget") or diag.get("blockTargetUsed"),
            "meetsShareTarget": diag.get("meetsShareTarget"),
            "meetsBlockTarget": diag.get("meetsBlockTarget"),
            "refinedReasonCode": diag.get("refinedReasonCode"),
            "variantTargetMatches": diag.get("header80VariantTargetMatches"),
            "shareHashValidationStatus": assessment.share_hash_validation_status,
            "targetValidationStatus": assessment.target_validation_status,
            "candidatePossible": assessment.candidate_possible,
            "rejectReason": assessment.reject_reason,
            "rejectDetail": assessment.detail,
            "jobContext": assessment.job_status,
        }
        record = {k: v for k, v in record.items() if v is not None}
        try:
            with open(self._submit_evidence_path, "a") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception as exc:
            LOGGER.error("Failed to append submit evidence: %s", exc)

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
        wallet: str | None = None,
        worker: str | None = None,
        login: str | None = None,
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
            version_source_order=getattr(self._config, "pepepow_header_version_source_order_enabled", False) is True,
        )
        if preimage.reject_reason is not None:
            return ShareHashCheck(
                status=preimage.status,
                reject_reason=preimage.reject_reason,
                detail=preimage.detail,
                diagnostic=_build_share_hash_diagnostic(
                    cached_job,
                    extranonce1=state.extranonce1,
                    extranonce2=params[2],
                    ntime=params[3],
                    nonce=params[4],
                    comparison_stage=_diagnostic_comparison_stage_for_preimage_detail(
                        preimage.detail
                    ),
                    reason_code=_classify_preimage_reason_code(
                        cached_job,
                        detail=preimage.detail,
                    ),
                    detail=preimage.detail,
                ),
            )

        assert preimage.header is not None
        target_context = cached_job.target_context if isinstance(cached_job.target_context, dict) else {}
        target_value = target_context.get("target")
        if not isinstance(target_value, str) or not target_value.strip():
            return ShareHashCheck(
                status="preimage-missing",
                reject_reason="preimage-missing",
                detail="daemon-template job is missing target for local hash check",
                diagnostic=_build_share_hash_diagnostic(
                    cached_job,
                    extranonce1=state.extranonce1,
                    extranonce2=params[2],
                    ntime=params[3],
                    nonce=params[4],
                    comparison_stage="template-context",
                    reason_code="template-context-mismatch",
                    detail="daemon-template job is missing target for local hash check",
                ),
            )
        if not _is_hex_string(target_value):
            return ShareHashCheck(
                status="preimage-mismatch",
                reject_reason="preimage-mismatch",
                detail="daemon-template target must be hex for local hash check",
                diagnostic=_build_share_hash_diagnostic(
                    cached_job,
                    extranonce1=state.extranonce1,
                    extranonce2=params[2],
                    ntime=params[3],
                    nonce=params[4],
                    comparison_stage="template-context",
                    reason_code="template-context-mismatch",
                    detail="daemon-template target must be hex for local hash check",
                ),
            )

        try:
            share_hash = _calculate_pepepow_share_hash(preimage.header)
        except PepepowPowError as exc:
            LOGGER.warning("PEPEPOW local hash check unavailable: %s", exc)
            return ShareHashCheck(status=None, reject_reason=None, detail=str(exc))
        block_target_int = int(target_value.strip(), 16)
        share_target_int = _share_target_from_difficulty(
            state.current_difficulty or self._synthetic_difficulty()
        )
        threshold_summary = _build_share_hash_threshold_summary(
            share_hash=share_hash,
            block_target_int=block_target_int,
            share_target_int=share_target_int,
        )
        if threshold_summary["meetsShareTarget"]:
            if threshold_summary["meetsBlockTarget"]:
                threshold_summary.update(
                    _prepare_candidate_artifact(
                        cached_job,
                        header=preimage.header,
                        share_hash=share_hash,
                        extranonce1_hex=str(state.extranonce1).strip(),
                        extranonce2_hex=str(params[2]).strip(),
                        ntime_hex=str(params[3]).strip(),
                        nonce_hex=str(params[4]).strip(),
                        block_target_hex=f"{block_target_int:064x}",
                    )
                )
                threshold_summary.update(
                    self._maybe_submit_prepared_candidate(threshold_summary)
                )
                self._append_candidate_evidence(
                    cached_job=cached_job,
                    wallet=wallet,
                    worker=worker,
                    login=login,
                    threshold_summary=threshold_summary,
                )
                return ShareHashCheck(
                    status="block-candidate",
                    reject_reason=None,
                    valid=True,
                    diagnostic={
                        "comparisonStage": "share-hash-compare",
                        "reasonCode": "block-candidate",
                        "localComputedHash": share_hash.hex(),
                        **threshold_summary,
                    },
                )
            return ShareHashCheck(
                status="share-hash-valid",
                reject_reason=None,
                valid=True,
                diagnostic={
                    "comparisonStage": "share-hash-compare",
                    "reasonCode": "pool-share",
                    "localComputedHash": share_hash.hex(),
                    **threshold_summary,
                },
            )

        return ShareHashCheck(
            status="low-difficulty-share",
            reject_reason="low-difficulty-share",
            valid=False,
            diagnostic=_build_share_hash_diagnostic(
                cached_job,
                extranonce1=state.extranonce1,
                extranonce2=params[2],
                ntime=params[3],
                nonce=params[4],
                comparison_stage="share-hash-compare",
                reason_code="low-difficulty-share",
                detail="local share hash exceeded effective share target",
                header=preimage.header,
                share_hash=share_hash,
                target_value=threshold_summary["shareTargetUsed"],
            )
            | threshold_summary,
        )

    def _maybe_submit_prepared_candidate(
        self,
        threshold_summary: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._config.enable_real_submitblock:
            return self._record_submitblock_status(
                _submitblock_status_result(status="submit-disabled-flag-off")
            )
        if (
            self._submit_validation_counts["realSubmitblockSentCount"]
            >= self._config.real_submitblock_max_sends
        ):
            return self._record_submitblock_status(
                _submitblock_status_result(
                    status="submit-skipped-send-budget-exhausted"
                )
            )
        if threshold_summary.get("candidatePrepStatus") != "candidate-prepared-complete":
            return self._record_submitblock_status(
                _submitblock_status_result(
                    status="submit-skipped-incomplete-candidate"
                )
            )
        if not threshold_summary.get("submitblockDryRunReady"):
            return self._record_submitblock_status(
                _submitblock_status_result(
                    status="submit-skipped-incomplete-dry-run"
                )
            )
        payload_hex = threshold_summary.get("submitblockPayloadHex")
        rpc_method = threshold_summary.get("submitblockRpcMethod")
        if (
            rpc_method != "submitblock"
            or not isinstance(payload_hex, str)
            or not payload_hex
        ):
            return self._record_submitblock_status(
                _submitblock_status_result(
                    status="submit-skipped-missing-payload"
                )
            )

        rpc_client = getattr(self._job_manager, "_rpc_client", None)
        if rpc_client is None or not hasattr(rpc_client, "submitblock"):
            return self._record_submitblock_status(
                _submitblock_status_result(
                    status="submit-skipped-missing-rpc-client"
                )
            )

        submitted_at = _isoformat_optional(utc_now())
        try:
            daemon_result = rpc_client.submitblock(payload_hex)
        except Exception as exc:
            return self._record_submitblock_status(
                _submitblock_status_result(
                    status="submit-error",
                    attempted=True,
                    sent=False,
                    submitted_at=submitted_at,
                    exception_text=str(exc),
                )
            )

        return self._record_submitblock_status(
            _submitblock_status_result(
                status="submit-sent",
                attempted=True,
                sent=True,
                submitted_at=submitted_at,
                daemon_result=daemon_result,
            )
        )

    def _record_submitblock_status(
        self,
        status_payload: dict[str, Any],
    ) -> dict[str, Any]:
        attempted = bool(status_payload.get("submitblockAttempted"))
        sent = bool(status_payload.get("submitblockSent"))
        status = status_payload.get("submitblockRealSubmitStatus")
        exception_text = status_payload.get("submitblockException")

        if attempted:
            self._submit_validation_counts["realSubmitblockAttemptCount"] += 1
        if sent:
            self._submit_validation_counts["realSubmitblockSentCount"] += 1
        if exception_text:
            self._submit_validation_counts["realSubmitblockErrorCount"] += 1

        self._submit_validation_counts["realSubmitblockSendBudgetRemaining"] = max(
            0,
            self._config.real_submitblock_max_sends
            - self._submit_validation_counts["realSubmitblockSentCount"],
        )
        self._submit_validation_counts["realSubmitblockLastStatus"] = status
        self._submit_validation_counts["realSubmitblockLastAttemptAt"] = status_payload.get(
            "submitblockSubmittedAt"
        )
        self._submit_validation_counts["realSubmitblockLastError"] = exception_text
        return status_payload

    def _append_candidate_evidence(
        self,
        *,
        cached_job: Any,
        wallet: str | None,
        worker: str | None,
        login: str | None,
        threshold_summary: dict[str, Any],
    ) -> None:
        candidate_artifact = threshold_summary.get("candidateArtifact")
        if not isinstance(candidate_artifact, dict):
            candidate_artifact = {}
        payload = {
            "timestamp": _isoformat_optional(utc_now()),
            "jobId": getattr(cached_job, "job_id", None),
            "templateAnchor": getattr(cached_job, "template_anchor", None),
            "wallet": wallet,
            "worker": worker,
            "login": login,
            "candidateBlockHash": candidate_artifact.get("candidateBlockHash")
            or threshold_summary.get("submitblockPayloadHash"),
            "candidatePrepStatus": threshold_summary.get("candidatePrepStatus"),
            "candidateCompleteEnoughForFutureSubmitblock": candidate_artifact.get(
                "completeEnoughForFutureSubmitblock"
            ),
            "submitblockDryRunReady": threshold_summary.get("submitblockDryRunReady"),
            "submitblockDryRunStatus": threshold_summary.get("submitblockDryRunStatus"),
            "realSubmitblockEnabled": self._config.enable_real_submitblock,
            "submitblockAttempted": threshold_summary.get("submitblockAttempted"),
            "submitblockSent": threshold_summary.get("submitblockSent"),
            "submitblockRealSubmitStatus": threshold_summary.get(
                "submitblockRealSubmitStatus"
            ),
            "submitblockSubmittedAt": threshold_summary.get("submitblockSubmittedAt"),
            "submitblockRpcMethod": threshold_summary.get("submitblockRpcMethod"),
            "submitblockRpcParamsShape": threshold_summary.get(
                "submitblockRpcParamsShape"
            ),
            "submitblockPayloadHash": threshold_summary.get("submitblockPayloadHash"),
            "submitblockPayloadBytes": threshold_summary.get("submitblockPayloadBytes"),
            "submitblockDaemonResult": threshold_summary.get("submitblockDaemonResult"),
            "submitblockException": threshold_summary.get("submitblockException"),
            "shareHashUsed": threshold_summary.get("shareHashUsed"),
            "blockTargetUsed": threshold_summary.get("blockTargetUsed"),
            "missingData": threshold_summary.get("missingData"),
            **candidate_followup_defaults(),
        }
        try:
            self._candidate_event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._candidate_event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                )
                handle.write("\n")
            append_candidate_outcome_event(
                self._candidate_outcome_event_log_path,
                payload,
            )
        except OSError:
            LOGGER.exception(
                "Failed to append candidate evidence or outcome evidence near %s",
                self._candidate_event_log_path,
            )

    def _maybe_append_share_hash_probe(
        self,
        *,
        assessment: SubmitAssessment,
        state: ConnectionState,
        wallet: str | None,
        worker: str | None,
        observed_at: datetime,
        remote_address: str,
        submit_params: list[Any],
    ) -> None:
        if self._share_hash_probe_captured:
            return
        if (not assessment.accepted and assessment.reject_reason != "low-difficulty-share") or assessment.job_status not in {"current", "previous"}:
            return
        if assessment.share_hash_valid is not False:
            return
        if assessment.share_hash_validation_status != "share-hash-invalid":
            return
        if assessment.target_validation_status not in {
            "candidate-possible",
            "context-valid",
        }:
            return

        cached_job = assessment.cached_job
        if cached_job is None or getattr(cached_job, "source", None) != "daemon-template":
            return

        diagnostic = (
            assessment.share_hash_diagnostic
            if isinstance(assessment.share_hash_diagnostic, dict)
            else {}
        )
        input_summary = diagnostic.get("inputSummary")
        if not isinstance(input_summary, dict):
            input_summary = {}
        coinbase_summary = diagnostic.get("coinbaseAssemblySummary")
        if not isinstance(coinbase_summary, dict):
            coinbase_summary = {}
        merkle_summary = diagnostic.get("merkleSummary")
        if not isinstance(merkle_summary, dict):
            merkle_summary = {}

        payload = {
            "timestamp": observed_at.replace(microsecond=0)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "jobId": assessment.submit_job_id,
            "jobSource": getattr(cached_job, "source", None),
            "jobStatus": assessment.job_status,
            "remoteAddress": remote_address,
            "wallet": wallet,
            "worker": worker,
            "accepted": assessment.accepted,
            "status": "accepted" if assessment.accepted else "rejected",
            "shareHashValidationStatus": assessment.share_hash_validation_status,
            "targetValidationStatus": assessment.target_validation_status,
            "submit": {
                "extranonce1": input_summary.get("extranonce1") or state.extranonce1,
                "extranonce2": input_summary.get("extranonce2") or _optional_submit_param(submit_params, 2),
                "ntime": input_summary.get("ntime") or _optional_submit_param(submit_params, 3),
                "nonce": input_summary.get("nonce") or _optional_submit_param(submit_params, 4),
                "solution": _optional_submit_param(submit_params, 5),
                "difficulty": state.current_difficulty or self._synthetic_difficulty(),
                "shareTarget": diagnostic.get("shareTargetUsed"),
                "blockTarget": diagnostic.get("blockTargetUsed"),
            },
            "poolReconstruction": {
                "prevhash": _normalize_optional_hex(getattr(cached_job, "prevhash", None)),
                "version": _normalize_optional_hex(getattr(cached_job, "version", None)),
                "nbits": _normalize_optional_hex(getattr(cached_job, "nbits", None)),
                "ntime": input_summary.get("ntime") or _optional_submit_param(submit_params, 3),
                "coinbase1Digest": _hex_digest(getattr(cached_job, "coinb1", None)),
                "coinbase2Digest": _hex_digest(getattr(cached_job, "coinb2", None)),
                "extranonce1": input_summary.get("extranonce1") or state.extranonce1,
                "extranonce2": input_summary.get("extranonce2") or _optional_submit_param(submit_params, 2),
                "reconstructedCoinbaseHash": coinbase_summary.get("coinbaseHash"),
                "reconstructedMerkleRoot": merkle_summary.get("merkleRoot"),
                "reconstructedHeader80Hex": diagnostic.get("header80ExpectedHex"),
                "matrixSeedBlake3": diagnostic.get("matrixSeedBlake3"),
                "headerHashBlake3": diagnostic.get("headerHashBlake3"),
                "localComputedHash": diagnostic.get("localComputedHash"),
                "independentAuthoritativeShareHash": diagnostic.get(
                    "independentAuthoritativeShareHash"
                ),
                "comparedTarget": diagnostic.get("comparedTarget"),
                "shareHashUsed": diagnostic.get("shareHashUsed"),
                "shareTargetUsed": diagnostic.get("shareTargetUsed"),
                "blockTargetUsed": diagnostic.get("blockTargetUsed"),
            },
        }
        try:
            self._share_hash_probe_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._share_hash_probe_log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                )
                handle.write("\n")
            self._share_hash_probe_captured = True
        except OSError:
            LOGGER.exception(
                "Failed to append share-hash probe artifact near %s",
                self._share_hash_probe_log_path,
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
        if assessment.counts_as_accepted_share:
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
                latest_anchor = self._job_manager.latest_template_anchor
                if latest_anchor is not None and state.last_notified_anchor == latest_anchor:
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

            active_sessions_payload = {}
            for session_id, (state, stats, remote_addr) in self._active_sessions.items():
                active_sessions_payload[session_id] = {
                    "remoteAddress": remote_addr,
                    "authorizedLogin": state.authorized_login,
                    "wallet": state.authorized_wallet,
                    "worker": state.authorized_worker,
                    "submitsReceived": stats.submits_received,
                    "acceptedShares": stats.accepted_share_count,
                    "rejectedShares": stats.rejected_share_count,
                    "rejectReasonCounts": stats.reject_reason_counts,
                    "advertisedDifficulty": state.current_difficulty,
                    "cleanJobsLegacy": state.clean_jobs_legacy,
                    "lastShareAt": _isoformat_or_none(stats.last_share_at),
                    "currentJobId": state.current_job_id,
                }
            snapshot["activeSessions"] = active_sessions_payload
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
        state.last_notified_anchor = job.template_anchor
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
            legacy_clean_jobs=state.clean_jobs_legacy,
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
    if cached_job is not None and not is_stale_job:
        return "previous"
    if is_stale_job:
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


def _share_target_from_difficulty(difficulty: float | None) -> int | None:
    if difficulty is None or not math.isfinite(difficulty) or difficulty <= 0:
        return None
    target = int(STRATUM_DIFF1_TARGET / difficulty)
    return max(1, min(MAX_UINT256_TARGET, target))


def _build_share_hash_threshold_summary(
    *,
    share_hash: bytes,
    block_target_int: int,
    share_target_int: int | None,
) -> dict[str, Any]:
    effective_share_target_int = max(
        block_target_int,
        share_target_int if share_target_int is not None else block_target_int,
    )
    share_hash_int = int.from_bytes(share_hash, byteorder="big", signed=False)
    return {
        "meetsShareTarget": share_hash_int <= effective_share_target_int,
        "meetsBlockTarget": share_hash_int <= block_target_int,
        "shareTargetUsed": f"{effective_share_target_int:064x}",
        "blockTargetUsed": f"{block_target_int:064x}",
        "shareHashComparisonMode": "effective-pool-share-target-and-block-target",
        "candidatePrepStatus": "candidate-not-triggered",
        "submitblockDryRunReady": False,
        "submitblockDryRunStatus": "dry-run-not-triggered",
        "submitblockAttempted": False,
        "submitblockSent": False,
        "submitblockRealSubmitStatus": "submit-not-triggered",
        "submitblockSubmittedAt": None,
        "submitblockDaemonResult": None,
        "submitblockException": None,
    }


def _prepare_candidate_artifact(
    cached_job: Any,
    *,
    header: bytes,
    share_hash: bytes,
    extranonce1_hex: str,
    extranonce2_hex: str,
    ntime_hex: str,
    nonce_hex: str,
    block_target_hex: str,
) -> dict[str, Any]:
    authoritative_context = (
        cached_job.authoritative_context
        if isinstance(getattr(cached_job, "authoritative_context", None), dict)
        else {}
    )
    coinb1_hex = _normalize_optional_hex(getattr(cached_job, "coinb1", None))
    coinb2_hex = _normalize_optional_hex(getattr(cached_job, "coinb2", None))
    transaction_data_hexes = authoritative_context.get("transactionDataHexes")
    template_transaction_count = (
        cached_job.preimage_context.get("templateTransactionCount")
        if isinstance(getattr(cached_job, "preimage_context", None), dict)
        else None
    )
    if (
        coinb1_hex is None
        or coinb2_hex is None
        or not isinstance(template_transaction_count, int)
        or template_transaction_count < 0
    ):
        artifact = {
            "candidateBlockHeaderHex": header.hex(),
            "candidateBlockHash": share_hash.hex(),
            "shareHashUsed": share_hash.hex(),
            "blockTargetUsed": block_target_hex,
            "jobId": getattr(cached_job, "job_id", None),
            "templateAnchor": getattr(cached_job, "template_anchor", None),
            "submitFields": {
                "extranonce1": extranonce1_hex,
                "extranonce2": extranonce2_hex,
                "ntime": ntime_hex,
                "nonce": nonce_hex,
            },
            "completeEnoughForFutureSubmitblock": False,
            "missingData": ["coinbase-components-or-template-transaction-count"],
        }
        return {
            "candidatePrepStatus": "candidate-prep-incomplete-missing-data",
            "candidateArtifact": artifact,
            **_prepare_submitblock_dry_run(artifact),
        }

    coinbase_hex = coinb1_hex + extranonce1_hex + extranonce2_hex + coinb2_hex
    artifact = {
        "candidateBlockHeaderHex": header.hex(),
        "candidateBlockHash": share_hash.hex(),
        "shareHashUsed": share_hash.hex(),
        "blockTargetUsed": block_target_hex,
        "jobId": getattr(cached_job, "job_id", None),
        "templateAnchor": getattr(cached_job, "template_anchor", None),
        "submitFields": {
            "extranonce1": extranonce1_hex,
            "extranonce2": extranonce2_hex,
            "ntime": ntime_hex,
            "nonce": nonce_hex,
        },
        "coinbaseTransactionHex": coinbase_hex,
        "coinbaseTransactionHash": _double_sha256(bytes.fromhex(coinbase_hex)).hex(),
        "nonCoinbaseTransactionCount": template_transaction_count,
        "completeEnoughForFutureSubmitblock": False,
        "missingData": [],
    }
    if template_transaction_count == 0:
        artifact["candidateBlockHex"] = (
            header.hex()
            + _encode_varint_local(1).hex()
            + coinbase_hex
        )
        artifact["completeEnoughForFutureSubmitblock"] = True
        return {
            "candidatePrepStatus": "candidate-prepared-complete",
            "candidateArtifact": artifact,
            **_prepare_submitblock_dry_run(artifact),
        }

    if (
        not isinstance(transaction_data_hexes, (list, tuple))
        or len(transaction_data_hexes) != template_transaction_count
        or not all(
            isinstance(raw_tx, str) and bool(raw_tx) for raw_tx in transaction_data_hexes
        )
    ):
        artifact["missingData"] = ["non-coinbase-transaction-data"]
        return {
            "candidatePrepStatus": "candidate-prepared-partial",
            "candidateArtifact": artifact,
            **_prepare_submitblock_dry_run(artifact),
        }

    artifact["candidateBlockHex"] = (
        header.hex()
        + _encode_varint_local(1 + template_transaction_count).hex()
        + coinbase_hex
        + "".join(str(raw_tx) for raw_tx in transaction_data_hexes)
    )
    artifact["completeEnoughForFutureSubmitblock"] = True
    return {
        "candidatePrepStatus": "candidate-prepared-complete",
        "candidateArtifact": artifact,
        **_prepare_submitblock_dry_run(artifact),
    }


def _prepare_submitblock_dry_run(candidate_artifact: dict[str, Any]) -> dict[str, Any]:
    payload_hex = candidate_artifact.get("candidateBlockHex")
    missing_data = candidate_artifact.get("missingData")
    missing_list = list(missing_data) if isinstance(missing_data, list) else []
    if not isinstance(payload_hex, str) or not payload_hex:
        return {
            "submitblockDryRunReady": False,
            "submitblockDryRunStatus": (
                "dry-run-prepared-partial"
                if candidate_artifact.get("candidateBlockHeaderHex")
                else "dry-run-skipped-missing-data"
            ),
            "submitblockRpcMethod": "submitblock",
            "submitblockPayloadHex": None,
            "submitblockPayloadHash": candidate_artifact.get("candidateBlockHash"),
            "submitblockPayloadBytes": None,
            "submitblockRpcParamsShape": "[candidateBlockHex]",
            "submitblockRpcParams": None,
            "missingData": missing_list or ["candidate-block-hex"],
        }
    return {
        "submitblockDryRunReady": True,
        "submitblockDryRunStatus": "dry-run-prepared-complete",
        "submitblockRpcMethod": "submitblock",
        "submitblockPayloadHex": payload_hex,
        "submitblockPayloadHash": candidate_artifact.get("candidateBlockHash"),
        "submitblockPayloadBytes": len(bytes.fromhex(payload_hex)),
        "submitblockRpcParamsShape": "[candidateBlockHex]",
        "submitblockRpcParams": [payload_hex],
        "missingData": [],
    }


def _submitblock_status_result(
    *,
    status: str,
    attempted: bool = False,
    sent: bool = False,
    submitted_at: str | None = None,
    daemon_result: Any = None,
    exception_text: str | None = None,
) -> dict[str, Any]:
    return {
        "submitblockAttempted": attempted,
        "submitblockSent": sent,
        "submitblockRealSubmitStatus": status,
        "submitblockSubmittedAt": submitted_at,
        "submitblockDaemonResult": daemon_result,
        "submitblockException": exception_text,
    }


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


def _normalize_optional_hex(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip().lower()
    return value or None


def _optional_submit_param(params: list[Any], index: int) -> Any | None:
    if index < 0 or index >= len(params):
        return None
    return params[index]


def _hex_digest(raw_hex: Any) -> str | None:
    normalized = _normalize_optional_hex(raw_hex)
    if normalized is None or not _is_hex_string(normalized):
        return None
    try:
        return blake3_hash(bytes.fromhex(normalized)).hex()
    except ValueError:
        return None


def _isoformat_optional(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _resolve_target_validation_outcome(
    *,
    target_context_status: str | None,
    target_context_candidate_possible: bool,
    share_hash_diagnostic: dict[str, Any] | None,
) -> tuple[str | None, bool]:
    if target_context_status != "candidate-possible":
        return target_context_status, target_context_candidate_possible

    meets_block_target = False
    if isinstance(share_hash_diagnostic, dict):
        meets_block_target = share_hash_diagnostic.get("meetsBlockTarget") is True

    if meets_block_target:
        return "candidate-possible", True

    return "context-valid", False


def _classify_preimage_reason_code(cached_job: Any, *, detail: str | None) -> str:
    preimage_context = getattr(cached_job, "preimage_context", None)
    if (
        not isinstance(preimage_context, dict)
        or preimage_context.get("source") != "template-derived"
    ):
        return "unsupported-live-job-shape"

    detail_value = (detail or "").strip().lower()
    if "submitted ntime does not match" in detail_value:
        return "ntime-normalization-mismatch"
    if "merkle branch" in detail_value:
        return "merkle-derivation-mismatch"
    if any(
        token in detail_value
        for token in (
            "coinb1",
            "coinb2",
            "extranonce1",
            "extranonce2",
            "unable to decode header preimage components from hex",
        )
    ):
        return "coinbase-assembly-mismatch"
    if "nonce" in detail_value:
        return "nonce-placement-mismatch"
    if any(
        token in detail_value
        for token in ("version", "prevhash", "nbits", "job_ntime", "submit_ntime")
    ):
        return "template-context-mismatch"
    return "unknown-classification"


def _diagnostic_comparison_stage_for_preimage_detail(detail: str | None) -> str:
    detail_value = (detail or "").strip().lower()
    if "submitted ntime does not match" in detail_value:
        return "ntime-normalization"
    if "merkle branch" in detail_value:
        return "merkle-derivation"
    if any(
        token in detail_value
        for token in (
            "coinb1",
            "coinb2",
            "extranonce1",
            "extranonce2",
            "unable to decode header preimage components from hex",
        )
    ):
        return "coinbase-assembly"
    if "nonce" in detail_value:
        return "nonce-placement"
    if any(
        token in detail_value
        for token in ("version", "prevhash", "nbits", "job_ntime", "submit_ntime")
    ):
        return "template-context"
    return "share-hash-classification"


def _classify_invalid_share_hash_reason_code(cached_job: Any) -> str:
    preimage_context = getattr(cached_job, "preimage_context", None)
    if (
        not isinstance(preimage_context, dict)
        or preimage_context.get("source") != "template-derived"
    ):
        return "unsupported-live-job-shape"

    target_context = getattr(cached_job, "target_context", None)
    if not isinstance(target_context, dict):
        return "template-context-mismatch"

    if not isinstance(getattr(cached_job, "template_anchor", None), str):
        return "template-context-mismatch"

    merkle_branch = getattr(cached_job, "merkle_branch", None)
    if not isinstance(merkle_branch, (list, tuple)):
        return "merkle-derivation-mismatch"

    return "header80-mismatch"


def _build_share_hash_diagnostic(
    cached_job: Any,
    *,
    extranonce1: str | None,
    extranonce2: Any,
    ntime: Any,
    nonce: Any,
    comparison_stage: str,
    reason_code: str,
    detail: str | None,
    header: bytes | None = None,
    share_hash: bytes | None = None,
    target_value: str | None = None,
) -> dict[str, Any]:
    target_context = (
        cached_job.target_context if isinstance(getattr(cached_job, "target_context", None), dict) else {}
    )
    preimage_context = (
        cached_job.preimage_context if isinstance(getattr(cached_job, "preimage_context", None), dict) else {}
    )
    merkle_branch = getattr(cached_job, "merkle_branch", ())

    extranonce1_value = _normalize_optional_hex(extranonce1)
    extranonce2_value = _normalize_optional_hex(extranonce2)
    ntime_value = _normalize_optional_hex(ntime)
    nonce_value = _normalize_optional_hex(nonce)
    coinb1_value = _normalize_optional_hex(getattr(cached_job, "coinb1", None))
    coinb2_value = _normalize_optional_hex(getattr(cached_job, "coinb2", None))

    coinbase_hash = None
    coinbase_hex_length = None
    if all(
        value is not None and len(value) % 2 == 0 and _is_hex_string(value)
        for value in (coinb1_value, coinb2_value, extranonce1_value, extranonce2_value)
    ):
        coinbase = bytes.fromhex(
            f"{coinb1_value}{extranonce1_value}{extranonce2_value}{coinb2_value}"
        )
        coinbase_hash = _double_sha256(coinbase).hex()
        coinbase_hex_length = len(coinbase) * 2

    merkle_root = None
    if header is not None and len(header) >= 68:
        merkle_root = header[36:68].hex()
    elif coinbase_hash is not None and isinstance(merkle_branch, (list, tuple)):
        try:
            merkle_root = _apply_merkle_branch(
                bytes.fromhex(coinbase_hash),
                merkle_branch,
            ).hex()
        except ValueError:
            merkle_root = None

    header_hex = header.hex() if header is not None else None
    normalized_target = _normalize_optional_hex(target_value)
    matrix_seed_blake3 = None
    header_hash_blake3 = None
    nonce_uint32 = None
    if header is not None and len(header) == 80:
        matrix_seed_blake3 = blake3_hash(header[:76] + (b"\x00" * 4)).hex()
        header_hash_blake3 = blake3_hash(header).hex()
        nonce_uint32 = int.from_bytes(header[76:80], byteorder="little", signed=False)

    diagnostic = {
        "comparisonStage": comparison_stage,
        "reasonCode": reason_code,
        "inputSummary": {
            "extranonce1": extranonce1_value,
            "extranonce2": extranonce2_value,
            "ntime": ntime_value,
            "nonce": nonce_value,
        },
        "templateContextSummary": {
            "jobSource": getattr(cached_job, "source", None),
            "templateAnchor": getattr(cached_job, "template_anchor", None),
            "height": target_context.get("height"),
            "bits": target_context.get("bits"),
            "version": target_context.get("version"),
            "curtime": target_context.get("curtime"),
            "target": normalized_target,
        },
        "coinbaseAssemblySummary": {
            "source": preimage_context.get("source"),
            "placeholderPayout": preimage_context.get("placeholderPayout"),
            "coinb1Length": preimage_context.get("coinb1Length"),
            "coinb2Length": preimage_context.get("coinb2Length"),
            "coinbaseOutputsCount": preimage_context.get("coinbaseOutputsCount"),
            "coinbaseValue": preimage_context.get("coinbaseValue"),
            "coinbaseHexLength": coinbase_hex_length,
            "coinbaseHash": coinbase_hash,
            "coinbaseLocalHex": f"{coinb1_value}{extranonce1_value}{extranonce2_value}{coinb2_value}" if coinbase_hex_length is not None else None,
        },
        "merkleSummary": {
            "branchLength": preimage_context.get("merkleBranchLength"),
            "templateTransactionCount": preimage_context.get("templateTransactionCount"),
            "transactionsDigest": preimage_context.get("transactionsDigest"),
            "coinbaseOutputsDigest": preimage_context.get("coinbaseOutputsDigest"),
            "merkleRoot": merkle_root,
        },
        "header80Summary": (
            {
                "byteLength": len(header),
                "hexPrefix": header_hex[:32],
                "hexSuffix": header_hex[-32:],
            }
            if header_hex is not None
            else None
        ),
        "header80Hex": header_hex,
        "localComputedHash": share_hash.hex() if share_hash is not None else None,
        "comparedTarget": normalized_target,
        "matrixSeedBlake3": matrix_seed_blake3,
        "headerHashBlake3": header_hash_blake3,
        "nonceUint32": nonce_uint32,
    }
    if detail:
        diagnostic["detail"] = detail
    if (
        reason_code == "header80-mismatch"
        and header is not None
        and normalized_target is not None
    ):
        header80_mismatch_diagnostic = _build_header80_mismatch_diagnostic(
            cached_job,
            header=header,
            ntime=ntime_value,
            nonce=nonce_value,
            target_value=normalized_target,
        )
        diagnostic.update(header80_mismatch_diagnostic)
        if (
            header80_mismatch_diagnostic.get("refinedReasonCode")
            == "upstream-context-mismatch"
            and "merkleRoot"
            in header80_mismatch_diagnostic.get("mismatchFieldNames", [])
        ):
            diagnostic.update(
                _build_merkle_provenance_diagnostic(
                    cached_job,
                    header=header,
                    extranonce1=extranonce1_value,
                    extranonce2=extranonce2_value,
                    ntime=ntime_value,
                    nonce=nonce_value,
                    coinbase_hash=coinbase_hash,
                    merkle_root=merkle_root,
                    target_value=normalized_target,
                )
            )
    return diagnostic


def _assemble_header80_from_field_bytes(field_bytes: dict[str, bytes]) -> bytes:
    return b"".join(
        field_bytes[field_name] for field_name, _offset, _size in HEADER80_FIELD_LAYOUT
    )


def _build_merkle_root_from_transaction_hashes(
    coinbase_hash: bytes, transaction_hashes: list[str] | tuple[str, ...]
) -> bytes:
    layer = [coinbase_hash]
    normalized_hashes = [
        _normalize_optional_hex(transaction_hash)
        for transaction_hash in transaction_hashes
        if isinstance(transaction_hash, str)
    ]
    if len(normalized_hashes) != len(transaction_hashes) or any(
        tx_hash is None or len(tx_hash) != 64 for tx_hash in normalized_hashes
    ):
        raise ValueError("authoritative transaction hashes are unavailable")
    layer.extend(
        bytes.fromhex(tx_hash)[::-1]
        for tx_hash in normalized_hashes
        if tx_hash is not None
    )
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [
            _double_sha256(layer[index] + layer[index + 1])
            for index in range(0, len(layer), 2)
        ]
    return layer[0]


def _build_independent_authoritative_header80_reference(
    cached_job: Any,
    *,
    extranonce1_hex: str,
    extranonce2_hex: str,
    ntime_hex: str,
    nonce_hex: str,
) -> dict[str, Any] | None:
    authoritative_context = getattr(cached_job, "authoritative_context", None)
    if not isinstance(authoritative_context, dict):
        return None

    authoritative_segments = authoritative_context.get("coinbaseSegmentSummaries")
    authoritative_outputs = authoritative_context.get("outputSummaries")
    transaction_hashes = authoritative_context.get("transactionHashes")
    version_hex = _normalize_optional_hex(getattr(cached_job, "version", None))
    prevhash_hex = _normalize_optional_hex(getattr(cached_job, "prevhash", None))
    bits_hex = _normalize_optional_hex(getattr(cached_job, "nbits", None))
    if (
        not isinstance(authoritative_segments, dict)
        or not isinstance(authoritative_outputs, list)
        or not isinstance(transaction_hashes, (list, tuple))
        or version_hex is None
        or prevhash_hex is None
        or bits_hex is None
    ):
        return None

    try:
        prefix_bytes = bytes.fromhex(
            authoritative_segments["coinbasePrefixBytes"]["hex"]
        )
        length_varint_bytes = bytes.fromhex(
            authoritative_segments["coinbaseLengthVarint"]["hex"]
        )
        script_sig_template_bytes = bytes.fromhex(
            authoritative_segments["scriptSigTemplateBytes"]["hex"]
        )
        extranonce_bytes = bytes.fromhex(extranonce1_hex) + bytes.fromhex(
            extranonce2_hex
        )
        sequence_bytes = bytes.fromhex(
            authoritative_segments["postScriptSigSequence"]["hex"]
        )
        output_count_bytes = bytes.fromhex(
            authoritative_segments["outputCountVarint"]["hex"]
        )
        locktime_bytes = bytes.fromhex(
            authoritative_segments["coinbaseTail"]["locktimeHex"]
        )
        output_bytes = b""
        for output_summary in authoritative_outputs:
            amount = output_summary.get("amount")
            script_hex = _normalize_optional_hex(output_summary.get("scriptHex"))
            script_length = output_summary.get("scriptLength")
            if (
                not isinstance(amount, int)
                or amount < 0
                or not isinstance(script_length, int)
                or script_length < 0
                or script_hex is None
                or len(script_hex) != script_length * 2
            ):
                return None
            output_bytes += (
                amount.to_bytes(8, byteorder="little", signed=False)
                + _encode_varint_local(script_length)
                + bytes.fromhex(script_hex)
            )

        authoritative_coinbase = (
            prefix_bytes
            + length_varint_bytes
            + script_sig_template_bytes
            + extranonce_bytes
            + sequence_bytes
            + output_count_bytes
            + output_bytes
            + locktime_bytes
        )
        authoritative_merkle_root = _build_merkle_root_from_transaction_hashes(
            _double_sha256(authoritative_coinbase), transaction_hashes
        )
        authoritative_field_bytes = {
            "version": bytes.fromhex(version_hex)[::-1],
            "prevHash": bytes.fromhex(prevhash_hex)[::-1],
            "merkleRoot": authoritative_merkle_root,
            "ntime": bytes.fromhex(ntime_hex)[::-1],
            "bits": bytes.fromhex(bits_hex)[::-1],
            "nonce": bytes.fromhex(nonce_hex)[::-1],
        }
    except (KeyError, TypeError, ValueError):
        return None

    header80 = _assemble_header80_from_field_bytes(authoritative_field_bytes)
    try:
        share_hash_hex = _calculate_pepepow_share_hash(header80).hex()
    except PepepowPowError:
        return None
    return {
        "header80": header80,
        "shareHash": share_hash_hex,
    }


def _build_header80_variant_target_matches(
    expected_field_bytes: dict[str, bytes],
    source_order_field_bytes: dict[str, bytes],
    *,
    target_int: int,
) -> dict[str, bool | None]:
    variant_definitions = {
        "versionSourceOrder": ("version",),
        "prevHashSourceOrder": ("prevHash",),
        "merkleRootByteReversed": ("merkleRoot",),
        "ntimeSourceOrder": ("ntime",),
        "bitsSourceOrder": ("bits",),
        "nonceSourceOrder": ("nonce",),
        "allFieldsSourceOrder": tuple(field_name for field_name, _offset, _size in HEADER80_FIELD_LAYOUT),
    }
    variant_results: dict[str, bool | None] = {}
    for variant_name, variant_fields in variant_definitions.items():
        candidate_field_bytes = dict(expected_field_bytes)
        for field_name in variant_fields:
            candidate_field_bytes[field_name] = source_order_field_bytes[field_name]
        try:
            candidate_hash = _calculate_pepepow_share_hash(
                _assemble_header80_from_field_bytes(candidate_field_bytes)
            )
        except PepepowPowError:
            variant_results[variant_name] = None
            continue
        variant_results[variant_name] = (
            int.from_bytes(candidate_hash, byteorder="big", signed=False) <= target_int
        )
    return variant_results


def _build_header80_field_summary(
    *,
    expected_field_bytes: dict[str, bytes],
    source_order_field_bytes: dict[str, bytes],
) -> dict[str, Any]:
    field_summary: dict[str, Any] = {}
    for field_name, offset, size in HEADER80_FIELD_LAYOUT:
        expected_bytes = expected_field_bytes[field_name]
        source_order_bytes = source_order_field_bytes[field_name]
        field_summary[field_name] = {
            "offset": offset,
            "length": size,
            "expectedHex": expected_bytes.hex(),
            "sourceOrderHex": source_order_bytes.hex(),
            "byteReversedHex": expected_bytes[::-1].hex(),
        }
    return field_summary


def _build_header80_mismatch_diagnostic(
    cached_job: Any,
    *,
    header: bytes,
    ntime: str | None,
    nonce: str | None,
    target_value: str,
) -> dict[str, Any]:
    version_hex = _normalize_optional_hex(getattr(cached_job, "version", None))
    prevhash_hex = _normalize_optional_hex(getattr(cached_job, "prevhash", None))
    bits_hex = _normalize_optional_hex(getattr(cached_job, "nbits", None))
    if (
        version_hex is None
        or prevhash_hex is None
        or bits_hex is None
        or ntime is None
        or nonce is None
    ):
        return {
            "refinedReasonCode": "unknown-header80-mismatch",
            "header80ExpectedHex": header.hex(),
            "comparedHeaderHex": header.hex(),
            "header80ObservedHex": None,
            "observedHeaderAvailable": False,
        }

    expected_field_bytes = {
        field_name: header[offset : offset + size]
        for field_name, offset, size in HEADER80_FIELD_LAYOUT
    }
    source_order_field_bytes = {
        "version": bytes.fromhex(version_hex),
        "prevHash": bytes.fromhex(prevhash_hex),
        "merkleRoot": expected_field_bytes["merkleRoot"][::-1],
        "ntime": bytes.fromhex(ntime),
        "bits": bytes.fromhex(bits_hex),
        "nonce": bytes.fromhex(nonce),
    }
    variant_target_matches = _build_header80_variant_target_matches(
        expected_field_bytes,
        source_order_field_bytes,
        target_int=int(target_value, 16),
    )
    single_field_variant_map = {
        "versionSourceOrder": "version",
        "prevHashSourceOrder": "prevHash",
        "merkleRootByteReversed": "merkleRoot",
        "ntimeSourceOrder": "ntime",
        "bitsSourceOrder": "bits",
        "nonceSourceOrder": "nonce",
    }
    matched_fields = [
        field_name
        for variant_name, field_name in single_field_variant_map.items()
        if variant_target_matches.get(variant_name) is True
    ]
    all_source_order_match = variant_target_matches.get("allFieldsSourceOrder") is True
    refined_reason_code = "unknown-header80-mismatch"
    mismatch_field_names: list[str] = []
    merkle_mismatch_appears_upstream = False
    endian_only_pattern = False

    if len(matched_fields) == 1:
        mismatch_field_names = matched_fields
        endian_only_pattern = True
        refined_reason_code = {
            "version": "version-mismatch",
            "prevHash": "previous-block-hash-mismatch",
            "merkleRoot": "merkle-root-mismatch",
            "ntime": "ntime-mismatch",
            "bits": "bits-mismatch",
            "nonce": "nonce-mismatch",
        }[matched_fields[0]]
    elif len(matched_fields) > 1:
        mismatch_field_names = sorted(
            matched_fields,
            key=lambda field_name: HEADER80_FIELD_OFFSET_MAP[field_name],
        )
        refined_reason_code = "multiple-field-mismatch"
        endian_only_pattern = True
    elif all_source_order_match:
        mismatch_field_names = [field_name for field_name, _offset, _size in HEADER80_FIELD_LAYOUT]
        refined_reason_code = "header-byte-ordering-mismatch"
        endian_only_pattern = True
    elif _header80_upstream_context_suspected(cached_job, ntime=ntime):
        mismatch_field_names = ["merkleRoot"]
        refined_reason_code = "upstream-context-mismatch"
        merkle_mismatch_appears_upstream = True

    mismatch_offsets = [
        HEADER80_FIELD_OFFSET_MAP[field_name]
        for field_name in mismatch_field_names
    ]
    return {
        "refinedReasonCode": refined_reason_code,
        "header80ExpectedHex": header.hex(),
        "comparedHeaderHex": header.hex(),
        "header80ObservedHex": None,
        "observedHeaderAvailable": False,
        "header80FieldSummary": _build_header80_field_summary(
            expected_field_bytes=expected_field_bytes,
            source_order_field_bytes=source_order_field_bytes,
        ),
        "mismatchFieldNames": mismatch_field_names,
        "likelyMismatchFieldNames": mismatch_field_names,
        "mismatchOffsets": mismatch_offsets,
        "firstMismatchOffset": min(mismatch_offsets) if mismatch_offsets else None,
        "endianOnlyPatternSuspected": endian_only_pattern,
        "merkleMismatchAppearsUpstream": merkle_mismatch_appears_upstream,
        "header80VariantTargetMatches": variant_target_matches,
    }


def _header80_upstream_context_suspected(cached_job: Any, *, ntime: str) -> bool:
    target_context = getattr(cached_job, "target_context", None)
    preimage_context = getattr(cached_job, "preimage_context", None)
    if not isinstance(target_context, dict) or not isinstance(preimage_context, dict):
        return False

    context_version = _normalize_optional_hex(target_context.get("version"))
    context_bits = _normalize_optional_hex(target_context.get("bits"))
    context_curtime = _parse_uint32(target_context.get("curtime"))
    cached_version = _normalize_optional_hex(getattr(cached_job, "version", None))
    cached_bits = _normalize_optional_hex(getattr(cached_job, "nbits", None))
    submit_ntime = _parse_hex_u32(ntime)
    return (
        preimage_context.get("source") == "template-derived"
        and isinstance(getattr(cached_job, "template_anchor", None), str)
        and context_version == cached_version
        and context_bits == cached_bits
        and context_curtime is not None
        and submit_ntime is not None
        and context_curtime == submit_ntime
    )


def _replace_header_merkle_root(header: bytes, merkle_root_hex: str) -> bytes:
    return header[:36] + bytes.fromhex(merkle_root_hex) + header[68:]


def _decode_varint_at(payload: bytes, offset: int) -> tuple[int | None, int]:
    if offset >= len(payload):
        return None, offset
    prefix = payload[offset]
    if prefix < 0xFD:
        return prefix, offset + 1
    if prefix == 0xFD and offset + 3 <= len(payload):
        return int.from_bytes(payload[offset + 1 : offset + 3], "little"), offset + 3
    if prefix == 0xFE and offset + 5 <= len(payload):
        return int.from_bytes(payload[offset + 1 : offset + 5], "little"), offset + 5
    if prefix == 0xFF and offset + 9 <= len(payload):
        return int.from_bytes(payload[offset + 1 : offset + 9], "little"), offset + 9
    return None, offset + 1


def _encode_varint_local(value: int) -> bytes:
    if value < 0xFD:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")
    return b"\xff" + value.to_bytes(8, "little")


def _script_length_varint_offset(coinb1_bytes: bytes) -> int:
    return 4 + 1 + 32 + 4


def _build_coinbase_variant_roots(
    *,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
    merkle_branch: tuple[str, ...] | list[str],
) -> dict[str, dict[str, str | int | None]]:
    zero_extranonce1 = "00" * (len(extranonce1_hex) // 2)
    zero_extranonce2 = "00" * (len(extranonce2_hex) // 2)
    variant_components = {
        "currentAssembly": (coinb1_hex, extranonce1_hex, extranonce2_hex, coinb2_hex),
        "swapExtranonces": (coinb1_hex, extranonce2_hex, extranonce1_hex, coinb2_hex),
        "zeroExtranonce1": (coinb1_hex, zero_extranonce1, extranonce2_hex, coinb2_hex),
        "zeroExtranonce2": (coinb1_hex, extranonce1_hex, zero_extranonce2, coinb2_hex),
        "dropExtranonce1": (coinb1_hex, "", extranonce2_hex, coinb2_hex),
        "dropExtranonce2": (coinb1_hex, extranonce1_hex, "", coinb2_hex),
    }
    results: dict[str, dict[str, str | int | None]] = {}
    for variant_name, components in variant_components.items():
        coinbase_hex = "".join(components)
        if len(coinbase_hex) % 2 != 0 or not _is_hex_string(coinbase_hex):
            results[variant_name] = {
                "coinbaseHash": None,
                "merkleRoot": None,
                "coinbaseHexLength": len(coinbase_hex),
            }
            continue
        coinbase = bytes.fromhex(coinbase_hex)
        coinbase_hash = _double_sha256(coinbase).hex()
        merkle_root = _apply_merkle_branch(
            bytes.fromhex(coinbase_hash),
            merkle_branch,
        ).hex()
        results[variant_name] = {
            "coinbaseHash": coinbase_hash,
            "merkleRoot": merkle_root,
            "coinbaseHexLength": len(coinbase_hex),
        }
    return results


def _build_coinbase_assembly_variants(
    *,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
) -> dict[str, dict[str, Any]]:
    coinb1_bytes = bytes.fromhex(coinb1_hex)
    coinb2_bytes = bytes.fromhex(coinb2_hex)
    extranonce1_bytes = bytes.fromhex(extranonce1_hex)
    extranonce2_bytes = bytes.fromhex(extranonce2_hex)
    combined_extranonce = extranonce1_bytes + extranonce2_bytes
    script_length_offset = _script_length_varint_offset(coinb1_bytes)
    declared_script_length, after_varint = _decode_varint_at(
        coinb1_bytes, script_length_offset
    )
    script_prefix = coinb1_bytes[after_varint:]
    adjusted_declared = (
        declared_script_length if isinstance(declared_script_length, int) else 0
    )
    total_extranonce_bytes = len(combined_extranonce)

    variant_payloads = {
        "currentAssembly": coinb1_bytes + extranonce1_bytes + extranonce2_bytes + coinb2_bytes,
        "swapExtranonces": coinb1_bytes + extranonce2_bytes + extranonce1_bytes + coinb2_bytes,
        "prependCombinedExtranonce": combined_extranonce + coinb1_bytes + coinb2_bytes,
        "appendCombinedExtranonce": coinb1_bytes + coinb2_bytes + combined_extranonce,
        "scriptLengthMinusExtranonce": (
            coinb1_bytes[:script_length_offset]
            + _encode_varint_local(max(0, adjusted_declared - total_extranonce_bytes))
            + script_prefix
            + extranonce1_bytes
            + extranonce2_bytes
            + coinb2_bytes
        ),
        "scriptLengthPlusExtranonce": (
            coinb1_bytes[:script_length_offset]
            + _encode_varint_local(adjusted_declared + total_extranonce_bytes)
            + script_prefix
            + extranonce1_bytes
            + extranonce2_bytes
            + coinb2_bytes
        ),
    }
    variant_categories = {
        "currentAssembly": "current",
        "swapExtranonces": "extranonce-placement",
        "prependCombinedExtranonce": "prefix-boundary",
        "appendCombinedExtranonce": "suffix-boundary",
        "scriptLengthMinusExtranonce": "length-encoding",
        "scriptLengthPlusExtranonce": "length-encoding",
    }
    variants: dict[str, dict[str, Any]] = {}
    for variant_name, payload in variant_payloads.items():
        variants[variant_name] = {
            "category": variant_categories[variant_name],
            "coinbaseHex": payload.hex(),
            "coinbaseHexLength": len(payload) * 2,
            "coinbaseHash": _double_sha256(payload).hex(),
        }
    return variants


def _build_coinbase_assembly_target_matches(
    *,
    header: bytes,
    coinbase_assembly_variants: dict[str, dict[str, Any]],
    target_value: str,
) -> dict[str, bool | None]:
    target_int = int(target_value, 16)
    results: dict[str, bool | None] = {}
    for variant_name, variant_data in coinbase_assembly_variants.items():
        coinbase_hash = variant_data.get("coinbaseHash")
        if not isinstance(coinbase_hash, str):
            results[variant_name] = None
            continue
        try:
            candidate_hash = _calculate_pepepow_share_hash(
                _replace_header_merkle_root(header, coinbase_hash)
            )
        except (PepepowPowError, ValueError):
            results[variant_name] = None
            continue
        results[variant_name] = (
            int.from_bytes(candidate_hash, byteorder="big", signed=False) <= target_int
        )
    return results


def _parse_coinb2_outputs(coinb2_hex: str) -> dict[str, Any]:
    try:
        coinb2_bytes = bytes.fromhex(coinb2_hex)
    except ValueError:
        return {"valid": False, "outputs": []}

    if len(coinb2_bytes) < 8:
        return {"valid": False, "outputs": []}

    output_count, cursor = _decode_varint_at(coinb2_bytes, 4)
    if not isinstance(output_count, int):
        return {"valid": False, "outputs": []}

    outputs: list[dict[str, Any]] = []
    for index in range(output_count):
        if cursor + 8 > len(coinb2_bytes) - 4:
            return {"valid": False, "outputs": outputs}
        output_start = cursor
        amount = int.from_bytes(
            coinb2_bytes[cursor : cursor + 8], byteorder="little", signed=False
        )
        cursor += 8
        script_length, script_offset = _decode_varint_at(coinb2_bytes, cursor)
        if not isinstance(script_length, int):
            return {"valid": False, "outputs": outputs}
        script_end = script_offset + script_length
        if script_end > len(coinb2_bytes) - 4:
            return {"valid": False, "outputs": outputs}
        script_hex = coinb2_bytes[script_offset:script_end].hex()
        outputs.append(
            {
                "index": index,
                "amount": amount,
                "scriptHex": script_hex,
                "serializedHex": coinb2_bytes[output_start:script_end].hex(),
                "placeholderScript": script_hex == PLACEHOLDER_PAYOUT_SCRIPT,
            }
        )
        cursor = script_end

    if len(coinb2_bytes) - cursor != 4:
        return {"valid": False, "outputs": outputs}

    return {
        "valid": True,
        "sequenceHex": coinb2_bytes[:4].hex(),
        "outputCount": output_count,
        "outputs": outputs,
        "locktimeHex": coinb2_bytes[cursor:].hex(),
    }


def _summarize_coinb2_output(output: dict[str, Any]) -> dict[str, Any]:
    script_hex = output.get("scriptHex")
    return {
        "index": output.get("index"),
        "amount": output.get("amount"),
        "scriptLength": (
            len(script_hex) // 2 if isinstance(script_hex, str) else None
        ),
        "scriptHex": script_hex,
        "placeholderScript": output.get("placeholderScript"),
    }


def _serialize_coinb2_outputs(
    *,
    sequence_hex: str,
    outputs: list[dict[str, Any]],
    locktime_hex: str,
    output_count_override: int | None = None,
) -> str:
    output_count = (
        output_count_override if isinstance(output_count_override, int) else len(outputs)
    )
    return (
        sequence_hex
        + _encode_varint_local(output_count).hex()
        + "".join(
            output["serializedHex"]
            for output in outputs
            if isinstance(output.get("serializedHex"), str)
        )
        + locktime_hex
    )


def _evaluate_coinb2_output_layout_variant(
    *,
    header: bytes,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
    merkle_branch: tuple[str, ...] | list[str],
    target_value: str,
) -> dict[str, Any]:
    coinbase_hex = coinb1_hex + extranonce1_hex + extranonce2_hex + coinb2_hex
    coinbase_hash = _double_sha256(bytes.fromhex(coinbase_hex)).hex()
    merkle_root = _apply_merkle_branch(bytes.fromhex(coinbase_hash), merkle_branch).hex()
    candidate_header = _replace_header_merkle_root(header, merkle_root)

    share_hash_hex = None
    target_match: bool | None = None
    comparison_result = "comparison-unavailable"
    try:
        share_hash = _calculate_pepepow_share_hash(candidate_header)
        share_hash_hex = share_hash.hex()
        target_match = (
            int.from_bytes(share_hash, byteorder="big", signed=False)
            <= int(target_value, 16)
        )
        comparison_result = "share-hash-valid" if target_match else "share-hash-invalid"
    except (PepepowPowError, ValueError):
        share_hash_hex = None

    return {
        "coinb2Hex": coinb2_hex,
        "coinbaseHash": coinbase_hash,
        "merkleRoot": merkle_root,
        "header80": candidate_header.hex(),
        "shareHash": share_hash_hex,
        "targetMatch": target_match,
        "comparisonResult": comparison_result,
    }


def _first_output_mismatch_index(
    baseline_outputs: list[dict[str, Any]],
    corrected_outputs: list[dict[str, Any]],
) -> int | None:
    limit = min(len(baseline_outputs), len(corrected_outputs))
    for index in range(limit):
        baseline = baseline_outputs[index]
        corrected = corrected_outputs[index]
        if (
            baseline.get("amount") != corrected.get("amount")
            or baseline.get("scriptHex") != corrected.get("scriptHex")
            or baseline.get("placeholderScript") != corrected.get("placeholderScript")
        ):
            return index
    if len(baseline_outputs) != len(corrected_outputs):
        return limit
    return None


def _classify_output_layout_reason_code(
    *,
    parsed_coinb2: dict[str, Any],
    output_layout_variant_target_matches: dict[str, bool | None],
    non_placeholder_variant_names: list[str],
) -> tuple[str, list[str], bool, bool]:
    if not parsed_coinb2.get("valid"):
        return (
            "coinb2-segmentation-boundary-mismatch",
            [
                "coinb2-segmentation-boundary-mismatch",
                "unknown-output-layout-mismatch",
            ],
            True,
            False,
        )

    if output_layout_variant_target_matches.get("decrementOutputCountOnly") is True:
        return (
            "output-count-varint-mismatch",
            [
                "output-count-varint-mismatch",
                "coinb2-segmentation-boundary-mismatch",
                "ambiguous-output-layout-mismatch",
            ],
            True,
            False,
        )

    if output_layout_variant_target_matches.get("movePlaceholderToEnd") is True:
        return (
            "output-order-mismatch",
            [
                "output-order-mismatch",
                "ambiguous-output-layout-mismatch",
            ],
            False,
            False,
        )

    non_placeholder_output_mismatch = any(
        output_layout_variant_target_matches.get(variant_name) is True
        for variant_name in non_placeholder_variant_names
    )
    if non_placeholder_output_mismatch:
        return (
            "non-placeholder-output-mismatch",
            [
                "non-placeholder-output-mismatch",
                "ambiguous-output-layout-mismatch",
            ],
            False,
            True,
        )

    return (
        "ambiguous-output-layout-mismatch",
        [
            "ambiguous-output-layout-mismatch",
            "unknown-output-layout-mismatch",
        ],
        False,
        False,
    )


def _build_authoritative_output_reference_diagnostic(
    cached_job: Any,
    *,
    local_output_summaries: list[dict[str, Any]],
    local_coinb2_hex: str,
) -> dict[str, Any]:
    authoritative_context = getattr(cached_job, "authoritative_context", None)
    if not isinstance(authoritative_context, dict):
        return {
            "authoritativeReferenceCaptured": False,
            "authoritativeCoinbaseAvailable": False,
            "authoritativeOutputLayoutAvailable": False,
            "authoritativeComparisonResult": "unavailable",
            "authoritativeMismatchFieldNames": [],
            "firstAuthoritativeMismatchIndex": None,
            "authoritativeMismatchSourceCandidates": [
                "unknown-authoritative-output-mismatch"
            ],
            "localVsAuthoritativeCoinbaseHashEqual": None,
            "localVsAuthoritativeOutputLayoutEqual": None,
        }

    authoritative_output_summaries = authoritative_context.get("outputSummaries")
    output_layout_available = isinstance(authoritative_output_summaries, list)
    if not output_layout_available:
        return {
            "authoritativeReferenceCaptured": authoritative_context.get(
                "referenceCaptured"
            )
            is True,
            "authoritativeCoinbaseAvailable": authoritative_context.get(
                "authoritativeCoinbaseAvailable"
            )
            is True,
            "authoritativeOutputLayoutAvailable": False,
            "authoritativeComparisonResult": "unavailable",
            "authoritativeMismatchFieldNames": [],
            "firstAuthoritativeMismatchIndex": None,
            "authoritativeMismatchSourceCandidates": [
                "unknown-authoritative-output-mismatch"
            ],
            "localVsAuthoritativeCoinbaseHashEqual": None,
            "localVsAuthoritativeOutputLayoutEqual": None,
        }

    mismatch_fields: list[str] = []
    first_mismatch_index: int | None = None
    local_vs_authoritative_output_layout_equal = True
    local_count = len(local_output_summaries)
    authoritative_count = len(authoritative_output_summaries)
    if local_count != authoritative_count:
        mismatch_fields.append("outputCount")
        first_mismatch_index = min(local_count, authoritative_count)
        local_vs_authoritative_output_layout_equal = False

    for index in range(min(local_count, authoritative_count)):
        local_output = local_output_summaries[index]
        authoritative_output = authoritative_output_summaries[index]
        if local_output.get("amount") != authoritative_output.get("amount"):
            mismatch_fields.append("outputAmount")
            local_vs_authoritative_output_layout_equal = False
            if first_mismatch_index is None:
                first_mismatch_index = index
        if local_output.get("scriptLength") != authoritative_output.get("scriptLength"):
            mismatch_fields.append("scriptPubKeyLength")
            local_vs_authoritative_output_layout_equal = False
            if first_mismatch_index is None:
                first_mismatch_index = index
        if local_output.get("scriptHex") != authoritative_output.get("scriptHex"):
            mismatch_fields.append("scriptPubKeyBytes")
            local_vs_authoritative_output_layout_equal = False
            if first_mismatch_index is None:
                first_mismatch_index = index

    local_coinb2_digest = None
    try:
        local_coinb2_digest = hashlib.sha256(bytes.fromhex(local_coinb2_hex)).hexdigest()[
            :24
        ]
    except ValueError:
        local_coinb2_digest = None
    authoritative_coinb2_digest = authoritative_context.get("coinb2Digest")
    if (
        local_vs_authoritative_output_layout_equal
        and isinstance(local_coinb2_digest, str)
        and isinstance(authoritative_coinb2_digest, str)
        and local_coinb2_digest != authoritative_coinb2_digest
    ):
        mismatch_fields.append("coinb2Shaping")
        first_mismatch_index = 0
        local_vs_authoritative_output_layout_equal = False

    mismatch_fields = list(dict.fromkeys(mismatch_fields))
    authoritative_mismatch_source_candidates: list[str] = []
    if mismatch_fields:
        if mismatch_fields == ["outputAmount"]:
            authoritative_mismatch_source_candidates.append(
                "authoritative-output-amount-mismatch"
            )
        elif mismatch_fields == ["scriptPubKeyLength"]:
            authoritative_mismatch_source_candidates.append(
                "authoritative-scriptpubkey-length-mismatch"
            )
        elif mismatch_fields == ["scriptPubKeyBytes"]:
            authoritative_mismatch_source_candidates.append(
                "authoritative-scriptpubkey-bytes-mismatch"
            )
        elif mismatch_fields == ["coinb2Shaping"]:
            authoritative_mismatch_source_candidates.append(
                "authoritative-coinb2-shaping-mismatch"
            )
        elif mismatch_fields == ["outputCount"]:
            authoritative_mismatch_source_candidates.append(
                "authoritative-output-vector-mismatch"
            )
        else:
            authoritative_mismatch_source_candidates.extend(
                [
                    "ambiguous-authoritative-output-mismatch",
                    "unknown-authoritative-output-mismatch",
                ]
            )

    authoritative_script_hexes = [
        summary.get("scriptHex")
        for summary in authoritative_output_summaries
        if isinstance(summary, dict)
    ]
    return {
        "authoritativeReferenceCaptured": authoritative_context.get("referenceCaptured")
        is True,
        "authoritativeCoinbaseAvailable": authoritative_context.get(
            "authoritativeCoinbaseAvailable"
        )
        is True,
        "authoritativeOutputLayoutAvailable": authoritative_context.get(
            "authoritativeOutputLayoutAvailable"
        )
        is True,
        "authoritativeCoinbaseSummary": {
            "coinb1HexLength": authoritative_context.get("coinb1HexLength"),
            "coinb2HexLength": authoritative_context.get("coinb2HexLength"),
            "coinb2Digest": authoritative_coinb2_digest,
            "authoritativeCoinbaseBytesAvailable": authoritative_context.get(
                "authoritativeCoinbaseAvailable"
            )
            is True,
        },
        "authoritativeOutputSummaries": authoritative_output_summaries,
        "authoritativeOutputCount": authoritative_count,
        "authoritativeOutputAmountSummary": {
            "amounts": [
                summary.get("amount")
                for summary in authoritative_output_summaries
                if isinstance(summary, dict)
            ],
            "total": sum(
                summary.get("amount", 0)
                for summary in authoritative_output_summaries
                if isinstance(summary, dict) and isinstance(summary.get("amount"), int)
            ),
        },
        "authoritativeScriptSummary": {
            "scriptLengths": [
                summary.get("scriptLength")
                for summary in authoritative_output_summaries
                if isinstance(summary, dict)
            ],
            "scriptsDigest": hashlib.sha256(
                json.dumps(authoritative_script_hexes, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()[:24],
        },
        "authoritativeComparisonResult": (
            "equal" if local_vs_authoritative_output_layout_equal else "mismatch"
        ),
        "authoritativeMismatchFieldNames": mismatch_fields,
        "firstAuthoritativeMismatchIndex": first_mismatch_index,
        "authoritativeMismatchSourceCandidates": authoritative_mismatch_source_candidates,
        "localVsAuthoritativeCoinbaseHashEqual": None,
        "localVsAuthoritativeOutputLayoutEqual": local_vs_authoritative_output_layout_equal,
    }


def _build_local_coinbase_segment_summaries(
    *,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
) -> dict[str, dict[str, Any]]:
    coinb1_bytes = bytes.fromhex(coinb1_hex)
    coinb2_bytes = bytes.fromhex(coinb2_hex)
    prefix_end = _script_length_varint_offset(coinb1_bytes)
    declared_script_length, after_varint = _decode_varint_at(coinb1_bytes, prefix_end)
    output_count, after_output_count = _decode_varint_at(coinb2_bytes, 4)
    total_extranonce_bytes = (len(extranonce1_hex) + len(extranonce2_hex)) // 2
    return {
        "coinbasePrefixBytes": {
            "offset": 0,
            "hexLength": prefix_end * 2,
            "hex": coinb1_bytes[:prefix_end].hex(),
            "digest": hashlib.sha256(coinb1_bytes[:prefix_end]).hexdigest()[:24],
        },
        "coinbaseLengthVarint": {
            "offset": prefix_end,
            "hex": coinb1_bytes[prefix_end:after_varint].hex(),
            "declaredScriptSigBytes": declared_script_length,
        },
        "scriptSigTemplateBytes": {
            "offset": after_varint,
            "hexLength": len(coinb1_bytes[after_varint:]) * 2,
            "hex": coinb1_bytes[after_varint:].hex(),
            "digest": hashlib.sha256(coinb1_bytes[after_varint:]).hexdigest()[:24],
        },
        "extranonceRegion": {
            "offset": len(coinb1_bytes),
            "extranonce1HexLength": len(extranonce1_hex),
            "extranonce2HexLength": len(extranonce2_hex),
            "totalBytes": total_extranonce_bytes,
        },
        "postScriptSigSequence": {
            "offset": len(coinb1_bytes) + total_extranonce_bytes,
            "hex": coinb2_bytes[:4].hex(),
        },
        "outputCountVarint": {
            "offset": len(coinb1_bytes) + total_extranonce_bytes + 4,
            "hex": coinb2_bytes[4:after_output_count].hex(),
            "value": output_count,
        },
        "coinbaseTail": {
            "offset": len(coinb1_bytes) + total_extranonce_bytes + len(coinb2_bytes) - 4,
            "locktimeHex": coinb2_bytes[-4:].hex(),
        },
    }


def _build_authoritative_coinbase_segment_diagnostic(
    cached_job: Any,
    *,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
    output_vector_confirmed_equal: bool | None,
) -> dict[str, Any]:
    authoritative_context = getattr(cached_job, "authoritative_context", None)
    if not isinstance(authoritative_context, dict):
        return {
            "refinedCoinbaseSegmentReasonCode": "unknown-non-output-coinbase-mismatch",
            "coinbaseSegmentComparisonSummary": {"authoritativeAvailable": False},
            "localCoinbaseSegmentSummaries": None,
            "authoritativeCoinbaseSegmentSummaries": None,
            "matchingCoinbaseSegments": [],
            "mismatchingCoinbaseSegments": [],
            "firstCoinbaseSegmentMismatch": None,
            "firstCoinbaseSegmentMismatchOffset": None,
            "coinbaseSegmentMismatchFieldNames": [],
            "coinbaseSegmentMismatchSourceCandidates": [
                "unknown-non-output-coinbase-mismatch"
            ],
            "outputVectorConfirmedEqual": output_vector_confirmed_equal,
            "nonOutputCoinbaseMismatchSuspected": None,
            "coinbaseTailSummary": None,
            "scriptSigAuthoritativeAvailable": False,
            "extranonceRegionSummary": None,
            "localVsAuthoritativeNonOutputSegmentsEqual": None,
        }

    authoritative_segments = authoritative_context.get("coinbaseSegmentSummaries")
    if not isinstance(authoritative_segments, dict):
        return {
            "refinedCoinbaseSegmentReasonCode": "unknown-non-output-coinbase-mismatch",
            "coinbaseSegmentComparisonSummary": {"authoritativeAvailable": False},
            "localCoinbaseSegmentSummaries": None,
            "authoritativeCoinbaseSegmentSummaries": None,
            "matchingCoinbaseSegments": [],
            "mismatchingCoinbaseSegments": [],
            "firstCoinbaseSegmentMismatch": None,
            "firstCoinbaseSegmentMismatchOffset": None,
            "coinbaseSegmentMismatchFieldNames": [],
            "coinbaseSegmentMismatchSourceCandidates": [
                "unknown-non-output-coinbase-mismatch"
            ],
            "outputVectorConfirmedEqual": output_vector_confirmed_equal,
            "nonOutputCoinbaseMismatchSuspected": None,
            "coinbaseTailSummary": None,
            "scriptSigAuthoritativeAvailable": False,
            "extranonceRegionSummary": None,
            "localVsAuthoritativeNonOutputSegmentsEqual": None,
        }

    local_segments = _build_local_coinbase_segment_summaries(
        coinb1_hex=coinb1_hex,
        coinb2_hex=coinb2_hex,
        extranonce1_hex=extranonce1_hex,
        extranonce2_hex=extranonce2_hex,
    )
    segment_order = [
        "coinbasePrefixBytes",
        "coinbaseLengthVarint",
        "scriptSigTemplateBytes",
        "extranonceRegion",
        "postScriptSigSequence",
        "outputCountVarint",
        "coinbaseTail",
    ]
    matching_segments: list[str] = []
    mismatching_segments: list[str] = []
    mismatch_field_names: list[str] = []
    first_mismatch = None
    first_mismatch_offset = None
    for segment_name in segment_order:
        local_segment = local_segments.get(segment_name, {})
        authoritative_segment = authoritative_segments.get(segment_name, {})
        segment_match = True
        segment_fields: list[str] = []
        if segment_name == "extranonceRegion":
            if local_segment.get("offset") != authoritative_segment.get("offset"):
                segment_match = False
                segment_fields.append("offset")
            if (
                local_segment.get("totalBytes")
                != authoritative_segment.get("expectedTotalBytes")
            ):
                segment_match = False
                segment_fields.append("totalBytes")
        elif segment_name == "coinbaseLengthVarint":
            if local_segment.get("hex") != authoritative_segment.get("hex"):
                segment_match = False
                segment_fields.append("hex")
            if (
                local_segment.get("declaredScriptSigBytes")
                != authoritative_segment.get("declaredScriptSigBytes")
            ):
                segment_match = False
                segment_fields.append("declaredScriptSigBytes")
        elif segment_name == "outputCountVarint":
            if local_segment.get("hex") != authoritative_segment.get("hex"):
                segment_match = False
                segment_fields.append("hex")
            if local_segment.get("value") != authoritative_segment.get("value"):
                segment_match = False
                segment_fields.append("value")
        elif segment_name == "coinbaseTail":
            if (
                local_segment.get("locktimeHex")
                != authoritative_segment.get("locktimeHex")
            ):
                segment_match = False
                segment_fields.append("locktimeHex")
        else:
            if local_segment.get("hex") != authoritative_segment.get("hex"):
                segment_match = False
                segment_fields.append("hex")

        if segment_match:
            matching_segments.append(segment_name)
            continue

        mismatching_segments.append(segment_name)
        mismatch_field_names.extend(segment_fields or [segment_name])
        if first_mismatch is None:
            first_mismatch = segment_name
            first_mismatch_offset = authoritative_segment.get("offset")

    mismatch_field_names = list(dict.fromkeys(mismatch_field_names))
    local_vs_authoritative_non_output_equal = len(mismatching_segments) == 0
    if local_vs_authoritative_non_output_equal and output_vector_confirmed_equal is True:
        reason_code = "coinbase-to-merkle-handoff-ambiguity"
        source_candidates = ["coinbase-to-merkle-handoff-ambiguity"]
        non_output_mismatch_suspected = False
    elif mismatching_segments == ["coinbasePrefixBytes"]:
        reason_code = "coinbase-prefix-mismatch"
        source_candidates = ["coinbase-prefix-mismatch"]
        non_output_mismatch_suspected = True
    elif mismatching_segments == ["scriptSigTemplateBytes"]:
        reason_code = "scriptSig-bytes-mismatch"
        source_candidates = ["scriptSig-bytes-mismatch"]
        non_output_mismatch_suspected = True
    elif mismatching_segments == ["extranonceRegion"]:
        reason_code = "extranonce-region-mismatch"
        source_candidates = ["extranonce-region-mismatch"]
        non_output_mismatch_suspected = True
    elif mismatching_segments == ["coinbaseLengthVarint"]:
        reason_code = "coinbase-length-encoding-mismatch"
        source_candidates = ["coinbase-length-encoding-mismatch"]
        non_output_mismatch_suspected = True
    elif mismatching_segments == ["coinbaseTail"]:
        reason_code = "coinbase-tail-mismatch"
        source_candidates = ["coinbase-tail-mismatch"]
        non_output_mismatch_suspected = True
    elif mismatching_segments:
        reason_code = "ambiguous-nonoutput-coinbase-mismatch"
        source_candidates = [
            "ambiguous-nonoutput-coinbase-mismatch",
            "normalized-template-nonoutput-mismatch",
        ]
        non_output_mismatch_suspected = True
    else:
        reason_code = "unknown-non-output-coinbase-mismatch"
        source_candidates = ["unknown-non-output-coinbase-mismatch"]
        non_output_mismatch_suspected = None

    return {
        "refinedCoinbaseSegmentReasonCode": reason_code,
        "coinbaseSegmentComparisonSummary": {
            "authoritativeAvailable": True,
            "authoritativeSegmentsAvailable": sorted(authoritative_segments.keys()),
            "localSegmentsAvailable": sorted(local_segments.keys()),
        },
        "localCoinbaseSegmentSummaries": local_segments,
        "authoritativeCoinbaseSegmentSummaries": authoritative_segments,
        "matchingCoinbaseSegments": matching_segments,
        "mismatchingCoinbaseSegments": mismatching_segments,
        "firstCoinbaseSegmentMismatch": first_mismatch,
        "firstCoinbaseSegmentMismatchOffset": first_mismatch_offset,
        "coinbaseSegmentMismatchFieldNames": mismatch_field_names,
        "coinbaseSegmentMismatchSourceCandidates": source_candidates,
        "outputVectorConfirmedEqual": output_vector_confirmed_equal,
        "nonOutputCoinbaseMismatchSuspected": non_output_mismatch_suspected,
        "coinbaseTailSummary": {
            "local": local_segments.get("coinbaseTail"),
            "authoritative": authoritative_segments.get("coinbaseTail"),
        },
        "scriptSigAuthoritativeAvailable": True,
        "extranonceRegionSummary": {
            "local": local_segments.get("extranonceRegion"),
            "authoritative": authoritative_segments.get("extranonceRegion"),
        },
        "localVsAuthoritativeNonOutputSegmentsEqual": local_vs_authoritative_non_output_equal,
    }


def _build_full_coinbase_handoff_diagnostic(
    cached_job: Any,
    *,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
    header_merkle_root_hex: str | None,
    merkle_branch: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    authoritative_context = getattr(cached_job, "authoritative_context", None)
    authoritative_reference_captured = isinstance(authoritative_context, dict) and (
        authoritative_context.get("referenceCaptured") is True
    )
    try:
        authoritative_full_coinbase = bytes.fromhex(
            f"{coinb1_hex}{extranonce1_hex}{extranonce2_hex}{coinb2_hex}"
        )
        local_full_coinbase = bytes.fromhex(
            f"{coinb1_hex}{extranonce1_hex}{extranonce2_hex}{coinb2_hex}"
        )
    except ValueError:
        return {
            "authoritativeFullCoinbaseAvailable": False,
            "localFullCoinbaseAvailable": False,
            "authoritativeFullCoinbaseHexSummary": None,
            "localFullCoinbaseHexSummary": None,
            "fullCoinbaseBytesEqual": None,
            "firstFullCoinbaseMismatchOffset": None,
            "authoritativeCoinbaseLeafHash": None,
            "localCoinbaseLeafHash": None,
            "coinbaseLeafHashEqual": None,
            "authoritativeMerkleLeafInputSummary": None,
            "localMerkleLeafInputSummary": None,
            "merkleLeafNormalizationEqual": None,
            "refinedHandoffReasonCode": "unknown-handoff-mismatch",
        }

    authoritative_leaf_hash = _double_sha256(authoritative_full_coinbase)
    local_leaf_hash = _double_sha256(local_full_coinbase)
    authoritative_computed_merkle_root = _apply_merkle_branch(
        authoritative_leaf_hash, merkle_branch
    ).hex()
    local_computed_merkle_root = _apply_merkle_branch(
        local_leaf_hash, merkle_branch
    ).hex()

    full_coinbase_bytes_equal = authoritative_full_coinbase == local_full_coinbase
    first_mismatch_offset = None
    if not full_coinbase_bytes_equal:
        max_common = min(len(authoritative_full_coinbase), len(local_full_coinbase))
        for index in range(max_common):
            if authoritative_full_coinbase[index] != local_full_coinbase[index]:
                first_mismatch_offset = index
                break
        if first_mismatch_offset is None and len(authoritative_full_coinbase) != len(
            local_full_coinbase
        ):
            first_mismatch_offset = max_common

    coinbase_leaf_hash_equal = authoritative_leaf_hash == local_leaf_hash
    authoritative_leaf_summary = {
        "source": "normalized-job-cache-plus-submit-extranonce",
        "merkleBranchLength": len(merkle_branch),
        "leafHash": authoritative_leaf_hash.hex(),
        "computedMerkleRoot": authoritative_computed_merkle_root,
        "headerMerkleRoot": header_merkle_root_hex,
    }
    local_leaf_summary = {
        "source": "failed-share-local-reconstruction",
        "merkleBranchLength": len(merkle_branch),
        "leafHash": local_leaf_hash.hex(),
        "computedMerkleRoot": local_computed_merkle_root,
        "headerMerkleRoot": header_merkle_root_hex,
    }
    merkle_leaf_normalization_equal = (
        authoritative_leaf_summary.get("merkleBranchLength")
        == local_leaf_summary.get("merkleBranchLength")
        and authoritative_leaf_summary.get("leafHash")
        == local_leaf_summary.get("leafHash")
        and authoritative_leaf_summary.get("computedMerkleRoot")
        == local_leaf_summary.get("computedMerkleRoot")
    )

    if not authoritative_reference_captured:
        refined_reason_code = "unknown-handoff-mismatch"
    elif not full_coinbase_bytes_equal:
        refined_reason_code = "full-coinbase-serialization-mismatch"
    elif not coinbase_leaf_hash_equal:
        refined_reason_code = "coinbase-leaf-hash-mismatch"
    elif not merkle_leaf_normalization_equal:
        refined_reason_code = "merkle-leaf-normalization-mismatch"
    elif (
        len(merkle_branch) == 0
        and isinstance(header_merkle_root_hex, str)
        and local_computed_merkle_root != header_merkle_root_hex
    ):
        refined_reason_code = "single-leaf-merkle-handoff-mismatch"
    else:
        refined_reason_code = "unknown-handoff-mismatch"

    return {
        "authoritativeFullCoinbaseAvailable": authoritative_reference_captured,
        "localFullCoinbaseAvailable": True,
        "authoritativeFullCoinbaseHexSummary": {
            "source": "normalized-job-cache-plus-submit-extranonce",
            "hexLength": len(authoritative_full_coinbase) * 2,
            "digest": hashlib.sha256(authoritative_full_coinbase).hexdigest()[:24],
            "hexPrefix": authoritative_full_coinbase[:16].hex(),
            "hexSuffix": authoritative_full_coinbase[-16:].hex(),
        },
        "localFullCoinbaseHexSummary": {
            "source": "failed-share-local-reconstruction",
            "hexLength": len(local_full_coinbase) * 2,
            "digest": hashlib.sha256(local_full_coinbase).hexdigest()[:24],
            "hexPrefix": local_full_coinbase[:16].hex(),
            "hexSuffix": local_full_coinbase[-16:].hex(),
        },
        "fullCoinbaseBytesEqual": full_coinbase_bytes_equal,
        "firstFullCoinbaseMismatchOffset": first_mismatch_offset,
        "authoritativeCoinbaseLeafHash": authoritative_leaf_hash.hex(),
        "localCoinbaseLeafHash": local_leaf_hash.hex(),
        "coinbaseLeafHashEqual": coinbase_leaf_hash_equal,
        "authoritativeMerkleLeafInputSummary": authoritative_leaf_summary,
        "localMerkleLeafInputSummary": local_leaf_summary,
        "merkleLeafNormalizationEqual": merkle_leaf_normalization_equal,
        "refinedHandoffReasonCode": refined_reason_code,
    }


def _build_final_header80_probe_diagnostic(
    cached_job: Any,
    *,
    header: bytes,
    extranonce1_hex: str,
    extranonce2_hex: str,
    ntime_hex: str,
    nonce_hex: str,
    coinbase_hash_hex: str | None,
    merkle_branch: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    version_hex = _normalize_optional_hex(getattr(cached_job, "version", None))
    prevhash_hex = _normalize_optional_hex(getattr(cached_job, "prevhash", None))
    bits_hex = _normalize_optional_hex(getattr(cached_job, "nbits", None))
    if (
        version_hex is None
        or prevhash_hex is None
        or bits_hex is None
        or len(header) != 80
    ):
        return {
            "authoritativeHeader80Available": False,
            "localHeader80Available": len(header) == 80,
            "authoritativeHeader80HexSummary": None,
            "independentAuthoritativeHeader80Available": False,
            "independentAuthoritativeHeader80HexSummary": None,
            "independentAuthoritativeShareHash": None,
            "localHeader80HexSummary": (
                {
                    "hexLength": len(header) * 2,
                    "hexPrefix": header[:16].hex(),
                    "hexSuffix": header[-16:].hex(),
                }
                if len(header) == 80
                else None
            ),
            "header80BytesEqual": None,
            "localVsIndependentAuthoritativeHeader80Equal": None,
            "normalizedVsIndependentAuthoritativeHeader80Equal": None,
            "firstHeader80MismatchOffset": None,
            "headerFieldComparisonSummary": None,
            "headerFieldEquality": None,
            "prevhashByteOrderSuspected": None,
            "nonceFieldMappingSuspected": None,
            "ntimeFieldMappingSuspected": None,
            "bitsFieldMappingSuspected": None,
            "refinedHeaderAssemblyReasonCode": "unknown-header-assembly-mismatch",
        }

    local_field_bytes = {
        field_name: header[offset : offset + size]
        for field_name, offset, size in HEADER80_FIELD_LAYOUT
    }
    try:
        authoritative_merkle_root = (
            _apply_merkle_branch(bytes.fromhex(coinbase_hash_hex), merkle_branch)
            if isinstance(coinbase_hash_hex, str)
            else local_field_bytes["merkleRoot"]
        )
        authoritative_field_bytes = {
            "version": bytes.fromhex(version_hex)[::-1],
            "prevHash": bytes.fromhex(prevhash_hex)[::-1],
            "merkleRoot": authoritative_merkle_root,
            "ntime": bytes.fromhex(ntime_hex)[::-1],
            "bits": bytes.fromhex(bits_hex)[::-1],
            "nonce": bytes.fromhex(nonce_hex)[::-1],
        }
    except ValueError:
        return {
            "authoritativeHeader80Available": False,
            "localHeader80Available": True,
            "authoritativeHeader80HexSummary": None,
            "independentAuthoritativeHeader80Available": False,
            "independentAuthoritativeHeader80HexSummary": None,
            "independentAuthoritativeShareHash": None,
            "localHeader80HexSummary": {
                "hexLength": len(header) * 2,
                "hexPrefix": header[:16].hex(),
                "hexSuffix": header[-16:].hex(),
            },
            "header80BytesEqual": None,
            "localVsIndependentAuthoritativeHeader80Equal": None,
            "normalizedVsIndependentAuthoritativeHeader80Equal": None,
            "firstHeader80MismatchOffset": None,
            "headerFieldComparisonSummary": None,
            "headerFieldEquality": None,
            "prevhashByteOrderSuspected": None,
            "nonceFieldMappingSuspected": None,
            "ntimeFieldMappingSuspected": None,
            "bitsFieldMappingSuspected": None,
            "refinedHeaderAssemblyReasonCode": "unknown-header-assembly-mismatch",
        }

    authoritative_header = _assemble_header80_from_field_bytes(
        authoritative_field_bytes
    )
    independent_authoritative_reference = (
        _build_independent_authoritative_header80_reference(
            cached_job,
            extranonce1_hex=extranonce1_hex,
            extranonce2_hex=extranonce2_hex,
            ntime_hex=ntime_hex,
            nonce_hex=nonce_hex,
        )
    )
    independent_authoritative_header = (
        independent_authoritative_reference.get("header80")
        if isinstance(independent_authoritative_reference, dict)
        else None
    )
    header_field_equality = {
        field_name: authoritative_field_bytes[field_name] == local_field_bytes[field_name]
        for field_name, _offset, _size in HEADER80_FIELD_LAYOUT
    }
    header80_bytes_equal = authoritative_header == header
    first_mismatch_offset = None
    if not header80_bytes_equal:
        for index, (authoritative_byte, local_byte) in enumerate(
            zip(authoritative_header, header, strict=True)
        ):
            if authoritative_byte != local_byte:
                first_mismatch_offset = index
                break

    prevhash_byte_order_suspected = (
        header_field_equality["prevHash"] is False
        and local_field_bytes["prevHash"] == bytes.fromhex(prevhash_hex)
    )
    ntime_field_mapping_suspected = (
        header_field_equality["ntime"] is False
        and local_field_bytes["ntime"] == bytes.fromhex(ntime_hex)
    )
    bits_field_mapping_suspected = (
        header_field_equality["bits"] is False
        and local_field_bytes["bits"] == bytes.fromhex(bits_hex)
    )
    nonce_field_mapping_suspected = (
        header_field_equality["nonce"] is False
        and local_field_bytes["nonce"] == bytes.fromhex(nonce_hex)
    )

    if prevhash_byte_order_suspected:
        refined_reason = "prevhash-byte-order-mismatch"
    elif header_field_equality["ntime"] is False:
        refined_reason = "ntime-field-mismatch"
    elif header_field_equality["bits"] is False:
        refined_reason = "bits-field-mismatch"
    elif header_field_equality["nonce"] is False:
        refined_reason = "nonce-field-mismatch"
    elif all(header_field_equality.values()) and not header80_bytes_equal:
        refined_reason = "parsed-fields-equal-but-header-differs"
    elif any(value is False for value in header_field_equality.values()):
        refined_reason = "final-header-packing-mismatch"
    else:
        refined_reason = "unknown-header-assembly-mismatch"

    return {
        "authoritativeHeader80Available": True,
        "localHeader80Available": True,
        "authoritativeHeader80HexSummary": {
            "hexLength": len(authoritative_header) * 2,
            "hexPrefix": authoritative_header[:16].hex(),
            "hexSuffix": authoritative_header[-16:].hex(),
        },
        "independentAuthoritativeHeader80Available": isinstance(
            independent_authoritative_header, bytes
        ),
        "independentAuthoritativeHeader80HexSummary": (
            {
                "hexLength": len(independent_authoritative_header) * 2,
                "hexPrefix": independent_authoritative_header[:16].hex(),
                "hexSuffix": independent_authoritative_header[-16:].hex(),
            }
            if isinstance(independent_authoritative_header, bytes)
            else None
        ),
        "independentAuthoritativeShareHash": (
            independent_authoritative_reference.get("shareHash")
            if isinstance(independent_authoritative_reference, dict)
            else None
        ),
        "localHeader80HexSummary": {
            "hexLength": len(header) * 2,
            "hexPrefix": header[:16].hex(),
            "hexSuffix": header[-16:].hex(),
        },
        "header80BytesEqual": header80_bytes_equal,
        "localVsIndependentAuthoritativeHeader80Equal": (
            independent_authoritative_header == header
            if isinstance(independent_authoritative_header, bytes)
            else None
        ),
        "normalizedVsIndependentAuthoritativeHeader80Equal": (
            independent_authoritative_header == authoritative_header
            if isinstance(independent_authoritative_header, bytes)
            else None
        ),
        "firstHeader80MismatchOffset": first_mismatch_offset,
        "headerFieldComparisonSummary": {
            field_name: {
                "authoritativeHex": authoritative_field_bytes[field_name].hex(),
                "localHex": local_field_bytes[field_name].hex(),
                "offset": offset,
                "length": size,
            }
            for field_name, offset, size in HEADER80_FIELD_LAYOUT
        },
        "headerFieldEquality": {
            "version": header_field_equality["version"],
            "prevhash": header_field_equality["prevHash"],
            "merkleRoot": header_field_equality["merkleRoot"],
            "ntime": header_field_equality["ntime"],
            "bits": header_field_equality["bits"],
            "nonce": header_field_equality["nonce"],
        },
        "prevhashByteOrderSuspected": prevhash_byte_order_suspected,
        "nonceFieldMappingSuspected": nonce_field_mapping_suspected,
        "ntimeFieldMappingSuspected": ntime_field_mapping_suspected,
        "bitsFieldMappingSuspected": bits_field_mapping_suspected,
        "refinedHeaderAssemblyReasonCode": refined_reason,
    }


def _build_corrected_placeholder_output_comparison(
    *,
    cached_job: Any,
    header: bytes,
    coinb1_hex: str,
    coinb2_hex: str,
    extranonce1_hex: str,
    extranonce2_hex: str,
    coinbase_hash: str | None,
    merkle_root: str | None,
    merkle_branch: tuple[str, ...] | list[str],
    target_value: str,
) -> dict[str, Any]:
    parsed_coinb2 = _parse_coinb2_outputs(coinb2_hex)
    if not parsed_coinb2.get("valid"):
        return {
            "correctedPlaceholderPayoutVariantTested": False,
            "refinedOutputLayoutReasonCode": "coinb2-segmentation-boundary-mismatch",
            "comparisonAgainstCurrentBaseline": {
                "baselinePath": "current-placeholder-payout-output",
                "experimentalPath": "drop-placeholder-payout-output",
                "variantAvailable": False,
            },
            "placeholderPayoutVariantEffect": "not-tested-invalid-coinb2",
            "coinb2SegmentationSummary": {
                "validParsedCoinb2": False,
                "baselineCoinb2HexLength": len(coinb2_hex),
            },
            "coinb2BoundarySuspected": True,
            "nonPlaceholderOutputMismatchSuspected": False,
            "outputLayoutMismatchSourceCandidates": [
                "coinb2-segmentation-boundary-mismatch",
                "unknown-output-layout-mismatch",
            ],
        }

    outputs = parsed_coinb2.get("outputs", [])
    placeholder_output = next(
        (
            output
            for output in outputs
            if output.get("placeholderScript") is True
            and isinstance(output.get("amount"), int)
            and output["amount"] >= 0
        ),
        None,
    )
    if placeholder_output is None:
        return {
            "correctedPlaceholderPayoutVariantTested": False,
            "refinedOutputLayoutReasonCode": "unknown-output-layout-mismatch",
            "comparisonAgainstCurrentBaseline": {
                "baselinePath": "current-placeholder-payout-output",
                "experimentalPath": "drop-placeholder-payout-output",
                "variantAvailable": False,
            },
            "placeholderPayoutVariantEffect": "not-tested-no-placeholder-output",
            "baselineOutputSummaries": [
                _summarize_coinb2_output(output) for output in outputs
            ],
            "coinb2SegmentationSummary": {
                "validParsedCoinb2": True,
                "sequenceHex": parsed_coinb2.get("sequenceHex"),
                "locktimeHex": parsed_coinb2.get("locktimeHex"),
                "baselineOutputCount": parsed_coinb2.get("outputCount"),
                "parsedOutputsCount": len(outputs),
            },
            "coinb2BoundarySuspected": False,
            "nonPlaceholderOutputMismatchSuspected": False,
            "outputLayoutMismatchSourceCandidates": [
                "unknown-output-layout-mismatch",
            ],
        }

    retained_outputs = [
        output
        for output in outputs
        if output.get("index") != placeholder_output.get("index")
    ]
    corrected_coinb2_hex = _serialize_coinb2_outputs(
        sequence_hex=parsed_coinb2["sequenceHex"],
        outputs=retained_outputs,
        locktime_hex=parsed_coinb2["locktimeHex"],
    )
    variant_payloads: dict[str, str] = {
        "dropPlaceholderOutput": corrected_coinb2_hex,
        "decrementOutputCountOnly": _serialize_coinb2_outputs(
            sequence_hex=parsed_coinb2["sequenceHex"],
            outputs=outputs,
            locktime_hex=parsed_coinb2["locktimeHex"],
            output_count_override=max(0, len(outputs) - 1),
        ),
        "movePlaceholderToEnd": _serialize_coinb2_outputs(
            sequence_hex=parsed_coinb2["sequenceHex"],
            outputs=retained_outputs + [placeholder_output],
            locktime_hex=parsed_coinb2["locktimeHex"],
        ),
    }
    non_placeholder_variant_names: list[str] = []
    for output in outputs:
        if output.get("index") == placeholder_output.get("index"):
            continue
        variant_name = f"dropNonPlaceholderOutput{output.get('index')}"
        non_placeholder_variant_names.append(variant_name)
        variant_payloads[variant_name] = _serialize_coinb2_outputs(
            sequence_hex=parsed_coinb2["sequenceHex"],
            outputs=[
                candidate
                for candidate in outputs
                if candidate.get("index") != output.get("index")
            ],
            locktime_hex=parsed_coinb2["locktimeHex"],
        )

    variant_results = {
        variant_name: _evaluate_coinb2_output_layout_variant(
            header=header,
            coinb1_hex=coinb1_hex,
            coinb2_hex=variant_coinb2_hex,
            extranonce1_hex=extranonce1_hex,
            extranonce2_hex=extranonce2_hex,
            merkle_branch=merkle_branch,
            target_value=target_value,
        )
        for variant_name, variant_coinb2_hex in variant_payloads.items()
    }
    output_layout_variant_target_matches = {
        variant_name: variant_data.get("targetMatch")
        for variant_name, variant_data in variant_results.items()
    }
    (
        refined_output_layout_reason_code,
        output_layout_source_candidates,
        coinb2_boundary_suspected,
        non_placeholder_output_mismatch_suspected,
    ) = _classify_output_layout_reason_code(
        parsed_coinb2=parsed_coinb2,
        output_layout_variant_target_matches=output_layout_variant_target_matches,
        non_placeholder_variant_names=non_placeholder_variant_names,
    )

    corrected_variant = variant_results["dropPlaceholderOutput"]
    corrected_coinbase_hash = corrected_variant.get("coinbaseHash")
    corrected_merkle_root = corrected_variant.get("merkleRoot")
    corrected_header_hex = corrected_variant.get("header80")
    corrected_share_hash_hex = corrected_variant.get("shareHash")
    corrected_target_match = corrected_variant.get("targetMatch")
    corrected_comparison_result = corrected_variant.get("comparisonResult")
    would_remove_mismatch = corrected_target_match is True
    baseline_output_summaries = [_summarize_coinb2_output(output) for output in outputs]
    corrected_output_summaries = [
        _summarize_coinb2_output(output) for output in retained_outputs
    ]
    first_output_mismatch_index = _first_output_mismatch_index(
        baseline_output_summaries,
        corrected_output_summaries,
    )
    output_mismatch_field_names: list[str] = []
    if len(outputs) != len(retained_outputs):
        output_mismatch_field_names.append("outputCount")
    if placeholder_output.get("index") != len(outputs) - 1:
        output_mismatch_field_names.append("outputOrder")
    if isinstance(placeholder_output.get("amount"), int):
        output_mismatch_field_names.append("outputAmount")
    script_hex = placeholder_output.get("scriptHex")
    if isinstance(script_hex, str):
        output_mismatch_field_names.append("scriptPubKeyLength")
        output_mismatch_field_names.append("scriptPubKeyBytes")
    return {
        "correctedPlaceholderPayoutVariantTested": True,
        "refinedOutputLayoutReasonCode": refined_output_layout_reason_code,
        "correctedOutputLayoutHash": corrected_coinbase_hash,
        "correctedOutputLayoutMerkleRoot": corrected_merkle_root,
        "correctedOutputLayoutHeader80": corrected_header_hex,
        "correctedOutputLayoutShareHash": corrected_share_hash_hex,
        "correctedOutputLayoutTargetMatch": corrected_target_match,
        "correctedOutputLayoutComparisonResult": corrected_comparison_result,
        "baselineOutputSummaries": baseline_output_summaries,
        "correctedOutputSummaries": corrected_output_summaries,
        "outputsComparisonSummary": {
            "testedVariantNames": sorted(variant_results.keys()),
            "variantTargetMatches": output_layout_variant_target_matches,
            "variantComparisonResults": {
                variant_name: variant_data.get("comparisonResult")
                for variant_name, variant_data in variant_results.items()
            },
        },
        "outputCountComparison": {
            "baselineOutputCount": len(outputs),
            "correctedOutputCount": len(retained_outputs),
            "decrementOutputCountOnlyTargetMatch": output_layout_variant_target_matches.get(
                "decrementOutputCountOnly"
            ),
        },
        "outputOrderComparison": {
            "placeholderOutputIndex": placeholder_output.get("index"),
            "nonPlaceholderRelativeOrderPreserved": [
                output.get("index") for output in retained_outputs
            ]
            == sorted(output.get("index") for output in retained_outputs),
            "movePlaceholderToEndTargetMatch": output_layout_variant_target_matches.get(
                "movePlaceholderToEnd"
            ),
        },
        "outputAmountComparison": {
            "removedPlaceholderAmount": placeholder_output.get("amount"),
            "retainedNonPlaceholderAmounts": [
                output.get("amount") for output in retained_outputs
            ],
        },
        "outputScriptLengthComparison": {
            "removedPlaceholderScriptLength": (
                len(script_hex) // 2 if isinstance(script_hex, str) else None
            ),
            "retainedNonPlaceholderScriptLengths": [
                len(output.get("scriptHex", "")) // 2
                if isinstance(output.get("scriptHex"), str)
                else None
                for output in retained_outputs
            ],
        },
        "outputScriptBytesComparison": {
            "removedPlaceholderScriptHex": script_hex,
            "retainedNonPlaceholderScriptHex": [
                output.get("scriptHex") for output in retained_outputs
            ],
        },
        "firstOutputMismatchIndex": first_output_mismatch_index,
        "outputMismatchFieldNames": output_mismatch_field_names,
        "outputLayoutMismatchSourceCandidates": output_layout_source_candidates,
        "coinb2SegmentationSummary": {
            "validParsedCoinb2": True,
            "sequenceHex": parsed_coinb2.get("sequenceHex"),
            "locktimeHex": parsed_coinb2.get("locktimeHex"),
            "baselineOutputCount": parsed_coinb2.get("outputCount"),
            "parsedOutputsCount": len(outputs),
            "baselineCoinb2HexLength": len(coinb2_hex),
        },
        "coinb2BoundarySuspected": coinb2_boundary_suspected,
        "nonPlaceholderOutputMismatchSuspected": (
            non_placeholder_output_mismatch_suspected
        ),
        "outputLayoutVariantDeltaSummary": {
            "variantName": "drop-placeholder-payout-output",
            "baselineCoinb2HexLength": len(coinb2_hex),
            "correctedCoinb2HexLength": len(corrected_coinb2_hex),
            "baselineOutputsCount": parsed_coinb2.get("outputCount"),
            "correctedOutputsCount": len(retained_outputs),
            "placeholderMatchCount": sum(
                1 for output in outputs if output.get("placeholderScript") is True
            ),
            "removedOutputIndex": placeholder_output.get("index"),
            "removedOutputAmount": placeholder_output.get("amount"),
            "coinbaseHashChanged": corrected_coinbase_hash != coinbase_hash,
            "merkleRootChanged": corrected_merkle_root != merkle_root,
            "header80Changed": corrected_header_hex != header.hex(),
        },
        "placeholderPayoutVariantEffect": (
            "would-remove-mismatch"
            if would_remove_mismatch
            else "mismatch-unchanged"
        ),
        "wouldCorrectedOutputLayoutRemoveMismatch": would_remove_mismatch,
        "comparisonAgainstCurrentBaseline": {
            "baselinePath": "current-placeholder-payout-output",
            "experimentalPath": "drop-placeholder-payout-output",
            "baselineTargetMatch": False,
            "correctedTargetMatch": corrected_target_match,
        },
    }


def _classify_coinbase_reason_code(
    *,
    coinbase_assembly_target_matches: dict[str, bool | None],
    preimage_context: dict[str, Any],
) -> tuple[str, list[str], int | None, list[str]]:
    matched_groups = {
        variant_name
        for variant_name, matched in coinbase_assembly_target_matches.items()
        if matched is True
    }
    if len(matched_groups) > 1:
        return (
            "ambiguous-coinbase-assembly-stage",
            [
                "extranonce-placement-mismatch",
                "coinbase-prefix-boundary-mismatch",
                "coinbase-suffix-boundary-mismatch",
                "varint-or-length-encoding-mismatch",
                "ambiguous-coinbase-assembly-stage",
            ],
            None,
            [],
        )
    if "swapExtranonces" in matched_groups:
        return (
            "extranonce-placement-mismatch",
            ["extranonce-placement-mismatch", "scriptSig-assembly-mismatch"],
            None,
            ["extranonce1", "extranonce2"],
        )
    if "prependCombinedExtranonce" in matched_groups:
        return (
            "coinbase-prefix-boundary-mismatch",
            [
                "coinbase-prefix-boundary-mismatch",
                "coinbase-field-order-mismatch",
            ],
            0,
            ["coinbasePrefix", "extranoncePlacement"],
        )
    if "appendCombinedExtranonce" in matched_groups:
        return (
            "coinbase-suffix-boundary-mismatch",
            [
                "coinbase-suffix-boundary-mismatch",
                "coinbase-field-order-mismatch",
            ],
            None,
            ["coinbaseSuffix", "outputLayout"],
        )
    if (
        "scriptLengthMinusExtranonce" in matched_groups
        or "scriptLengthPlusExtranonce" in matched_groups
    ):
        return (
            "varint-or-length-encoding-mismatch",
            [
                "varint-or-length-encoding-mismatch",
                "scriptSig-assembly-mismatch",
            ],
            _script_length_varint_offset(bytes.fromhex("00" * 41)),
            ["scriptSigLength"],
        )

    if preimage_context.get("placeholderPayout") is True:
        return (
            "placeholder-payout-output-suspected",
            [
                "placeholder-payout-output-suspected",
                "output-layout-mismatch",
                "unknown-coinbase-assembly-stage",
            ],
            None,
            ["outputLayout", "placeholderPayout"],
        )
    if preimage_context.get("coinbaseOutputsCount", 0) > 0:
        return (
            "output-layout-mismatch",
            ["output-layout-mismatch", "unknown-coinbase-assembly-stage"],
            None,
            ["outputLayout"],
        )
    return (
        "unknown-coinbase-assembly-stage",
        ["unknown-coinbase-assembly-stage"],
        None,
        [],
    )


def _build_merkle_variant_target_matches(
    *,
    header: bytes,
    variant_roots: dict[str, dict[str, str | int | None]],
    target_value: str,
) -> dict[str, bool | None]:
    target_int = int(target_value, 16)
    results: dict[str, bool | None] = {}
    for variant_name, variant_data in variant_roots.items():
        merkle_root = variant_data.get("merkleRoot")
        if not isinstance(merkle_root, str):
            results[variant_name] = None
            continue
        try:
            candidate_hash = _calculate_pepepow_share_hash(
                _replace_header_merkle_root(header, merkle_root)
            )
        except (PepepowPowError, ValueError):
            results[variant_name] = None
            continue
        results[variant_name] = (
            int.from_bytes(candidate_hash, byteorder="big", signed=False) <= target_int
        )
    return results


def _build_branch_fold_variant_roots(
    *,
    coinbase_hash_hex: str | None,
    merkle_branch: tuple[str, ...] | list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(coinbase_hash_hex, str):
        return {}

    normalized_branch = [
        entry.strip().lower() for entry in merkle_branch if isinstance(entry, str)
    ]
    if not normalized_branch:
        return {
            "currentRule": {
                "merkleRoot": coinbase_hash_hex,
                "branchCount": 0,
                "firstDivergenceIndex": None,
            }
        }

    variant_definitions = {
        "currentRule": {
            "branch": normalized_branch,
            "reverse_sibling_bytes": True,
            "prepend_sibling": False,
        },
        "reverseBranchOrder": {
            "branch": list(reversed(normalized_branch)),
            "reverse_sibling_bytes": True,
            "prepend_sibling": False,
        },
        "sourceOrderSiblings": {
            "branch": normalized_branch,
            "reverse_sibling_bytes": False,
            "prepend_sibling": False,
        },
        "prependSibling": {
            "branch": normalized_branch,
            "reverse_sibling_bytes": True,
            "prepend_sibling": True,
        },
    }
    roots: dict[str, dict[str, Any]] = {}
    for variant_name, config in variant_definitions.items():
        current = bytes.fromhex(coinbase_hash_hex)
        first_divergence_index: int | None = None
        for index, sibling_hash in enumerate(config["branch"]):
            sibling_bytes = bytes.fromhex(sibling_hash)
            sibling = (
                sibling_bytes[::-1]
                if config["reverse_sibling_bytes"]
                else sibling_bytes
            )
            payload = (
                sibling + current
                if config["prepend_sibling"]
                else current + sibling
            )
            next_root = _double_sha256(payload)
            if (
                variant_name != "currentRule"
                and first_divergence_index is None
                and next_root != current
            ):
                first_divergence_index = index
            current = next_root
        roots[variant_name] = {
            "merkleRoot": current.hex(),
            "branchCount": len(config["branch"]),
            "firstDivergenceIndex": first_divergence_index,
        }
    return roots


def _build_branch_fold_target_matches(
    *,
    header: bytes,
    branch_fold_variant_roots: dict[str, dict[str, Any]],
    target_value: str,
) -> dict[str, bool | None]:
    target_int = int(target_value, 16)
    results: dict[str, bool | None] = {}
    for variant_name, variant_data in branch_fold_variant_roots.items():
        merkle_root = variant_data.get("merkleRoot")
        if not isinstance(merkle_root, str):
            results[variant_name] = None
            continue
        try:
            candidate_hash = _calculate_pepepow_share_hash(
                _replace_header_merkle_root(header, merkle_root)
            )
        except (PepepowPowError, ValueError):
            results[variant_name] = None
            continue
        results[variant_name] = (
            int.from_bytes(candidate_hash, byteorder="big", signed=False) <= target_int
        )
    return results


def _classify_merkle_assembly_stage(
    *,
    merkle_branch: tuple[str, ...] | list[str],
    branch_fold_target_matches: dict[str, bool | None],
    preimage_context: dict[str, Any],
) -> tuple[str, list[str], int | None]:
    branch_count = len(merkle_branch) if isinstance(merkle_branch, (list, tuple)) else 0
    if branch_count == 0:
        return (
            "coinbase-hash-stage",
            ["coinbase-hash-mismatch", "unknown-merkle-assembly-stage"],
            None,
        )

    current_rule = branch_fold_target_matches.get("currentRule")
    if current_rule is not True:
        if branch_fold_target_matches.get("reverseBranchOrder") is True:
            return (
                "merkle-branch-fold-stage",
                ["merkle-branch-order-mismatch", "ambiguous-merkle-assembly-stage"],
                0,
            )
        if branch_fold_target_matches.get("sourceOrderSiblings") is True:
            return (
                "merkle-branch-fold-stage",
                [
                    "merkle-branch-normalization-mismatch",
                    "ambiguous-merkle-assembly-stage",
                ],
                0,
            )
        if branch_fold_target_matches.get("prependSibling") is True:
            return (
                "merkle-branch-fold-stage",
                ["merkle-folding-rule-mismatch", "ambiguous-merkle-assembly-stage"],
                0,
            )

    if preimage_context.get("merkleBranchLength", 0) > 0:
        return (
            "ambiguous-merkle-assembly-stage",
            ["ambiguous-merkle-assembly-stage", "unknown-merkle-assembly-stage"],
            0,
        )

    return (
        "unknown-merkle-assembly-stage",
        ["unknown-merkle-assembly-stage"],
        None,
    )


def _classify_refined_merkle_reason_code(
    *,
    extranonce_byte_count: int | None,
    merkle_variant_target_matches: dict[str, bool | None],
    preimage_context: dict[str, Any],
) -> tuple[str, list[str]]:
    source_candidates: list[str] = []

    if extranonce_byte_count is not None and extranonce_byte_count != 8:
        source_candidates.append("scriptSig-assembly-mismatch")
        return "scriptSig-assembly-mismatch", source_candidates

    if merkle_variant_target_matches.get("swapExtranonces") is True:
        source_candidates.append("extranonce-assembly-mismatch")
        return "extranonce-assembly-mismatch", source_candidates

    if any(
        merkle_variant_target_matches.get(variant_name) is True
        for variant_name in ("zeroExtranonce1", "zeroExtranonce2")
    ):
        source_candidates.extend(
            ["coinbase-input-mismatch", "extranonce-assembly-mismatch"]
        )
        return "coinbase-input-mismatch", source_candidates

    if any(
        merkle_variant_target_matches.get(variant_name) is True
        for variant_name in ("dropExtranonce1", "dropExtranonce2")
    ):
        source_candidates.extend(
            ["scriptSig-assembly-mismatch", "coinbase-input-mismatch"]
        )
        return "scriptSig-assembly-mismatch", source_candidates

    if (
        preimage_context.get("merkleBranchLength", 0) > 0
        or preimage_context.get("templateTransactionCount", 0) > 0
    ):
        source_candidates.extend(
            [
                "transaction-list-or-branch-mismatch",
                "wrong-job-context-mismatch",
                "unknown-upstream-merkle-mismatch",
            ]
        )
        return "transaction-list-or-branch-mismatch", source_candidates

    source_candidates.extend(
        ["merkle-assembly-mismatch", "unknown-upstream-merkle-mismatch"]
    )
    return "merkle-assembly-mismatch", source_candidates


def _build_merkle_branch_summary(
    merkle_branch: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    normalized_branch = [entry.strip().lower() for entry in merkle_branch if isinstance(entry, str)]
    return {
        "branchLength": len(normalized_branch),
        "firstBranchEntry": normalized_branch[0] if normalized_branch else None,
        "lastBranchEntry": normalized_branch[-1] if normalized_branch else None,
        "branchDigest": (
            hashlib.sha256(
                json.dumps(normalized_branch, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:24]
            if normalized_branch
            else None
        ),
    }


def _build_merkle_provenance_diagnostic(
    cached_job: Any,
    *,
    header: bytes,
    extranonce1: str | None,
    extranonce2: str | None,
    ntime: str,
    nonce: str,
    coinbase_hash: str | None,
    merkle_root: str | None,
    target_value: str,
) -> dict[str, Any]:
    preimage_context = (
        cached_job.preimage_context if isinstance(getattr(cached_job, "preimage_context", None), dict) else {}
    )
    target_context = (
        cached_job.target_context if isinstance(getattr(cached_job, "target_context", None), dict) else {}
    )
    merkle_branch = getattr(cached_job, "merkle_branch", ())
    coinb1_hex = _normalize_optional_hex(getattr(cached_job, "coinb1", None))
    coinb2_hex = _normalize_optional_hex(getattr(cached_job, "coinb2", None))

    if (
        coinb1_hex is None
        or coinb2_hex is None
        or extranonce1 is None
        or extranonce2 is None
        or not isinstance(merkle_branch, (list, tuple))
    ):
        return {
            "refinedMerkleReasonCode": "unknown-upstream-merkle-mismatch",
            "merkleRootExpected": merkle_root,
            "merkleRootLocal": merkle_root,
            "coinbaseHashLocal": coinbase_hash,
        }

    merkle_variant_roots = _build_coinbase_variant_roots(
        coinb1_hex=coinb1_hex,
        coinb2_hex=coinb2_hex,
        extranonce1_hex=extranonce1,
        extranonce2_hex=extranonce2,
        merkle_branch=merkle_branch,
    )
    merkle_variant_target_matches = _build_merkle_variant_target_matches(
        header=header,
        variant_roots=merkle_variant_roots,
        target_value=target_value,
    )
    branch_fold_variant_roots = _build_branch_fold_variant_roots(
        coinbase_hash_hex=coinbase_hash,
        merkle_branch=merkle_branch,
    )
    branch_fold_target_matches = _build_branch_fold_target_matches(
        header=header,
        branch_fold_variant_roots=branch_fold_variant_roots,
        target_value=target_value,
    )
    extranonce_byte_count = (len(extranonce1) + len(extranonce2)) // 2
    refined_merkle_reason_code, source_candidates = _classify_refined_merkle_reason_code(
        extranonce_byte_count=extranonce_byte_count,
        merkle_variant_target_matches=merkle_variant_target_matches,
        preimage_context=preimage_context,
    )
    refined_merkle_assembly_stage = None
    assembly_mismatch_source_candidates: list[str] | None = None
    first_merkle_divergence_index = None
    if refined_merkle_reason_code == "merkle-assembly-mismatch":
        (
            refined_merkle_assembly_stage,
            assembly_mismatch_source_candidates,
            first_merkle_divergence_index,
        ) = _classify_merkle_assembly_stage(
            merkle_branch=merkle_branch,
            branch_fold_target_matches=branch_fold_target_matches,
            preimage_context=preimage_context,
        )
    now = utc_now()
    created_at = getattr(cached_job, "created_at", None)
    expires_at = getattr(cached_job, "expires_at", None)
    diagnostic = {
        "refinedMerkleReasonCode": refined_merkle_reason_code,
        "coinbaseHashLocal": coinbase_hash,
        "merkleRootExpected": merkle_root,
        "merkleRootLocal": merkle_root,
        "merkleBranchSummary": _build_merkle_branch_summary(merkle_branch),
        "transactionContextSummary": {
            "templateTransactionCount": preimage_context.get("templateTransactionCount"),
            "transactionsDigest": preimage_context.get("transactionsDigest"),
            "coinbaseOutputsDigest": preimage_context.get("coinbaseOutputsDigest"),
            "coinbaseOutputsCount": preimage_context.get("coinbaseOutputsCount"),
            "placeholderPayout": preimage_context.get("placeholderPayout"),
        },
        "jobContextIdentifiers": {
            "jobId": getattr(cached_job, "job_id", None),
            "jobSequence": _parse_internal_job_sequence(
                getattr(cached_job, "job_id", None)
            ),
            "templateAnchor": getattr(cached_job, "template_anchor", None),
            "height": target_context.get("height"),
            "createdAt": _isoformat_optional(created_at),
            "expiresAt": _isoformat_optional(expires_at),
            "staleBasis": getattr(cached_job, "stale_basis", None),
        },
        "templateIdentifiers": {
            "targetBits": target_context.get("bits"),
            "targetVersion": target_context.get("version"),
            "targetCurtime": target_context.get("curtime"),
            "jobNtime": getattr(cached_job, "ntime", None),
            "preimageSource": preimage_context.get("source"),
            "transactionsDigest": preimage_context.get("transactionsDigest"),
            "coinbaseOutputsDigest": preimage_context.get("coinbaseOutputsDigest"),
        },
        "contextAgeOrSequenceHints": {
            "jobAgeSeconds": (
                max(0, int((now - created_at).total_seconds()))
                if isinstance(created_at, datetime)
                else None
            ),
            "ttlRemainingSeconds": (
                max(0, int((expires_at - now).total_seconds()))
                if isinstance(expires_at, datetime)
                else None
            ),
            "submitExtranonceByteCount": extranonce_byte_count,
            "localCoinbaseExtranonceBytesAssumed": 8,
        },
        "alternateCoinbaseVariantRoots": merkle_variant_roots,
        "alternateCoinbaseHashVariants": {
            variant_name: variant_data.get("coinbaseHash")
            for variant_name, variant_data in merkle_variant_roots.items()
        },
        "alternateCoinbaseVariantTargetMatches": merkle_variant_target_matches,
        "merkleRootMismatchSourceCandidates": source_candidates,
    }
    parsed_coinb2 = _parse_coinb2_outputs(coinb2_hex)
    authoritative_output_reference = _build_authoritative_output_reference_diagnostic(
        cached_job,
        local_output_summaries=[
            _summarize_coinb2_output(output) for output in parsed_coinb2.get("outputs", [])
        ],
        local_coinb2_hex=coinb2_hex,
    )
    diagnostic.update(authoritative_output_reference)
    diagnostic.update(
        _build_authoritative_coinbase_segment_diagnostic(
            cached_job,
            coinb1_hex=coinb1_hex,
            coinb2_hex=coinb2_hex,
            extranonce1_hex=extranonce1,
            extranonce2_hex=extranonce2,
            output_vector_confirmed_equal=authoritative_output_reference.get(
                "localVsAuthoritativeOutputLayoutEqual"
            ),
        )
    )
    diagnostic.update(
        _build_full_coinbase_handoff_diagnostic(
            cached_job,
            coinb1_hex=coinb1_hex,
            coinb2_hex=coinb2_hex,
            extranonce1_hex=extranonce1,
            extranonce2_hex=extranonce2,
            header_merkle_root_hex=header[36:68].hex() if len(header) >= 68 else None,
            merkle_branch=merkle_branch,
        )
    )
    diagnostic.update(
        _build_final_header80_probe_diagnostic(
            cached_job,
            header=header,
            extranonce1_hex=extranonce1,
            extranonce2_hex=extranonce2,
            ntime_hex=ntime,
            nonce_hex=nonce,
            coinbase_hash_hex=coinbase_hash,
            merkle_branch=merkle_branch,
        )
    )
    if refined_merkle_assembly_stage is not None:
        diagnostic["refinedMerkleAssemblyStage"] = refined_merkle_assembly_stage
        diagnostic["merkleBranchFoldTraceSummary"] = {
            "branchCount": len(merkle_branch) if isinstance(merkle_branch, (list, tuple)) else 0,
            "currentRuleMerkleRoot": (
                branch_fold_variant_roots.get("currentRule", {}).get("merkleRoot")
            ),
        }
        diagnostic["firstMerkleDivergenceIndex"] = first_merkle_divergence_index
        diagnostic["branchCount"] = (
            len(merkle_branch) if isinstance(merkle_branch, (list, tuple)) else 0
        )
        diagnostic["branchOrderVariantResults"] = {
            "reverseBranchOrder": branch_fold_target_matches.get("reverseBranchOrder")
        }
        diagnostic["branchEndianVariantResults"] = {
            "sourceOrderSiblings": branch_fold_target_matches.get("sourceOrderSiblings")
        }
        diagnostic["branchFoldTargetMatches"] = branch_fold_target_matches
        diagnostic["assemblyMismatchSourceCandidates"] = (
            assembly_mismatch_source_candidates
        )
        if refined_merkle_assembly_stage == "coinbase-hash-stage":
            coinbase_assembly_variants = _build_coinbase_assembly_variants(
                coinb1_hex=coinb1_hex,
                coinb2_hex=coinb2_hex,
                extranonce1_hex=extranonce1,
                extranonce2_hex=extranonce2,
            )
            coinbase_assembly_target_matches = _build_coinbase_assembly_target_matches(
                header=header,
                coinbase_assembly_variants=coinbase_assembly_variants,
                target_value=target_value,
            )
            refined_coinbase_reason_code, coinbase_source_candidates, first_coinbase_mismatch_offset, coinbase_mismatch_field_names = _classify_coinbase_reason_code(
                coinbase_assembly_target_matches=coinbase_assembly_target_matches,
                preimage_context=preimage_context,
            )
            coinb1_bytes = bytes.fromhex(coinb1_hex)
            coinb2_bytes = bytes.fromhex(coinb2_hex)
            declared_script_length, after_varint = _decode_varint_at(
                coinb1_bytes, _script_length_varint_offset(coinb1_bytes)
            )
            local_coinbase_hex = (
                coinb1_hex + extranonce1 + extranonce2 + coinb2_hex
            )
            diagnostic["refinedCoinbaseReasonCode"] = refined_coinbase_reason_code
            diagnostic["coinbaseLocalHex"] = local_coinbase_hex
            diagnostic["coinbaseSegmentSummary"] = {
                "coinb1HexLength": len(coinb1_hex),
                "extranonce1HexLength": len(extranonce1),
                "extranonce2HexLength": len(extranonce2),
                "coinb2HexLength": len(coinb2_hex),
                "totalCoinbaseHexLength": len(local_coinbase_hex),
            }
            diagnostic["coinbasePrefixSummary"] = {
                "coinb1HexLength": len(coinb1_hex),
                "coinb1HexPrefix": coinb1_hex[:32],
                "scriptLengthVarintOffset": _script_length_varint_offset(coinb1_bytes),
            }
            diagnostic["coinbaseSuffixSummary"] = {
                "coinb2HexLength": len(coinb2_hex),
                "coinb2HexPrefix": coinb2_hex[:32],
                "coinb2HexSuffix": coinb2_hex[-32:],
            }
            diagnostic["scriptSigSummary"] = {
                "declaredScriptSigBytes": declared_script_length,
                "scriptSigPrefixBytes": max(
                    0,
                    len(coinb1_bytes[after_varint:]),
                ),
                "submitExtranonceBytes": (len(extranonce1) + len(extranonce2)) // 2,
            }
            diagnostic["extranoncePlacementSummary"] = {
                "assumedLayout": "coinb1|extranonce1|extranonce2|coinb2",
                "extranonce1HexLength": len(extranonce1),
                "extranonce2HexLength": len(extranonce2),
            }
            diagnostic["outputLayoutSummary"] = {
                "coinbaseOutputsCount": preimage_context.get("coinbaseOutputsCount"),
                "placeholderPayout": preimage_context.get("placeholderPayout"),
                "coinbaseOutputsDigest": preimage_context.get("coinbaseOutputsDigest"),
            }
            diagnostic["coinbaseLengthSummary"] = {
                "totalCoinbaseBytes": len(local_coinbase_hex) // 2,
                "declaredScriptSigBytes": declared_script_length,
                "localCoinbaseExtranonceBytes": (len(extranonce1) + len(extranonce2))
                // 2,
            }
            diagnostic["alternateCoinbaseAssemblyVariants"] = {
                variant_name: {
                    "category": variant_data.get("category"),
                    "coinbaseHexLength": variant_data.get("coinbaseHexLength"),
                    "coinbaseHash": variant_data.get("coinbaseHash"),
                }
                for variant_name, variant_data in coinbase_assembly_variants.items()
            }
            diagnostic["alternateCoinbaseAssemblyHashMatches"] = (
                coinbase_assembly_target_matches
            )
            diagnostic["firstCoinbaseMismatchOffset"] = (
                first_coinbase_mismatch_offset
            )
            diagnostic["coinbaseMismatchFieldNames"] = coinbase_mismatch_field_names
            diagnostic["coinbaseMismatchSourceCandidates"] = (
                coinbase_source_candidates
            )
            if refined_coinbase_reason_code == "placeholder-payout-output-suspected":
                diagnostic.update(
                    _build_corrected_placeholder_output_comparison(
                        cached_job=cached_job,
                        header=header,
                        coinb1_hex=coinb1_hex,
                        coinb2_hex=coinb2_hex,
                        extranonce1_hex=extranonce1,
                        extranonce2_hex=extranonce2,
                        coinbase_hash=coinbase_hash,
                        merkle_root=merkle_root,
                        merkle_branch=merkle_branch,
                        target_value=target_value,
                    )
                )
    return diagnostic


def _build_share_header_preimage(
    cached_job: Any,
    *,
    extranonce1: str | None,
    extranonce2: str,
    ntime: str,
    nonce: str,
    version_source_order: bool = False,
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
        version_bytes = bytes.fromhex(version)
        version_le = version_bytes if version_source_order else version_bytes[::-1]
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

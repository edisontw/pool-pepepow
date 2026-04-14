from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ShareEventLoadError(RuntimeError):
    """Raised when the share event log cannot be read."""


@dataclass(frozen=True)
class ShareEvent:
    wallet: str
    worker: str
    occurred_at: datetime
    accepted: bool


@dataclass(frozen=True)
class ShareEventLoadResult:
    events: list[ShareEvent]
    warnings: list[str]
    missing: bool


@dataclass(frozen=True)
class ShareEventRecord:
    event: ShareEvent
    payload: dict[str, Any]
    sequence: int
    start_offset: int
    end_offset: int


def load_share_events(log_path: Path) -> ShareEventLoadResult:
    if not log_path.exists():
        return ShareEventLoadResult(events=[], warnings=[], missing=True)

    try:
        raw = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ShareEventLoadError(
            f"Share event log is unreadable: {log_path}"
        ) from exc

    events: list[ShareEvent] = []
    warnings: list[str] = []

    for line_number, line in enumerate(raw.splitlines(), start=1):
        payload = line.strip()
        if not payload:
            continue

        try:
            event = parse_share_event(payload)
        except ValueError as exc:
            warnings.append(f"line {line_number}: {exc}")
            continue

        events.append(event)

    return ShareEventLoadResult(events=events, warnings=warnings, missing=False)


def read_share_event_records(
    log_path: Path, *, start_offset: int = 0
) -> tuple[list[ShareEventRecord], list[str]]:
    if not log_path.exists():
        return [], []

    records: list[ShareEventRecord] = []
    warnings: list[str] = []

    try:
        with log_path.open("rb") as handle:
            handle.seek(max(0, start_offset))

            line_number = 0
            while True:
                raw_line = handle.readline()
                if not raw_line:
                    break
                line_number += 1
                line_end = handle.tell()
                line_start = line_end - len(raw_line)
                payload = raw_line.decode("utf-8", errors="replace").strip()
                if not payload:
                    continue

                try:
                    raw_payload = _load_payload(payload)
                    event = parse_share_event(raw_payload)
                except ValueError as exc:
                    warnings.append(f"line {line_number}: {exc}")
                    continue

                records.append(
                    ShareEventRecord(
                        event=event,
                        payload=raw_payload,
                        sequence=_resolve_sequence(raw_payload),
                        start_offset=line_start,
                        end_offset=line_end,
                    )
                )
    except OSError as exc:
        raise ShareEventLoadError(
            f"Share event log is unreadable: {log_path}"
        ) from exc

    return records, warnings


def parse_share_event(raw_event: str | dict[str, Any]) -> ShareEvent:
    payload = _load_payload(raw_event)
    wallet, worker = _resolve_identity(payload)
    occurred_at = _parse_timestamp(payload)
    accepted = _resolve_outcome(payload)
    return ShareEvent(
        wallet=wallet,
        worker=worker,
        occurred_at=occurred_at,
        accepted=accepted,
    )


def _load_payload(raw_event: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_event, dict):
        payload = raw_event
    else:
        try:
            payload = json.loads(raw_event)
        except json.JSONDecodeError as exc:
            raise ValueError("event is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("event payload must be a JSON object")

    return payload


def _resolve_identity(payload: dict[str, Any]) -> tuple[str, str]:
    wallet = payload.get("wallet")
    worker = payload.get("worker")
    login = payload.get("login")

    if isinstance(wallet, str) and wallet.strip():
        resolved_wallet = wallet.strip()
        if isinstance(worker, str) and worker.strip():
            return resolved_wallet, worker.strip()
        return resolved_wallet, "default"

    if isinstance(login, str) and login.strip():
        login_value = login.strip()
        if "." in login_value:
            login_wallet, login_worker = login_value.split(".", 1)
            login_wallet = login_wallet.strip()
            login_worker = login_worker.strip()
            if login_wallet:
                return login_wallet, login_worker or "default"
        return login_value, "default"

    raise ValueError("event is missing wallet or login")


def _parse_timestamp(payload: dict[str, Any]) -> datetime:
    for key in ("timestamp", "submittedAt", "observedAt"):
        raw_value = payload.get(key)
        if raw_value is None:
            continue

        if isinstance(raw_value, (int, float)):
            return datetime.fromtimestamp(raw_value, tz=timezone.utc)

        if isinstance(raw_value, str) and raw_value.strip():
            normalized = raw_value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(f"{key} is not a valid ISO timestamp") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        raise ValueError(f"{key} has an unsupported type")

    raise ValueError("event is missing timestamp")


def _resolve_outcome(payload: dict[str, Any]) -> bool:
    accepted = payload.get("accepted")
    if isinstance(accepted, bool):
        return accepted

    for key in ("status", "result", "outcome"):
        raw_value = payload.get(key)
        if not isinstance(raw_value, str):
            continue
        value = raw_value.strip().lower()
        if value in {"accepted", "ok", "valid", "share-accepted"}:
            return True
        if value in {
            "rejected",
            "invalid",
            "stale",
            "duplicate",
            "error",
            "share-rejected",
        }:
            return False

    return True


def _resolve_sequence(payload: dict[str, Any]) -> int:
    sequence = payload.get("sequence")
    if isinstance(sequence, bool):
        return int(sequence)
    if isinstance(sequence, int):
        return max(0, sequence)
    if isinstance(sequence, float):
        return max(0, int(sequence))
    if isinstance(sequence, str):
        stripped = sequence.strip()
        if stripped.isdigit():
            return int(stripped)
    return 0

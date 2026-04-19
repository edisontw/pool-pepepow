from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any


DEFAULT_WORKER_NAME = "default"
UNKNOWN_WALLET = "unknown"


class StratumProtocolError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StratumRequest:
    request_id: Any
    method: str
    params: list[Any]


@dataclass
class ConnectionState:
    session_id: str
    extranonce1: str
    extranonce2_size: int = 4
    authorized: bool = False
    authorized_login: str | None = None
    authorized_wallet: str | None = None
    authorized_worker: str | None = None
    current_difficulty: float | None = None
    current_job_id: str | None = None
    previous_job_id: str | None = None
    submits_received: int = 0
    shares_valid: int = 0
    shares_rejected: int = 0
    reject_reason_counts: dict[str, int] = field(default_factory=dict)
    last_share_at: Any | None = None  # Use Any to avoid datetime import dependency here if preferred, but datetime is fine
    clean_jobs_legacy: bool = False


def new_connection_state() -> ConnectionState:
    session_id = secrets.token_hex(8)
    return ConnectionState(
        session_id=session_id,
        extranonce1=secrets.token_hex(4),
    )


def parse_request(raw_line: str) -> StratumRequest:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise StratumProtocolError(-32700, "Parse error") from exc

    if not isinstance(payload, dict):
        raise StratumProtocolError(-32600, "Request must be a JSON object")

    method = payload.get("method")
    params = payload.get("params", [])
    request_id = payload.get("id")

    if not isinstance(method, str) or not method:
        raise StratumProtocolError(-32600, "Request method is invalid")
    if not isinstance(params, list):
        raise StratumProtocolError(-32602, "Request params must be an array")

    return StratumRequest(request_id=request_id, method=method, params=params)


def success_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"id": request_id, "result": result, "error": None}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"id": request_id, "result": None, "error": {"code": code, "message": message}}


def subscribe_result(state: ConnectionState) -> list[Any]:
    return [
        [
            ["mining.set_difficulty", state.session_id],
            ["mining.notify", state.session_id],
        ],
        state.extranonce1,
        state.extranonce2_size,
    ]


def difficulty_notification(difficulty: float) -> dict[str, Any]:
    return {
        "id": None,
        "method": "mining.set_difficulty",
        "params": [difficulty],
    }


def notify_notification(
    *,
    job_id: str,
    prevhash: str,
    coinb1: str,
    coinb2: str,
    merkle_branch: list[str],
    version: str,
    nbits: str,
    ntime: str,
    clean_jobs: bool,
    legacy_clean_jobs: bool = False,
) -> dict[str, Any]:
    return {
        "id": None,
        "method": "mining.notify",
        "params": [
            job_id,
            prevhash,
            coinb1,
            coinb2,
            merkle_branch,
            version,
            nbits,
            ntime,
            1 if (clean_jobs and legacy_clean_jobs) else clean_jobs,
        ],
    }


def authorize_identity(login: str | None) -> tuple[str, str, str]:
    normalized_login = (login or "").strip()
    if not normalized_login:
        return UNKNOWN_WALLET, DEFAULT_WORKER_NAME, UNKNOWN_WALLET

    if "." in normalized_login:
        wallet, worker = normalized_login.split(".", 1)
        wallet = wallet.strip() or UNKNOWN_WALLET
        worker = worker.strip() or DEFAULT_WORKER_NAME
        return wallet, worker, f"{wallet}.{worker}"

    return normalized_login, DEFAULT_WORKER_NAME, normalized_login


def resolve_submit_identity(
    params: list[Any], state: ConnectionState
) -> tuple[str, str, str]:
    if params:
        login = params[0]
        if isinstance(login, str) and login.strip():
            return authorize_identity(login)

    if state.authorized_login is not None:
        return (
            state.authorized_wallet or UNKNOWN_WALLET,
            state.authorized_worker or DEFAULT_WORKER_NAME,
            state.authorized_login,
        )

    return UNKNOWN_WALLET, DEFAULT_WORKER_NAME, UNKNOWN_WALLET

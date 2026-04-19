from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DaemonRpcError(RuntimeError):
    """Base error for RPC client failures."""


class DaemonRpcUnavailableError(DaemonRpcError):
    """Raised when the daemon cannot be reached."""


class DaemonRpcResponseError(DaemonRpcError):
    """Raised when the daemon returns an invalid RPC payload."""


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class DaemonRpcClient:
    def __init__(
        self,
        rpc_url: str,
        rpc_user: str,
        rpc_password: str,
        timeout_seconds: float,
        cache_ttl_seconds: int = 5,
    ) -> None:
        self._rpc_url = rpc_url
        self._rpc_user = rpc_user
        self._rpc_password = rpc_password
        self._timeout_seconds = timeout_seconds
        self._default_cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._request_id = 0

    def get_blockchain_info(self) -> dict[str, Any]:
        return self._cached_call("getblockchaininfo", ttl=5)

    def get_network_info(self) -> dict[str, Any]:
        return self._cached_call("getnetworkinfo", ttl=15)

    def get_mining_info(self) -> dict[str, Any]:
        return self._cached_call("getmininginfo", ttl=15)

    def get_block_template(self) -> dict[str, Any]:
        result = self.call("getblocktemplate", [{}])
        if not isinstance(result, dict):
            raise DaemonRpcResponseError(
                "getblocktemplate returned an invalid payload type"
            )
        return result

    def submitblock(self, block_hex: str) -> Any:
        return self.call("submitblock", [block_hex])

    def get_block_hash(self, height: int) -> str:
        result = self.call("getblockhash", [height])
        if not isinstance(result, str) or not result:
            raise DaemonRpcResponseError(
                f"getblockhash returned an invalid hash for height {height}"
            )
        return result

    def get_block_header(self, block_hash: str) -> dict[str, Any]:
        result = self.call("getblockheader", [block_hash])
        if not isinstance(result, dict):
            raise DaemonRpcResponseError(
                f"getblockheader returned an invalid payload for {block_hash}"
            )
        return result

    def get_recent_block_headers(self, tip_height: int, limit: int) -> list[dict[str, Any]]:
        start_height = max(0, tip_height - limit + 1)
        headers: list[dict[str, Any]] = []

        for height in range(tip_height, start_height - 1, -1):
            try:
                block_hash = self.get_block_hash(height)
                headers.append(self.get_block_header(block_hash))
            except DaemonRpcError:
                if height == tip_height:
                    continue
                raise

        headers.sort(key=lambda item: int(item.get("height", 0)), reverse=True)
        return headers

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        self._request_id += 1
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or [],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._rpc_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._build_auth_header(),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_seconds
            ) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            with suppress(json.JSONDecodeError):
                payload = json.loads(detail)
                if isinstance(payload, dict) and payload.get("error"):
                    raise DaemonRpcResponseError(
                        f"RPC {method} error: {payload['error']}"
                    ) from exc
            raise DaemonRpcUnavailableError(
                f"RPC {method} returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise DaemonRpcUnavailableError(
                f"RPC {method} failed: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise DaemonRpcUnavailableError(
                f"RPC {method} timed out after {self._timeout_seconds} seconds"
            ) from exc

        try:
            data = json.loads(response_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DaemonRpcResponseError(
                f"RPC {method} returned invalid JSON"
            ) from exc

        if not isinstance(data, dict):
            raise DaemonRpcResponseError(
                f"RPC {method} returned a non-object payload"
            )

        error = data.get("error")
        if error:
            raise DaemonRpcResponseError(f"RPC {method} error: {error}")

        if "result" not in data:
            raise DaemonRpcResponseError(
                f"RPC {method} response is missing a result field"
            )

        return data["result"]

    def _cached_call(self, method: str, ttl: int | None = None) -> dict[str, Any]:
        cache_key = method
        now = time.time()
        entry = self._cache.get(cache_key)
        effective_ttl = ttl or self._default_cache_ttl_seconds

        if entry is not None and entry.expires_at > now:
            cached = entry.value
            if isinstance(cached, dict):
                return cached
            raise DaemonRpcResponseError(
                f"Cached RPC payload for {method} is invalid"
            )

        result = self.call(method)
        if not isinstance(result, dict):
            raise DaemonRpcResponseError(
                f"RPC {method} returned an invalid payload type"
            )

        self._cache[cache_key] = CacheEntry(
            value=result,
            expires_at=now + effective_ttl,
        )
        return result

    def _build_auth_header(self) -> str:
        token = f"{self._rpc_user}:{self._rpc_password}".encode("utf-8")
        return f"Basic {base64.b64encode(token).decode('ascii')}"


def candidate_followup_defaults() -> dict[str, Any]:
    return {
        "followupStatus": "not-checked",
        "followupCheckedAt": None,
        "followupObservedHeight": None,
        "followupObservedBlockHash": None,
        "followupNote": None,
    }


def candidate_outcome_status(followup_status: Any) -> str:
    if followup_status == "match-found":
        return "chain-match-found"
    if followup_status == "no-match-found":
        return "chain-match-not-found"
    if followup_status == "check-error":
        return "check-error"
    return "submitted"


def build_candidate_outcome_event(
    candidate_event: dict[str, Any],
    followup_result: dict[str, Any] | None = None,
    *,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    observed_at = recorded_at or datetime.now(timezone.utc)
    merged_followup = candidate_followup_defaults()
    if isinstance(followup_result, dict):
        merged_followup.update(
            {
                "followupStatus": followup_result.get("followupStatus"),
                "followupCheckedAt": followup_result.get("followupCheckedAt"),
                "followupObservedHeight": followup_result.get(
                    "followupObservedHeight"
                ),
                "followupObservedBlockHash": followup_result.get(
                    "followupObservedBlockHash"
                ),
                "followupNote": followup_result.get("followupNote"),
            }
        )

    return {
        "timestamp": (
            observed_at.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "candidateTimestamp": candidate_event.get("timestamp"),
        "jobId": candidate_event.get("jobId"),
        "templateAnchor": candidate_event.get("templateAnchor"),
        "wallet": candidate_event.get("wallet"),
        "worker": candidate_event.get("worker"),
        "candidateBlockHash": candidate_event.get("candidateBlockHash"),
        "candidatePrepStatus": candidate_event.get("candidatePrepStatus"),
        "submitblockRealSubmitStatus": candidate_event.get(
            "submitblockRealSubmitStatus"
        ),
        "submitblockAttempted": candidate_event.get("submitblockAttempted"),
        "submitblockSent": candidate_event.get("submitblockSent"),
        "submitblockSubmittedAt": candidate_event.get("submitblockSubmittedAt"),
        "candidateOutcomeStatus": candidate_outcome_status(
            merged_followup.get("followupStatus")
        ),
        "followupStatus": merged_followup.get("followupStatus"),
        "followupCheckedAt": merged_followup.get("followupCheckedAt"),
        "followupObservedHeight": merged_followup.get("followupObservedHeight"),
        "followupObservedBlockHash": merged_followup.get("followupObservedBlockHash"),
        "followupNote": merged_followup.get("followupNote"),
    }


def append_candidate_outcome_event(
    path: Path,
    candidate_event: dict[str, Any],
    followup_result: dict[str, Any] | None = None,
    *,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    payload = build_candidate_outcome_event(
        candidate_event,
        followup_result,
        recorded_at=recorded_at,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )
        handle.write("\n")
    return payload


def check_candidate_followup(
    candidate_block_hash: str | None,
    *,
    rpc_client: Any,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    result = candidate_followup_defaults()
    observed_at = checked_at or datetime.now(timezone.utc)
    result["followupCheckedAt"] = (
        observed_at.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    if not isinstance(candidate_block_hash, str) or not candidate_block_hash.strip():
        result["followupStatus"] = "check-error"
        result["followupNote"] = "candidate-block-hash-missing"
        return result

    normalized_hash = candidate_block_hash.strip().lower()
    try:
        header = rpc_client.get_block_header(normalized_hash)
    except DaemonRpcResponseError as exc:
        detail = str(exc).lower()
        if "block not found" in detail or "code': -5" in detail or '"code": -5' in detail:
            result["followupStatus"] = "no-match-found"
            result["followupNote"] = "candidate-block-hash-not-found-on-local-chain"
            return result
        result["followupStatus"] = "check-error"
        result["followupNote"] = str(exc)
        return result
    except DaemonRpcError as exc:
        result["followupStatus"] = "check-error"
        result["followupNote"] = str(exc)
        return result

    result["followupStatus"] = "match-found"
    result["followupObservedHeight"] = header.get("height")
    result["followupObservedBlockHash"] = (
        header.get("hash") if isinstance(header.get("hash"), str) else normalized_hash
    )
    result["followupNote"] = "candidate-block-hash-found-on-local-chain"
    return result


def build_candidate_followup_event(
    candidate_event: dict[str, Any],
    followup_result: dict[str, Any],
    *,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    observed_at = recorded_at or datetime.now(timezone.utc)
    return {
        "timestamp": (
            observed_at.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "candidateTimestamp": candidate_event.get("timestamp"),
        "jobId": candidate_event.get("jobId"),
        "templateAnchor": candidate_event.get("templateAnchor"),
        "wallet": candidate_event.get("wallet"),
        "worker": candidate_event.get("worker"),
        "candidateBlockHash": candidate_event.get("candidateBlockHash"),
        "candidatePrepStatus": candidate_event.get("candidatePrepStatus"),
        "submitblockRealSubmitStatus": candidate_event.get(
            "submitblockRealSubmitStatus"
        ),
        "followupStatus": followup_result.get("followupStatus"),
        "followupCheckedAt": followup_result.get("followupCheckedAt"),
        "followupObservedHeight": followup_result.get("followupObservedHeight"),
        "followupObservedBlockHash": followup_result.get("followupObservedBlockHash"),
        "followupNote": followup_result.get("followupNote"),
    }


def append_candidate_followup_event(
    path: Path,
    candidate_event: dict[str, Any],
    followup_result: dict[str, Any],
    *,
    recorded_at: datetime | None = None,
    outcome_path: Path | None = None,
) -> dict[str, Any]:
    payload = build_candidate_followup_event(
        candidate_event,
        followup_result,
        recorded_at=recorded_at,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )
        handle.write("\n")
    if outcome_path is not None:
        append_candidate_outcome_event(
            outcome_path,
            candidate_event,
            followup_result,
            recorded_at=recorded_at,
        )
    return payload

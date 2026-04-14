from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
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

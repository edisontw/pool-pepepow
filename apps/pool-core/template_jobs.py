from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from config import PoolCoreConfig
from daemon_rpc import DaemonRpcClient, DaemonRpcError


LOGGER = logging.getLogger("pepepow.template_jobs")

TEMPLATE_MODE_SYNTHETIC = "synthetic"
TEMPLATE_MODE_DAEMON = "daemon-template"
TEMPLATE_MODE_FALLBACK = "daemon-template-fallback-synthetic"

RPC_STATUS_DISABLED = "disabled"
RPC_STATUS_UNKNOWN = "unknown"
RPC_STATUS_REACHABLE = "reachable"
RPC_STATUS_UNREACHABLE = "unreachable"

FETCH_STATUS_DISABLED = "disabled"
FETCH_STATUS_NEVER_ATTEMPTED = "never-attempted"
FETCH_STATUS_OK = "ok"
FETCH_STATUS_ERROR = "error"

SYNTHETIC_PREVHASH = "0" * 64
SYNTHETIC_VERSION = "20000000"
SYNTHETIC_NBITS = "1d00ffff"
SYNTHETIC_COINB1 = "0100000001"
SYNTHETIC_COINB2 = "ffffffff"
PLACEHOLDER_PAYOUT_SCRIPT = "51"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def normalize_template_mode(raw_mode: str) -> str:
    normalized = (raw_mode or "").strip().lower()
    if normalized == TEMPLATE_MODE_DAEMON:
        return TEMPLATE_MODE_DAEMON
    return TEMPLATE_MODE_SYNTHETIC


@dataclass(frozen=True)
class TemplateSnapshot:
    template_anchor: str
    prevhash: str
    version: str
    nbits: str
    ntime: str
    fetched_at: datetime
    target_context: dict[str, Any]
    coinb1: str
    coinb2: str
    merkle_branch: tuple[str, ...]
    preimage_context: dict[str, Any]
    authoritative_context: dict[str, Any]


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    template_anchor: str
    assigned_difficulty: float | None
    target_context: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    stale_basis: str
    source: str
    prevhash: str
    version: str
    nbits: str
    ntime: str
    coinb1: str
    coinb2: str
    merkle_branch: tuple[str, ...]
    preimage_context: dict[str, Any]
    authoritative_context: dict[str, Any]

    def as_dict(self, *, now: datetime) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "templateAnchor": self.template_anchor,
            "targetContext": self.target_context,
            "createdAt": isoformat(self.created_at),
            "expiresAt": isoformat(self.expires_at),
            "staleBasis": self.stale_basis,
            "stale": now >= self.expires_at,
            "ageSeconds": max(0, int((now - self.created_at).total_seconds())),
            "source": self.source,
            "preimageContext": self.preimage_context,
        }


class TemplateJobManager:
    def __init__(
        self,
        config: PoolCoreConfig,
        *,
        rpc_client: DaemonRpcClient | Any | None = None,
    ) -> None:
        self._configured_mode = normalize_template_mode(config.template_mode)
        self._fetch_interval_seconds = config.template_fetch_interval_seconds
        self._job_ttl_seconds = config.template_job_ttl_seconds
        self._job_cache_size = config.template_job_cache_size
        self._retired_job_cache_size = max(16, config.template_job_cache_size * 4)
        self._retired_job_max_age_seconds = max(300, config.template_job_ttl_seconds * 2)
        self._rpc_client = rpc_client
        if self._rpc_client is None and self._configured_mode == TEMPLATE_MODE_DAEMON:
            self._rpc_client = DaemonRpcClient(
                config.rpc_url,
                config.rpc_user,
                config.rpc_password,
                config.rpc_timeout_seconds,
                cache_ttl_seconds=config.rpc_cache_ttl_seconds,
            )

        self._jobs: OrderedDict[str, JobRecord] = OrderedDict()
        self._retired_jobs: OrderedDict[str, datetime] = OrderedDict()
        self._latest_template: TemplateSnapshot | None = None
        self._last_attempt_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None
        self._rpc_status = (
            RPC_STATUS_DISABLED
            if self._configured_mode == TEMPLATE_MODE_SYNTHETIC
            else RPC_STATUS_UNKNOWN
        )
        self._fetch_status = (
            FETCH_STATUS_DISABLED
            if self._configured_mode == TEMPLATE_MODE_SYNTHETIC
            else FETCH_STATUS_NEVER_ATTEMPTED
        )
        self._dirty = False
        self._task: asyncio.Task[None] | None = None

    @property
    def latest_template_anchor(self) -> str | None:
        if self._latest_template is not None:
            return self._latest_template.template_anchor
        return None

    async def start(self) -> None:
        if self._configured_mode != TEMPLATE_MODE_DAEMON or self._task is not None:
            return

        self._task = asyncio.create_task(
            self._refresh_loop(),
            name="daemon-template-refresh",
        )

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def has_dirty_updates(self) -> bool:
        return self._dirty

    def clear_dirty_updates(self) -> None:
        self._dirty = False

    def issue_job(
        self,
        job_id: str,
        *,
        now: datetime | None = None,
        assigned_difficulty: float | None = None,
    ) -> JobRecord:
        current_time = now or utc_now()
        self._prune_jobs(current_time)
        self._prune_retired_jobs(current_time)
        template = self._latest_template
        if self._configured_mode == TEMPLATE_MODE_DAEMON and template is not None:
            source = TEMPLATE_MODE_DAEMON
            prevhash = template.prevhash
            version = template.version
            nbits = template.nbits
            ntime = template.ntime
            template_anchor = template.template_anchor
            target_context = dict(template.target_context)
            coinb1 = template.coinb1
            coinb2 = template.coinb2
            merkle_branch = tuple(template.merkle_branch)
            preimage_context = dict(template.preimage_context)
            authoritative_context = dict(template.authoritative_context)
        else:
            source = TEMPLATE_MODE_SYNTHETIC
            prevhash = SYNTHETIC_PREVHASH
            version = SYNTHETIC_VERSION
            nbits = SYNTHETIC_NBITS
            ntime = f"{int(current_time.timestamp()):08x}"
            template_anchor = "synthetic-anchor"
            target_context = {
                "bits": nbits,
                "target": None,
                "height": None,
                "version": version,
                "curtime": int(current_time.timestamp()),
            }
            coinb1 = SYNTHETIC_COINB1
            coinb2 = SYNTHETIC_COINB2
            merkle_branch = ()
            preimage_context = {
                "source": "synthetic-placeholder",
                "coinb1Length": len(coinb1),
                "coinb2Length": len(coinb2),
                "merkleBranchLength": 0,
                "templateTransactionCount": 0,
                "coinbaseOutputsCount": 0,
            }
            authoritative_context = {}

        expires_at = current_time + timedelta(seconds=self._job_ttl_seconds)
        job = JobRecord(
            job_id=job_id,
            template_anchor=template_anchor,
            assigned_difficulty=assigned_difficulty,
            target_context=target_context,
            created_at=current_time,
            expires_at=expires_at,
            stale_basis=f"created+{self._job_ttl_seconds}s",
            source=source,
            prevhash=prevhash,
            version=version,
            nbits=nbits,
            ntime=ntime,
            coinb1=coinb1,
            coinb2=coinb2,
            merkle_branch=merkle_branch,
            preimage_context=preimage_context,
            authoritative_context=authoritative_context,
        )
        self._jobs.pop(job_id, None)
        self._jobs[job_id] = job
        while len(self._jobs) > self._job_cache_size:
            evicted_job_id, evicted_job = self._jobs.popitem(last=False)
            self._remember_retired_job(evicted_job_id, evicted_job.expires_at)
        self._dirty = True
        return job

    def get_job(self, job_id: str | None, *, now: datetime | None = None) -> JobRecord | None:
        if job_id is None:
            return None
        self._prune_jobs(now or utc_now())
        return self._jobs.get(job_id)

    def is_stale_job(self, job_id: str | None, *, now: datetime | None = None) -> bool:
        if job_id is None:
            return False

        current_time = now or utc_now()
        self._prune_jobs(current_time)
        self._prune_retired_jobs(current_time)

        if job_id in self._jobs:
            return False
        return job_id in self._retired_jobs

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        current_time = now or utc_now()
        removed = self._prune_jobs(current_time)
        if removed:
            self._dirty = True

        latest_template_age_seconds: int | None = None
        latest_template_anchor: str | None = None
        if self._last_success_at is not None:
            latest_template_age_seconds = max(
                0, int((current_time - self._last_success_at).total_seconds())
            )
        if self._latest_template is not None:
            latest_template_anchor = self._latest_template.template_anchor

        return {
            "configuredMode": self._configured_mode,
            "currentMode": self._effective_mode(),
            "daemonRpcStatus": self._rpc_status,
            "daemonRpcReachable": self._rpc_status == RPC_STATUS_REACHABLE,
            "templateFetchStatus": self._fetch_status,
            "lastAttemptAt": isoformat(self._last_attempt_at),
            "lastSuccessAt": isoformat(self._last_success_at),
            "latestTemplateAgeSeconds": latest_template_age_seconds,
            "latestTemplateAnchor": latest_template_anchor,
            "lastError": self._last_error,
            "activeJobCount": len(self._jobs),
            "active": [
                job.as_dict(now=current_time)
                for job in self._jobs.values()
            ],
        }

    async def _refresh_loop(self) -> None:
        while True:
            await self._refresh_once()
            await asyncio.sleep(self._fetch_interval_seconds)

    async def _refresh_once(self) -> None:
        if self._rpc_client is None:
            return

        current_time = utc_now()
        self._last_attempt_at = current_time
        try:
            raw_template = await asyncio.to_thread(self._rpc_client.get_block_template)
            template = _parse_block_template(raw_template, fetched_at=current_time)
        except (DaemonRpcError, ValueError) as exc:
            self._rpc_status = RPC_STATUS_UNREACHABLE
            self._fetch_status = FETCH_STATUS_ERROR
            self._last_error = str(exc)
            self._dirty = True
            LOGGER.warning("Daemon template refresh failed: %s", exc)
            return

        self._latest_template = template
        self._last_success_at = current_time
        self._last_error = None
        self._rpc_status = RPC_STATUS_REACHABLE
        self._fetch_status = FETCH_STATUS_OK
        self._dirty = True

    def _effective_mode(self) -> str:
        if self._configured_mode == TEMPLATE_MODE_SYNTHETIC:
            return TEMPLATE_MODE_SYNTHETIC
        if self._latest_template is not None:
            return TEMPLATE_MODE_DAEMON
        return TEMPLATE_MODE_FALLBACK

    def _prune_jobs(self, now: datetime) -> bool:
        removed = False
        expired_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if now >= job.expires_at
        ]
        for job_id in expired_job_ids:
            expired_job = self._jobs.pop(job_id, None)
            if expired_job is not None:
                self._remember_retired_job(job_id, expired_job.expires_at)
            removed = True
        return removed

    def _remember_retired_job(self, job_id: str, retired_at: datetime) -> None:
        self._retired_jobs.pop(job_id, None)
        self._retired_jobs[job_id] = retired_at
        while len(self._retired_jobs) > self._retired_job_cache_size:
            self._retired_jobs.popitem(last=False)

    def _prune_retired_jobs(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._retired_job_max_age_seconds)
        expired_job_ids = [
            job_id
            for job_id, retired_at in self._retired_jobs.items()
            if retired_at <= cutoff
        ]
        for job_id in expired_job_ids:
            self._retired_jobs.pop(job_id, None)


def _parse_block_template(
    raw_template: Any, *, fetched_at: datetime
) -> TemplateSnapshot:
    if not isinstance(raw_template, dict):
        raise ValueError("getblocktemplate returned a non-object payload")

    prevhash = _as_hex_string(raw_template.get("previousblockhash"), field_name="previousblockhash")
    bits = _as_hex_string(raw_template.get("bits"), field_name="bits")
    version = _as_uint32_hex(raw_template.get("version"), field_name="version")
    current_time = _as_uint32(raw_template.get("curtime"), field_name="curtime")
    (
        coinb1,
        coinb2,
        merkle_branch,
        preimage_context,
        authoritative_context,
    ) = _build_template_preimage_material(
        raw_template,
        current_time=current_time,
    )
    template_anchor_payload = {
        "previousblockhash": prevhash,
        "height": _optional_int(raw_template.get("height")),
        "bits": bits,
        "curtime": current_time,
        "coinbaseValue": preimage_context.get("coinbaseValue"),
        "transactionsDigest": preimage_context.get("transactionsDigest"),
        "coinbaseOutputsDigest": preimage_context.get("coinbaseOutputsDigest"),
    }
    template_anchor = hashlib.sha256(
        json.dumps(
            template_anchor_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return TemplateSnapshot(
        template_anchor=template_anchor,
        prevhash=prevhash,
        version=version,
        nbits=bits,
        ntime=f"{current_time:08x}",
        fetched_at=fetched_at,
        target_context={
            "bits": bits,
            "target": _optional_string(raw_template.get("target")),
            "height": _optional_int(raw_template.get("height")),
            "version": version,
            "curtime": current_time,
        },
        coinb1=coinb1,
        coinb2=coinb2,
        merkle_branch=tuple(merkle_branch),
        preimage_context=preimage_context,
        authoritative_context=authoritative_context,
    )


def _build_template_preimage_material(
    raw_template: dict[str, Any],
    *,
    current_time: int,
) -> tuple[str, str, list[str], dict[str, Any], dict[str, Any]]:
    height = _as_uint32(raw_template.get("height"), field_name="height")
    coinbase_value = _as_uint64(
        raw_template.get("coinbasevalue"),
        field_name="coinbasevalue",
    )
    coinbase_flags = _parse_coinbase_flags(raw_template.get("coinbaseaux"))
    transactions = _extract_template_transactions(raw_template.get("transactions"))
    transaction_hashes = [entry["hash"] for entry in transactions]
    transaction_data_hexes = tuple(entry.get("data") for entry in transactions)
    payout_outputs = _extract_template_outputs(raw_template)
    payout_total = sum(output["amount"] for output in payout_outputs)
    if payout_total > coinbase_value:
        raise ValueError(
            "getblocktemplate payout outputs exceed coinbasevalue"
        )

    remaining_amount = coinbase_value - payout_total
    outputs: list[dict[str, Any]] = []
    if remaining_amount > 0 or not payout_outputs:
        outputs.append(
            {
                "amount": remaining_amount,
                "script": PLACEHOLDER_PAYOUT_SCRIPT,
                "kind": "placeholder-miner",
            }
        )
    outputs.extend(payout_outputs)

    height_script = _encode_coinbase_height(height)
    extranonce_bytes = 8
    script_prefix = height_script + coinbase_flags
    script_length = len(script_prefix) + extranonce_bytes
    coinb1_bytes = (
        bytes.fromhex("01000000")
        + b"\x01"
        + (b"\x00" * 32)
        + bytes.fromhex("ffffffff")
        + _encode_varint(script_length)
        + script_prefix
    )
    coinb2_bytes = (
        bytes.fromhex("ffffffff")
        + _encode_varint(len(outputs))
        + b"".join(_serialize_tx_output(output) for output in outputs)
        + bytes.fromhex("00000000")
    )
    merkle_branch = _build_coinbase_merkle_branch(transaction_hashes)
    outputs_digest = hashlib.sha256(
        json.dumps(outputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    transactions_digest = hashlib.sha256(
        json.dumps(transaction_hashes, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    preimage_context = {
        "source": "template-derived",
        "coinb1Length": len(coinb1_bytes.hex()),
        "coinb2Length": len(coinb2_bytes.hex()),
        "merkleBranchLength": len(merkle_branch),
        "templateTransactionCount": len(transaction_hashes),
        "coinbaseOutputsCount": len(outputs),
        "coinbaseValue": coinbase_value,
        "coinbaseFlagsHex": coinbase_flags.hex(),
        "coinbaseOutputsDigest": outputs_digest,
        "transactionsDigest": transactions_digest,
        "placeholderPayout": remaining_amount > 0 or not payout_outputs,
    }
    authoritative_context = {
        "referenceCaptured": True,
        "authoritativeCoinbaseAvailable": False,
        "authoritativeOutputLayoutAvailable": True,
        "authoritativeNonOutputSegmentsAvailable": True,
        "coinb1HexLength": len(coinb1_bytes.hex()),
        "coinb2HexLength": len(coinb2_bytes.hex()),
        "coinb2Digest": hashlib.sha256(coinb2_bytes).hexdigest()[:24],
        "outputVectorDigest": outputs_digest,
        "transactionHashes": tuple(transaction_hashes),
        "transactionDataHexes": transaction_data_hexes,
        "transactionDataAvailableAll": all(
            isinstance(raw_tx, str) and bool(raw_tx) for raw_tx in transaction_data_hexes
        ),
        "coinbaseSegmentSummaries": {
            "coinbasePrefixBytes": {
                "offset": 0,
                "hexLength": (4 + 1 + 32 + 4) * 2,
                "hex": coinb1_bytes[: 4 + 1 + 32 + 4].hex(),
                "digest": hashlib.sha256(
                    coinb1_bytes[: 4 + 1 + 32 + 4]
                ).hexdigest()[:24],
            },
            "coinbaseLengthVarint": {
                "offset": 4 + 1 + 32 + 4,
                "hex": _encode_varint(script_length).hex(),
                "declaredScriptSigBytes": script_length,
            },
            "scriptSigTemplateBytes": {
                "offset": (4 + 1 + 32 + 4) + len(_encode_varint(script_length)),
                "hexLength": len(script_prefix.hex()),
                "hex": script_prefix.hex(),
                "digest": hashlib.sha256(script_prefix).hexdigest()[:24],
            },
            "extranonceRegion": {
                "offset": len(coinb1_bytes),
                "expectedTotalBytes": extranonce_bytes,
            },
            "postScriptSigSequence": {
                "offset": len(coinb1_bytes) + extranonce_bytes,
                "hex": coinb2_bytes[:4].hex(),
            },
            "outputCountVarint": {
                "offset": len(coinb1_bytes) + extranonce_bytes + 4,
                "hex": _encode_varint(len(outputs)).hex(),
                "value": len(outputs),
            },
            "coinbaseTail": {
                "offset": len(coinb1_bytes) + extranonce_bytes + len(coinb2_bytes) - 4,
                "locktimeHex": coinb2_bytes[-4:].hex(),
            },
        },
        "outputSummaries": [
            {
                "index": index,
                "kind": output["kind"],
                "amount": output["amount"],
                "scriptLength": len(output["script"]) // 2,
                "scriptHex": output["script"],
                "placeholderScript": output["script"] == PLACEHOLDER_PAYOUT_SCRIPT,
            }
            for index, output in enumerate(outputs)
        ],
    }
    return (
        coinb1_bytes.hex(),
        coinb2_bytes.hex(),
        merkle_branch,
        preimage_context,
        authoritative_context,
    )


def _as_hex_string(raw_value: Any, *, field_name: str) -> str:
    if not isinstance(raw_value, str):
        raise ValueError(f"getblocktemplate field {field_name} is missing")
    value = raw_value.strip().lower()
    if not value:
        raise ValueError(f"getblocktemplate field {field_name} is empty")
    return value


def _as_uint32(raw_value: Any, *, field_name: str) -> int:
    if not isinstance(raw_value, int):
        raise ValueError(f"getblocktemplate field {field_name} is missing")
    if raw_value < 0:
        raise ValueError(f"getblocktemplate field {field_name} is invalid")
    return raw_value


def _as_uint64(raw_value: Any, *, field_name: str) -> int:
    if not isinstance(raw_value, int):
        raise ValueError(f"getblocktemplate field {field_name} is missing")
    if raw_value < 0:
        raise ValueError(f"getblocktemplate field {field_name} is invalid")
    return raw_value


def _as_uint32_hex(raw_value: Any, *, field_name: str) -> str:
    return f"{_as_uint32(raw_value, field_name=field_name) & 0xFFFFFFFF:08x}"


def _optional_int(raw_value: Any) -> int | None:
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    return None


def _optional_string(raw_value: Any) -> str | None:
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    return None


def _parse_coinbase_flags(raw_value: Any) -> bytes:
    if raw_value in (None, ""):
        return b""
    if isinstance(raw_value, dict):
        raw_value = raw_value.get("flags")
    if raw_value in (None, ""):
        return b""
    if not isinstance(raw_value, str):
        raise ValueError("getblocktemplate coinbaseaux.flags is invalid")
    value = raw_value.strip()
    if not value:
        return b""
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("getblocktemplate coinbaseaux.flags must be hex") from exc


def _extract_template_transactions(raw_value: Any) -> list[dict[str, str | None]]:
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise ValueError("getblocktemplate transactions must be an array")

    transactions: list[dict[str, str | None]] = []
    for index, entry in enumerate(raw_value):
        if not isinstance(entry, dict):
            raise ValueError(f"getblocktemplate transaction {index} is invalid")
        raw_tx = entry.get("data")
        normalized_data = None
        if isinstance(raw_tx, str) and raw_tx.strip():
            normalized_data = raw_tx.strip().lower()
            _decode_hex(normalized_data, field_name=f"transaction data {index}")
        candidate = entry.get("hash") or entry.get("txid")
        if isinstance(candidate, str) and candidate.strip():
            normalized = candidate.strip().lower()
            _decode_hex(normalized, field_name=f"transaction hash {index}", expected_length=64)
            transactions.append({"hash": normalized, "data": normalized_data})
            continue
        if normalized_data is not None:
            tx_bytes = bytes.fromhex(normalized_data)
            transactions.append(
                {
                    "hash": hashlib.sha256(hashlib.sha256(tx_bytes).digest()).digest()[::-1].hex(),
                    "data": normalized_data,
                }
            )
            continue
        raise ValueError(
            f"getblocktemplate transaction {index} is missing hash and data"
        )
    return transactions


def _extract_template_outputs(raw_template: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for field_name in ("masternode", "superblock", "foundation"):
        raw_value = raw_template.get(field_name)
        if raw_value in (None, ""):
            continue
        if isinstance(raw_value, dict) and not raw_value:
            continue
        entries = raw_value if isinstance(raw_value, list) else [raw_value]
        if not isinstance(entries, list):
            raise ValueError(f"getblocktemplate field {field_name} is invalid")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"getblocktemplate field {field_name}[{index}] is invalid"
                )
            script = _optional_string(entry.get("script"))
            amount = entry.get("amount")
            if script is None or not isinstance(amount, int) or amount < 0:
                raise ValueError(
                    f"getblocktemplate field {field_name}[{index}] is missing script or amount"
                )
            _decode_hex(script.lower(), field_name=f"{field_name}[{index}].script")
            outputs.append(
                {
                    "amount": amount,
                    "script": script.lower(),
                    "kind": field_name,
                }
            )
    return outputs


def _encode_coinbase_height(height: int) -> bytes:
    encoded_number = _encode_script_number(height)
    return _encode_varint(len(encoded_number)) + encoded_number


def _encode_script_number(value: int) -> bytes:
    if value < 0:
        raise ValueError("script number must not be negative")
    if value == 0:
        return b""
    encoded = bytearray()
    remaining = value
    while remaining:
        encoded.append(remaining & 0xFF)
        remaining >>= 8
    if encoded[-1] & 0x80:
        encoded.append(0)
    return bytes(encoded)


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint must not be negative")
    if value < 0xFD:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, byteorder="little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, byteorder="little")
    return b"\xff" + value.to_bytes(8, byteorder="little")


def _serialize_tx_output(output: dict[str, Any]) -> bytes:
    amount = output["amount"]
    script = output["script"]
    if not isinstance(amount, int) or amount < 0:
        raise ValueError("coinbase output amount is invalid")
    script_bytes = _decode_hex(script, field_name="coinbase output script")
    return (
        amount.to_bytes(8, byteorder="little", signed=False)
        + _encode_varint(len(script_bytes))
        + script_bytes
    )


def _build_coinbase_merkle_branch(transaction_hashes: list[str]) -> list[str]:
    if not transaction_hashes:
        return []

    layer = [bytes.fromhex(tx_hash)[::-1] for tx_hash in transaction_hashes]
    branch: list[str] = []
    while layer:
        sibling = layer[0]
        branch.append(sibling[::-1].hex())
        remaining = layer[1:]
        if not remaining:
            break
        if len(remaining) % 2 == 1:
            remaining.append(remaining[-1])
        layer = [
            hashlib.sha256(
                hashlib.sha256(remaining[index] + remaining[index + 1]).digest()
            ).digest()
            for index in range(0, len(remaining), 2)
        ]
    return branch


def _decode_hex(
    raw_value: str,
    *,
    field_name: str,
    expected_length: int | None = None,
) -> bytes:
    value = raw_value.strip().lower()
    if expected_length is not None and len(value) != expected_length:
        raise ValueError(f"{field_name} must be {expected_length}-character hex")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be hex") from exc

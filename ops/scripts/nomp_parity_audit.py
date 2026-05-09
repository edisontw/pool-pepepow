#!/usr/bin/env python3
"""Bounded NOMP parity audit for PEPEW Stratum share reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from miner_hash_correlation import (  # noqa: E402
    evidence_key,
    hash_meets_target,
    norm_hex,
    parse_miner_log,
    reverse_hex_bytes,
    yes_no,
)


def double_sha256(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()


def bytes_from_hex(value: Any, expected_bytes: int | None = None) -> bytes | None:
    value = norm_hex(value)
    if not value:
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None
    if expected_bytes is not None and len(raw) != expected_bytes:
        return None
    return raw


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def row_status(evidence: dict[str, Any], miner_row: dict[str, Any]) -> str:
    status = str(miner_row.get("poolStatus") or "unknown")
    if status != "unknown":
        return status
    if evidence.get("rejectReason"):
        return str(evidence["rejectReason"])
    if evidence.get("shareHashValidationStatus") == "share-hash-valid":
        return "accepted"
    return "unknown"


def matched_rows(
    miner_log: Path,
    submit_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    miner_rows, _counters = parse_miner_log(miner_log)
    evidence_by_key = {evidence_key(row): row for row in submit_rows if all(evidence_key(row))}
    matched: list[dict[str, Any]] = []
    for miner_row in miner_rows:
        evidence = evidence_by_key.get(evidence_key(miner_row))
        if evidence is None:
            continue
        miner_hash = norm_hex(miner_row.get("minerReportedHash"))
        local_hash = norm_hex(evidence.get("localComputedHash"))
        target = norm_hex(evidence.get("shareTargetUsed") or evidence.get("shareTarget"))
        local_meets = evidence.get("meetsShareTarget")
        if not isinstance(local_meets, bool):
            local_meets = hash_meets_target(local_hash, target)
        matched.append(
            {
                "miner": miner_row,
                "evidence": evidence,
                "poolStatus": row_status(evidence, miner_row),
                "target": target,
                "minerEqualsLocal": bool(miner_hash and local_hash and miner_hash == local_hash),
                "minerMeetsTarget": hash_meets_target(miner_hash, target),
                "localMeetsTarget": local_meets,
            }
        )
    return matched


def select_rows(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    selected: list[tuple[str, dict[str, Any]]] = []
    rejected = next(
        (
            row
            for row in rows
            if row["poolStatus"] != "accepted" and row["minerMeetsTarget"] is True
        ),
        None,
    )
    accepted = next(
        (
            row
            for row in rows
            if row["poolStatus"] == "accepted" and not row["minerEqualsLocal"]
        ),
        None,
    )
    if rejected is not None:
        selected.append(("Selected rejected row", rejected))
    if accepted is not None:
        selected.append(("Selected accepted row", accepted))
    return selected


def notify_for_row(row: dict[str, Any], notify_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    evidence = row["evidence"]
    session_id = evidence.get("sessionId")
    job_id = evidence.get("jobId")
    for notify in reversed(notify_rows):
        if notify.get("jobId") == job_id and (
            not session_id or notify.get("sessionId") == session_id
        ):
            return notify
    return None


def reverse_byte_order_words_4(value: str) -> str | None:
    raw = bytes_from_hex(value, 32)
    if raw is None:
        return None
    return b"".join(raw[index : index + 4][::-1] for index in range(0, len(raw), 4)).hex()


def rpc_previousblockhash_for(
    evidence: dict[str, Any],
    notify: dict[str, Any] | None,
) -> tuple[str | None, str]:
    for field in ("submitPrevhashCached", "preimagePrevhash"):
        value = norm_hex(evidence.get(field))
        if bytes_from_hex(value, 32) is not None:
            return value, f"used {field} as rpcData.previousblockhash"

    for field, source in (
        ("notifyPrevhashSent", evidence),
        ("submitPrevhashUsed", evidence),
        ("prevhashSent", notify or {}),
    ):
        derived = reverse_byte_order_words_4(norm_hex(source.get(field)))
        if derived is not None:
            return (
                derived,
                f"derived rpcData.previousblockhash by applying NOMP reverseByteOrder inverse to {field}",
            )

    return None, "missing rpcData.previousblockhash and no equivalent notify prevhash derivation was available"


def merkle_tree_with_first(coinbase_hash: bytes, branches: Any) -> bytes | None:
    root = coinbase_hash
    if not isinstance(branches, list):
        branches = []
    for branch in branches:
        sibling = bytes_from_hex(branch, 32)
        if sibling is None:
            return None
        root = double_sha256(root + sibling[::-1])
    return root


def nomp_header80(
    evidence: dict[str, Any],
    notify: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    coinb1 = norm_hex(evidence.get("issuedJobCoinb1"))
    coinb2 = norm_hex(evidence.get("issuedJobCoinb2"))
    extranonce1 = norm_hex(evidence.get("extranonce1"))
    extranonce2 = norm_hex(evidence.get("extranonce2"))
    final_coinbase = f"{coinb1}{extranonce1}{extranonce2}{coinb2}"
    coinbase = bytes_from_hex(final_coinbase)
    if coinbase is None:
        return {"error": "missing or invalid coinbase parts"}, None

    coinbase_hash = double_sha256(coinbase)
    merkle_root = merkle_tree_with_first(coinbase_hash, evidence.get("issuedJobMerkleBranch"))
    if merkle_root is None:
        return {"error": "missing or invalid merkle branch"}, None
    mr_tree_rev_hex = merkle_root[::-1].hex()

    previousblockhash, prevhash_source = rpc_previousblockhash_for(evidence, notify)
    nonce = bytes_from_hex(evidence.get("nonce"), 4)
    bits = bytes_from_hex(evidence.get("submitNbitsUsed") or evidence.get("notifyNbitsSent") or evidence.get("preimageNbits"), 4)
    ntime = bytes_from_hex(evidence.get("submitNtimeUsed") or evidence.get("ntime"), 4)
    merkle_reversed = bytes_from_hex(mr_tree_rev_hex, 32)
    prevhash = bytes_from_hex(previousblockhash, 32)
    version_hex = norm_hex(
        evidence.get("submitVersionUsed")
        or evidence.get("notifyVersionSent")
        or evidence.get("preimageVersion")
    )
    try:
        version = int(version_hex, 16)
    except ValueError:
        version = -1

    if None in (nonce, bits, ntime, merkle_reversed, prevhash) or not (0 <= version <= 0xFFFFFFFF):
        return {
            "error": "missing or invalid NOMP header field",
            "previousblockhashSource": prevhash_source,
        }, None

    header = bytearray(80)
    header[0:4] = nonce
    header[4:8] = bits
    header[8:12] = ntime
    header[12:44] = merkle_reversed
    header[44:76] = prevhash
    header[76:80] = version.to_bytes(4, byteorder="big")
    header80 = bytes(header)[::-1]
    return {
        "finalCoinbaseHex": final_coinbase,
        "coinbaseHash": coinbase_hash.hex(),
        "merkleRoot": merkle_root.hex(),
        "mrTreeRevHex": mr_tree_rev_hex,
        "previousblockhash": previousblockhash,
        "previousblockhashSource": prevhash_source,
        "versionUInt32BE": f"{version:08x}",
    }, header80.hex()


def hoohash_header80(header_hex: str, pool_core_dir: Path) -> tuple[str | None, str | None]:
    header = bytes_from_hex(header_hex, 80)
    if header is None:
        return None, "invalid header80"
    if str(pool_core_dir) not in sys.path:
        sys.path.insert(0, str(pool_core_dir))
    try:
        from pepepow_pow import blake3_hash, hoohash_v110  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return None, f"hoohash oracle unavailable: {exc}"

    masked_header = header[:76] + (b"\x00" * 4)
    header_hash = blake3_hash(header)
    matrix_seed = blake3_hash(masked_header)
    nonce = int.from_bytes(header[76:80], byteorder="little", signed=False)
    return hoohash_v110(matrix_seed, header_hash, nonce)[::-1].hex(), None


def short(value: Any, chars: int = 24) -> str:
    value = norm_hex(value)
    if not value:
        return "-"
    if len(value) <= chars * 2:
        return value
    return f"{value[:chars]}...{value[-chars:]}"


def print_kv(name: str, value: Any) -> None:
    if isinstance(value, bool):
        value = yes_no(value)
    elif value is None:
        value = "-"
    print(f"{name}: {value}")


def print_row(
    label: str,
    row: dict[str, Any],
    notify: dict[str, Any] | None,
    pool_core_dir: Path,
) -> dict[str, Any]:
    evidence = row["evidence"]
    miner = row["miner"]
    miner_hash = norm_hex(miner.get("minerReportedHash"))
    local_hash = norm_hex(evidence.get("localComputedHash"))
    current_header = norm_hex(evidence.get("header80Hex"))
    context, header_hex = nomp_header80(evidence, notify)
    nomp_hash, hash_error = hoohash_header80(header_hex or "", pool_core_dir) if header_hex else (None, "missing nompHeader80Hex")

    print(label)
    for name, value in (
        ("jobId", evidence.get("jobId")),
        ("extranonce1", evidence.get("extranonce1")),
        ("extranonce2", evidence.get("extranonce2")),
        ("ntime", evidence.get("ntime")),
        ("nonce", evidence.get("nonce")),
        ("poolStatus", row["poolStatus"]),
        ("rejectReason", evidence.get("rejectReason")),
        ("shareTarget", row["target"]),
        ("minerReportedHash", miner_hash),
        ("currentPoolHeader80Hex", current_header),
        ("currentPoolLocalComputedHash", local_hash),
        ("nompHeader80Hex", header_hex),
        ("nompHash", nomp_hash),
        ("nompHashOracleStatus", hash_error or "available"),
        ("nompHash == minerReportedHash", nomp_hash == miner_hash if nomp_hash else None),
        ("reversed nompHash == minerReportedHash", reverse_hex_bytes(nomp_hash or "") == miner_hash if nomp_hash else None),
        ("nompHash meets share target", hash_meets_target(nomp_hash or "", row["target"]) if nomp_hash else None),
        ("nompHeader80 == current pool header80", header_hex == current_header if header_hex else None),
        ("previousblockhashSource", context.get("previousblockhashSource")),
        ("rpcData.previousblockhash", context.get("previousblockhash")),
        ("coinbaseHash", context.get("coinbaseHash")),
        ("merkleRoot", context.get("merkleRoot")),
        ("mr_tree_rev_hex", context.get("mrTreeRevHex")),
        ("version UInt32BE", context.get("versionUInt32BE")),
        ("notifyEvidenceMatched", evidence.get("notifyEvidenceMatched")),
        ("notifyVsSubmitJobCacheDigestMatch", evidence.get("notifyVsSubmitJobCacheDigestMatch")),
    ):
        print_kv(name, value)
    if context.get("error"):
        print_kv("nompReconstructionError", context.get("error"))
    print()

    return {
        "label": label,
        "minerMatch": nomp_hash == miner_hash if nomp_hash else None,
        "minerReverseMatch": reverse_hex_bytes(nomp_hash or "") == miner_hash if nomp_hash else None,
        "headerDiffers": header_hex != current_header if header_hex else None,
        "hashAvailable": nomp_hash is not None,
        "nompHeader80PrefixSuffix": short(header_hex),
        "currentHeader80PrefixSuffix": short(current_header),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("miner_log")
    parser.add_argument("tail_lines", type=int)
    parser.add_argument("submit_tail")
    parser.add_argument("notify_tail")
    parser.add_argument("pool_core_dir")
    args = parser.parse_args()

    miner_log = Path(args.miner_log)
    if not miner_log.is_file():
        print(f"nomp_parity_audit: miner log not found: {miner_log}", file=sys.stderr)
        return 1

    submit_rows = read_jsonl(Path(args.submit_tail))
    notify_rows = read_jsonl(Path(args.notify_tail))
    rows = matched_rows(miner_log, submit_rows)
    selected = select_rows(rows)

    print("Summary")
    print("nomp_parity_audit: ready")
    print(f"minerLog: {miner_log}")
    print(f"boundedTailLines: {args.tail_lines}")
    print(f"submitEvidenceRowsRead: {len(submit_rows)}")
    print(f"notifyEvidenceRowsRead: {len(notify_rows)}")
    print(f"matchedRows: {len(rows)}")
    print(f"selectedRows: {len(selected)}")
    print()

    print("NOMP reference points used")
    print("- coinbase = coinbase1 + extranonce1 + extranonce2 + coinbase2")
    print("- coinbaseHash = sha256d(coinbase)")
    print("- merkle root = merkleTree.withFirst(coinbaseHash), with notify branches reversed back to internal bytes")
    print("- mr_tree_rev_hex = reverseBuffer(merkleRoot)")
    print("- serializeHeader writes nonce, bits, nTime, merkleRoot, rpcData.previousblockhash, version UInt32BE, then reverses all 80 bytes")
    print("- share target comparison treats the reported hash hex as a big-endian integer")
    print()

    if not selected:
        print("NOMP parity result")
        print("selection: no matched rejected+accepted pair satisfied the bounded audit criteria")
        print("hint: retry with a bounded larger tail up to 1000")
        return 0

    results = []
    for label, row in selected:
        results.append(print_row(label, row, notify_for_row(row, notify_rows), Path(args.pool_core_dir)))

    print("NOMP parity result")
    for result in results:
        print(
            f"{result['label']}: "
            f"nompHashMatchesMiner={yes_no(result['minerMatch'])} "
            f"reversedNompHashMatchesMiner={yes_no(result['minerReverseMatch'])} "
            f"nompHeaderDiffersFromCurrentPool={yes_no(result['headerDiffers'])} "
            f"hashOracleAvailable={yes_no(result['hashAvailable'])}"
        )
        print(f"  nompHeader80: {result['nompHeader80PrefixSuffix']}")
        print(f"  currentHeader80: {result['currentHeader80PrefixSuffix']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

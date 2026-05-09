#!/usr/bin/env python3
"""Trace one or two matched miner submits through the pool preimage."""

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


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def double_sha256(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()


def short_hex(value: Any, chars: int = 24) -> str:
    value = norm_hex(value)
    if not value:
        return "-"
    if len(value) <= chars * 2:
        return value
    return f"{value[:chars]}...{value[-chars:]}"


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


def bytes_from_hex(value: Any, expected_len: int | None = None) -> bytes | None:
    value = norm_hex(value)
    if not value:
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None
    if expected_len is not None and len(raw) != expected_len:
        return None
    return raw


def apply_merkle_branch(coinbase_hash: bytes, merkle_branch: Any) -> bytes | None:
    if not isinstance(merkle_branch, list):
        merkle_branch = []
    root = coinbase_hash
    for sibling_hash in merkle_branch:
        sibling = bytes_from_hex(sibling_hash, 32)
        if sibling is None:
            return None
        root = double_sha256(root + sibling[::-1])
    return root


def hoohash_header80(header: bytes, pool_core_dir: Path) -> str | None:
    if len(header) != 80:
        return None
    if str(pool_core_dir) not in sys.path:
        sys.path.insert(0, str(pool_core_dir))
    from pepepow_pow import blake3_hash, hoohash_v110  # noqa: PLC0415

    masked_header = header[:76] + (b"\x00" * 4)
    header_hash = blake3_hash(header)
    matrix_seed = blake3_hash(masked_header)
    nonce = int.from_bytes(header[76:80], byteorder="little", signed=False)
    return hoohash_v110(matrix_seed, header_hash, nonce)[::-1].hex()


def build_header_from_coinbase(
    evidence: dict[str, Any],
    coinbase_hex: str,
) -> tuple[str | None, str | None, str | None]:
    coinbase = bytes_from_hex(coinbase_hex)
    if coinbase is None:
        return None, None, None
    coinbase_hash = double_sha256(coinbase)
    merkle_root = apply_merkle_branch(coinbase_hash, evidence.get("issuedJobMerkleBranch"))
    if merkle_root is None:
        return coinbase_hash.hex(), None, None

    header = bytes_from_hex(evidence.get("header80Hex"), 80)
    if header is None:
        return coinbase_hash.hex(), merkle_root.hex(), None
    rebuilt_header = header[:36] + merkle_root + header[68:]
    return coinbase_hash.hex(), merkle_root.hex(), rebuilt_header.hex()


def row_status(evidence: dict[str, Any], miner_row: dict[str, Any]) -> str:
    status = miner_row.get("poolStatus") or "unknown"
    if status != "unknown":
        return str(status)
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
        target = norm_hex(evidence.get("shareTargetUsed") or evidence.get("shareTarget"))
        miner_hash = norm_hex(miner_row.get("minerReportedHash"))
        local_hash = norm_hex(evidence.get("localComputedHash"))
        merged = {
            "miner": miner_row,
            "evidence": evidence,
            "target": target,
            "poolStatus": row_status(evidence, miner_row),
            "minerEqualsLocal": miner_hash == local_hash if miner_hash and local_hash else False,
            "minerMeetsTargetCanonical": hash_meets_target(miner_hash, target),
            "minerMeetsTargetReversed": hash_meets_target(reverse_hex_bytes(miner_hash), target),
            "localMeetsTarget": evidence.get("meetsShareTarget")
            if isinstance(evidence.get("meetsShareTarget"), bool)
            else hash_meets_target(local_hash, target),
        }
        matched.append(merged)
    return matched


def select_rows(
    rows: list[dict[str, Any]],
    status_filter: str | None,
    job_id: str | None,
    nonce: str | None,
) -> list[dict[str, Any]]:
    filtered = rows
    if job_id:
        filtered = [row for row in filtered if row["evidence"].get("jobId") == job_id]
    if nonce:
        nonce = norm_hex(nonce)
        filtered = [row for row in filtered if norm_hex(row["evidence"].get("nonce")) == nonce]
    if status_filter == "accepted":
        filtered = [row for row in filtered if row["poolStatus"] == "accepted"]
    elif status_filter == "rejected":
        filtered = [row for row in filtered if row["poolStatus"] != "accepted"]

    if status_filter or job_id or nonce:
        return filtered[:2]

    selected: list[dict[str, Any]] = []
    rejected = next(
        (
            row
            for row in filtered
            if row["poolStatus"] != "accepted"
            and row["minerMeetsTargetCanonical"] is True
            and not row["minerEqualsLocal"]
        ),
        None,
    )
    accepted = next(
        (
            row
            for row in filtered
            if row["poolStatus"] == "accepted" and not row["minerEqualsLocal"]
        ),
        None,
    )
    if rejected:
        selected.append(rejected)
    if accepted:
        selected.append(accepted)
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


def print_kv(name: str, value: Any) -> None:
    if isinstance(value, bool):
        value = yes_no(value)
    elif value is None:
        value = "-"
    print(f"{name}: {value}")


def header_split(header_hex: str) -> dict[str, str]:
    header = norm_hex(header_hex)
    return {
        "version bytes": header[0:8],
        "prevhash bytes": header[8:72],
        "merkle root bytes": header[72:136],
        "ntime bytes": header[136:144],
        "nbits bytes": header[144:152],
        "nonce bytes": header[152:160],
    }


def variant_headers(evidence: dict[str, Any]) -> list[tuple[str, str | None]]:
    header = bytes_from_hex(evidence.get("header80Hex"), 80)
    variants: list[tuple[str, str | None]] = []
    if header is None:
        return [
            ("current header80 as-is", None),
            ("current header80 with nonce bytes reversed", None),
            ("current header80 with ntime bytes reversed", None),
            ("current header80 with ntime+nonce reversed", None),
            ("current header80 with merkle root reversed", None),
            ("current header80 with prevhash reversed", None),
            ("current header80 with full header80 reversed", None),
            ("current header80 but hash output reversed before compare", None),
        ]
    variants.append(("current header80 as-is", header.hex()))
    variants.append(("current header80 with nonce bytes reversed", (header[:76] + header[76:80][::-1]).hex()))
    variants.append(("current header80 with ntime bytes reversed", (header[:68] + header[68:72][::-1] + header[72:]).hex()))
    variants.append(("current header80 with ntime+nonce reversed", (header[:68] + header[68:72][::-1] + header[72:76] + header[76:80][::-1]).hex()))
    variants.append(("current header80 with merkle root reversed", (header[:36] + header[36:68][::-1] + header[68:]).hex()))
    variants.append(("current header80 with prevhash reversed", (header[:4] + header[4:36][::-1] + header[36:]).hex()))
    variants.append(("current header80 with full header80 reversed", header[::-1].hex()))
    variants.append(("current header80 but hash output reversed before compare", header.hex()))
    return variants


def coinbase_variants(evidence: dict[str, Any]) -> list[tuple[str, str | None]]:
    coinb1 = norm_hex(evidence.get("issuedJobCoinb1"))
    coinb2 = norm_hex(evidence.get("issuedJobCoinb2"))
    extranonce1 = norm_hex(evidence.get("extranonce1"))
    extranonce2 = norm_hex(evidence.get("extranonce2"))
    variants: list[tuple[str, str | None]] = []
    ex2_reversed = reverse_hex_bytes(extranonce2)
    if coinb1 and coinb2 and extranonce1 and ex2_reversed:
        _coinbase_hash, _merkle_root, header_hex = build_header_from_coinbase(
            evidence, f"{coinb1}{extranonce1}{ex2_reversed}{coinb2}"
        )
        variants.append(("current final coinbase with extranonce2 interpreted as little-endian before merkle", header_hex))
    else:
        variants.append(("current final coinbase with extranonce2 interpreted as little-endian before merkle", None))
    if coinb1 and coinb2 and extranonce1 and extranonce2:
        _coinbase_hash, _merkle_root, header_hex = build_header_from_coinbase(
            evidence, f"{coinb1}{extranonce2}{extranonce1}{coinb2}"
        )
        variants.append(("current final coinbase with extranonce1/extranonce2 order swapped", header_hex))
    else:
        variants.append(("current final coinbase with extranonce1/extranonce2 order swapped", None))
    return variants


def recompute_variants(
    evidence: dict[str, Any],
    miner_hash: str,
    target: str,
    pool_core_dir: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, header_hex in variant_headers(evidence) + coinbase_variants(evidence):
        computed_hash = None
        if header_hex:
            header = bytes_from_hex(header_hex, 80)
            if header is not None:
                computed_hash = hoohash_header80(header, pool_core_dir)
                if name == "current header80 but hash output reversed before compare" and computed_hash:
                    computed_hash = reverse_hex_bytes(computed_hash)
        rows.append(
            {
                "variant": name,
                "computedHash": computed_hash,
                "equalsMiner": computed_hash == miner_hash if computed_hash else False,
                "reversedEqualsMiner": reverse_hex_bytes(computed_hash or "") == miner_hash
                if computed_hash
                else False,
                "meetsTarget": hash_meets_target(computed_hash or "", target),
            }
        )
    return rows


def print_trace(
    label: str,
    row: dict[str, Any],
    notify: dict[str, Any] | None,
    pool_core_dir: Path,
) -> bool:
    evidence = row["evidence"]
    miner = row["miner"]
    target = row["target"]
    miner_hash = norm_hex(miner.get("minerReportedHash"))
    local_hash = norm_hex(evidence.get("localComputedHash"))
    header_hex = norm_hex(evidence.get("header80Hex"))
    final_coinbase = norm_hex(evidence.get("coinbaseLocalHex"))
    coinbase_hash = norm_hex(evidence.get("coinbaseHashLocal"))
    merkle_root = norm_hex(evidence.get("merkleRoot"))
    final_coinbase_bytes = bytes_from_hex(final_coinbase)
    recomputed_coinbase_hash = double_sha256(final_coinbase_bytes).hex() if final_coinbase_bytes else ""

    print(f"=== {label} ===")
    print("A. Submit identity")
    for name, value in (
        ("timestamp", evidence.get("timestamp")),
        ("jobId", evidence.get("jobId")),
        ("extranonce1", evidence.get("extranonce1")),
        ("extranonce2", evidence.get("extranonce2")),
        ("ntime", evidence.get("ntime")),
        ("nonce", evidence.get("nonce")),
        ("minerReportedHash", miner_hash),
        ("localComputedHash", local_hash),
        ("independentAuthoritativeShareHash", evidence.get("independentAuthoritativeShareHash")),
        ("shareTarget", target),
        ("minerHashMeetsTarget canonical", row["minerMeetsTargetCanonical"]),
        ("minerHashMeetsTarget reversed", row["minerMeetsTargetReversed"]),
        ("localHashMeetsTarget", row["localMeetsTarget"]),
        ("pool status", row["poolStatus"]),
        ("reject reason", evidence.get("rejectReason")),
    ):
        print_kv(name, value)

    print("B. Notify payload")
    if notify is None:
        print("notify: missing from bounded tail")
    else:
        for name, value in (
            ("notify jobId", notify.get("jobId")),
            ("prevhash sent", notify.get("prevhashSent")),
            ("coinbase1 length", notify.get("coinbase1Len")),
            ("coinbase1 prefix/suffix", f"{notify.get('coinbase1Prefix')}...{notify.get('coinbase1Suffix')}"),
            ("coinbase1 sha256", notify.get("coinbase1Sha256")),
            ("coinbase2 length", notify.get("coinbase2Len")),
            ("coinbase2 prefix/suffix", f"{notify.get('coinbase2Prefix')}...{notify.get('coinbase2Suffix')}"),
            ("coinbase2 sha256", notify.get("coinbase2Sha256")),
            ("merkle branch count", notify.get("merkleBranchCount")),
            ("merkle branch digest", notify.get("merkleBranchDigest")),
            ("version sent", notify.get("versionSent")),
            ("nbits sent", notify.get("nbitsSent")),
            ("ntime sent", notify.get("ntimeSent")),
            ("cleanJobs", notify.get("cleanJobs")),
            ("extranonce1", notify.get("extranonce1")),
            ("extranonce2Size", notify.get("extranonce2Size")),
        ):
            print_kv(name, value)

    print("C. Submit reconstruction")
    print_kv("finalCoinbaseHex length bytes", len(final_coinbase) // 2 if final_coinbase else None)
    print_kv("finalCoinbaseHex prefix/suffix", short_hex(final_coinbase, 48))
    print_kv("finalCoinbaseSha256", sha256_hex(final_coinbase_bytes) if final_coinbase_bytes else None)
    print_kv("coinbaseTxid / coinbaseHash used in merkle root", coinbase_hash or recomputed_coinbase_hash)
    print_kv("recomputedCoinbaseHash", recomputed_coinbase_hash or None)
    print_kv("merkleRootHex", merkle_root)
    print_kv("header80Hex length bytes", len(header_hex) // 2 if header_hex else None)
    print_kv("header80Hex", header_hex if len(header_hex) == 160 else short_hex(header_hex))
    if len(header_hex) == 160:
        for name, value in header_split(header_hex).items():
            print_kv(name, value)
    print_kv("hoohash input hex length bytes", len(header_hex) // 2 if header_hex else None)
    print_kv("hoohash input prefix/suffix", short_hex(header_hex, 48))
    print_kv("localComputedHash", local_hash)

    print("D. Miner hash reverse checks")
    print_kv("minerReportedHash canonical int meets share target", hash_meets_target(miner_hash, target))
    print_kv("minerReportedHash reversed bytes meets share target", hash_meets_target(reverse_hex_bytes(miner_hash), target))
    print_kv("localComputedHash canonical int meets share target", hash_meets_target(local_hash, target))
    print_kv("localComputedHash reversed bytes meets share target", hash_meets_target(reverse_hex_bytes(local_hash), target))

    print("E. Exact-match targeted recompute attempts")
    any_exact = False
    for result in recompute_variants(evidence, miner_hash, target, pool_core_dir):
        any_exact = any_exact or bool(result["equalsMiner"] or result["reversedEqualsMiner"])
        print(
            "variant: "
            f"{result['variant']} | computedHash={result['computedHash'] or '-'} "
            f"| computedHash==minerReportedHash={yes_no(result['equalsMiner'])} "
            f"| computedHashReversed==minerReportedHash={yes_no(result['reversedEqualsMiner'])} "
            f"| computedHashMeetsTarget={yes_no(result['meetsTarget'])}"
        )
    print(f"exactMatchFound: {yes_no(any_exact)}")
    print()
    return any_exact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("miner_log")
    parser.add_argument("tail_lines", type=int)
    parser.add_argument("submit_tail")
    parser.add_argument("notify_tail")
    parser.add_argument("pool_core_dir")
    parser.add_argument("--status", choices=("accepted", "rejected"))
    parser.add_argument("--job-id")
    parser.add_argument("--nonce")
    args = parser.parse_args()

    miner_log = Path(args.miner_log)
    if not miner_log.is_file():
        print(f"single-submit-preimage-trace: miner log not found: {miner_log}", file=sys.stderr)
        return 1

    submit_rows = read_jsonl(Path(args.submit_tail))
    notify_rows = read_jsonl(Path(args.notify_tail))
    rows = matched_rows(miner_log, submit_rows)
    selected = select_rows(rows, args.status, args.job_id, args.nonce)

    print("single_submit_preimage_trace: ready")
    print(f"minerLog: {miner_log}")
    print(f"boundedTailLines: {args.tail_lines}")
    print(f"submitEvidenceRowsRead: {len(submit_rows)}")
    print(f"notifyEvidenceRowsRead: {len(notify_rows)}")
    print(f"matchedRows: {len(rows)}")
    print(f"selectedRows: {len(selected)}")
    print()

    if not selected:
        print("selection: no matched row satisfied the requested filters")
        print("hint: retry with a bounded larger tail such as 1000, or pass --job-id and --nonce from a matched row")
        return 0

    any_exact = False
    for index, row in enumerate(selected, start=1):
        label = "selected rejected row" if row["poolStatus"] != "accepted" else "selected accepted row"
        if len(selected) == 1:
            label = f"{label} #{index}"
        notify = notify_for_row(row, notify_rows)
        any_exact = print_trace(label, row, notify, Path(args.pool_core_dir)) or any_exact

    print("summary:")
    print(f"exactMatchFoundAnySelectedRow: {yes_no(any_exact)}")
    if any_exact:
        print("interpretation: a targeted recompute exactly matched minerReportedHash; inspect the matching variant above for the field convention mismatch")
    else:
        print("interpretation: no targeted recompute matched minerReportedHash; pool lacks miner preimage visibility for this mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

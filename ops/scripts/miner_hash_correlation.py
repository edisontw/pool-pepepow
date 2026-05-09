#!/usr/bin/env python3
"""Correlate hoo_gpu -P miner hashes with bounded pool submit evidence."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOLUTION_RE = re.compile(
    r"PEPEW job (?P<job>[^ ]+) solution found! "
    r"nonce=(?P<nonce>[0-9]+) xnonce2=(?P<xnonce2>[0-9]+) "
    r"hash=(?P<hash>[0-9a-fA-F]{64})"
)
WIRE_JSON_RE = re.compile(r"\[User\]\s+(?P<dir>[<>])\s+(?P<json>\{.*\})\s*$")


def norm_hex(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def reverse_hex_bytes(value: str) -> str:
    value = norm_hex(value)
    if len(value) % 2:
        return ""
    try:
        bytes.fromhex(value)
    except ValueError:
        return ""
    return bytes.fromhex(value)[::-1].hex()


def prefix(value: Any, chars: int = 12) -> str:
    value = norm_hex(value)
    if not value:
        return "-"
    return value[:chars]


def yes_no(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "-"


def hash_meets_target(hash_hex: str, target_hex: str) -> bool | None:
    hash_hex = norm_hex(hash_hex)
    target_hex = norm_hex(target_hex)
    if not hash_hex or not target_hex:
        return None
    try:
        return int(hash_hex, 16) <= int(target_hex, 16)
    except ValueError:
        return None


def classify_response(payload: dict[str, Any]) -> str:
    if payload.get("result") is True and payload.get("error") is None:
        return "accepted"
    error = payload.get("error")
    if isinstance(error, list) and len(error) > 1:
        reason = str(error[1]).lower()
        if "low difficulty" in reason:
            return "low-difficulty"
        if "stale" in reason:
            return "stale"
        return reason.replace(" ", "-")
    if error:
        return "rejected"
    return "unknown"


def parse_miner_log(path: Path) -> tuple[list[dict[str, Any]], Counter[str]]:
    counters: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    pending_solution: dict[str, Any] | None = None
    pending_statuses: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            solution = SOLUTION_RE.search(line)
            if solution:
                counters["parsed miner solutions"] += 1
                pending_solution = {
                    "jobId": solution.group("job"),
                    "minerDecimalNonce": int(solution.group("nonce")),
                    "minerDecimalXnonce2": int(solution.group("xnonce2")),
                    "minerReportedHash": norm_hex(solution.group("hash")),
                }
                continue

            wire = WIRE_JSON_RE.search(line)
            if not wire:
                continue

            try:
                payload = json.loads(wire.group("json"))
            except json.JSONDecodeError:
                continue

            if wire.group("dir") == ">" and payload.get("method") == "mining.submit":
                counters["parsed miner submits"] += 1
                params = payload.get("params")
                if not isinstance(params, list) or len(params) < 5:
                    pending_solution = None
                    continue
                job_id = str(params[1])
                if pending_solution and pending_solution.get("jobId") == job_id:
                    row = {
                        **pending_solution,
                        "wallet": str(params[0]),
                        "extranonce2": norm_hex(params[2]),
                        "ntime": norm_hex(params[3]),
                        "nonce": norm_hex(params[4]),
                        "poolStatus": "unknown",
                    }
                    rows.append(row)
                    pending_statuses.append(row)
                    counters["paired solution+submit rows"] += 1
                pending_solution = None
                continue

            if wire.group("dir") == "<" and pending_statuses:
                if "result" in payload or payload.get("error") is not None:
                    pending_statuses.pop(0)["poolStatus"] = classify_response(payload)

    return rows, counters


def evidence_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("jobId") or ""),
        norm_hex(row.get("extranonce2")),
        norm_hex(row.get("ntime")),
        norm_hex(row.get("nonce")),
    )


def read_evidence_from_stdin() -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], Counter[str]]:
    counters: Counter[str] = Counter()
    rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        counters["evidence tail lines"] += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            counters["invalid evidence json lines"] += 1
            continue
        key = evidence_key(payload)
        if all(key):
            rows[key] = payload
        else:
            counters["evidence rows missing match fields"] += 1
    return rows, counters


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "jobId",
        "extranonce2",
        "ntime",
        "nonce",
        "minerHashPrefix",
        "localHashPrefix",
        "localHashReversedPrefix",
        "miner==local",
        "miner==localReversed",
        "minerMeetsShareTargetCanonical",
        "minerMeetsShareTargetReversed",
        "localMeetsShareTarget",
        "poolStatus",
    ]
    print("\t".join(headers))
    for row in rows:
        print(
            "\t".join(
                [
                    str(row["jobId"]),
                    row["extranonce2"],
                    row["ntime"],
                    row["nonce"],
                    prefix(row["minerReportedHash"]),
                    prefix(row["localComputedHash"]),
                    prefix(row["localComputedHashReversed"]),
                    yes_no(row["minerEqualsLocal"]),
                    yes_no(row["minerEqualsLocalReversed"]),
                    yes_no(row["minerMeetsShareTargetCanonical"]),
                    yes_no(row["minerMeetsShareTargetReversed"]),
                    yes_no(row["localMeetsShareTarget"]),
                    row["poolStatus"],
                ]
            )
        )


def summarize_no_matches(
    paired_rows: list[dict[str, Any]],
    evidence_rows: dict[tuple[str, str, str, str], dict[str, Any]],
    evidence_counters: Counter[str],
) -> None:
    miner_jobs = Counter(row["jobId"] for row in paired_rows)
    evidence_jobs = Counter(key[0] for key in evidence_rows)
    overlapping_jobs = sorted(set(miner_jobs) & set(evidence_jobs))

    print("match_diagnostics:")
    if not evidence_rows:
        print("  - no keyed submit-evidence rows were available in the bounded tail")
    if evidence_counters.get("evidence rows missing match fields"):
        print("  - some submit-evidence rows are missing jobId/extranonce2/ntime/nonce")
    if paired_rows and evidence_rows and not overlapping_jobs:
        print("  - job ids from miner log are absent in submit-evidence tail")
    if overlapping_jobs:
        print("  - job ids overlap, but exact extranonce2/ntime/nonce tuples did not")
    print("  - evidence tail may be too small; retry with a bounded larger tail such as 1000")
    print("  - miner log may be from a different pool restart/session or the log path may be wrong")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: miner_hash_correlation.py <miner-log> <tail-lines>", file=sys.stderr)
        return 2

    miner_path = Path(sys.argv[1])
    tail_lines = sys.argv[2]
    if not miner_path.is_file():
        print(f"miner_hash_correlation: error: miner log not found: {miner_path}", file=sys.stderr)
        return 1

    paired_rows, miner_counters = parse_miner_log(miner_path)
    evidence_rows, evidence_counters = read_evidence_from_stdin()

    matched: list[dict[str, Any]] = []
    counters: Counter[str] = Counter(miner_counters)
    counters["matched submit-evidence rows"] = 0

    for miner_row in paired_rows:
        evidence = evidence_rows.get(evidence_key(miner_row))
        if not evidence:
            continue
        local_hash = norm_hex(evidence.get("localComputedHash"))
        local_reversed = norm_hex(evidence.get("localComputedHashReversed"))
        if not local_reversed and local_hash:
            local_reversed = reverse_hex_bytes(local_hash)
        target = norm_hex(evidence.get("shareTargetUsed") or evidence.get("shareTarget"))
        miner_hash = miner_row["minerReportedHash"]
        miner_hash_reversed = reverse_hex_bytes(miner_hash)
        local_meets = evidence.get("meetsShareTarget")
        if not isinstance(local_meets, bool):
            local_meets = hash_meets_target(local_hash, target)
        pool_status = miner_row.get("poolStatus") or "unknown"
        if pool_status == "unknown":
            if evidence.get("rejectReason"):
                pool_status = str(evidence["rejectReason"])
            elif evidence.get("shareHashValidationStatus") == "share":
                pool_status = "accepted"

        out = {
            **miner_row,
            "localComputedHash": local_hash,
            "localComputedHashReversed": local_reversed,
            "independentAuthoritativeShareHash": norm_hex(evidence.get("independentAuthoritativeShareHash")),
            "shareTarget": target,
            "localMeetsShareTarget": local_meets,
            "shareHashValidationStatus": evidence.get("shareHashValidationStatus"),
            "rejectReason": evidence.get("rejectReason"),
            "notifyVsSubmitJobCacheDigestMatch": evidence.get("notifyVsSubmitJobCacheDigestMatch"),
            "header80Prefix": prefix(evidence.get("header80Hex"), 24),
            "header80Suffix": norm_hex(evidence.get("header80Hex"))[-24:] if evidence.get("header80Hex") else "",
            "minerEqualsLocal": miner_hash == local_hash if local_hash else None,
            "minerEqualsLocalReversed": miner_hash == local_reversed if local_reversed else None,
            "minerMeetsShareTargetCanonical": hash_meets_target(miner_hash, target),
            "minerMeetsShareTargetReversed": hash_meets_target(miner_hash_reversed, target),
            "poolStatus": pool_status,
        }
        matched.append(out)

    counters["matched submit-evidence rows"] = len(matched)
    for row in matched:
        if row["minerEqualsLocal"]:
            counters["miner==local"] += 1
        if row["minerEqualsLocalReversed"]:
            counters["miner==localReversed"] += 1
        if row["minerMeetsShareTargetCanonical"]:
            counters["minerHash meets share target canonical"] += 1
        if row["minerMeetsShareTargetReversed"]:
            counters["minerHash meets share target reversed"] += 1
        if row["localMeetsShareTarget"]:
            counters["localHash meets share target"] += 1
        if row["poolStatus"] == "accepted" and (row["minerEqualsLocal"] or row["minerEqualsLocalReversed"]):
            counters["accepted rows where miner/local match"] += 1
        if row["poolStatus"] != "accepted" and not (row["minerEqualsLocal"] or row["minerEqualsLocalReversed"]):
            counters["rejected rows where miner/local mismatch"] += 1
        if row["minerMeetsShareTargetCanonical"] and row["poolStatus"] != "accepted":
            counters["rows where miner hash meets target but pool rejected"] += 1

    print("miner_hash_correlation: ready")
    print(f"minerLog: {miner_path}")
    print(f"submitEvidenceSource: stdin tail -n {tail_lines}")
    print(f"evidenceTailLinesRead: {evidence_counters.get('evidence tail lines', 0)}")
    print()
    print_table(matched)
    print()
    print("summary:")
    for name in [
        "parsed miner solutions",
        "parsed miner submits",
        "paired solution+submit rows",
        "matched submit-evidence rows",
        "miner==local",
        "miner==localReversed",
        "minerHash meets share target canonical",
        "minerHash meets share target reversed",
        "localHash meets share target",
        "accepted rows where miner/local match",
        "rejected rows where miner/local mismatch",
        "rows where miner hash meets target but pool rejected",
    ]:
        print(f"{name}: {counters.get(name, 0)}")

    if matched:
        print()
        print("matched_details:")
        for row in matched:
            print(
                "  "
                f"{row['jobId']} {row['extranonce2']} {row['ntime']} {row['nonce']} "
                f"status={row['poolStatus']} validation={row.get('shareHashValidationStatus') or '-'} "
                f"reject={row.get('rejectReason') or '-'} target={prefix(row.get('shareTarget'))} "
                f"authHash={prefix(row.get('independentAuthoritativeShareHash'))} "
                f"notifyDigestMatch={row.get('notifyVsSubmitJobCacheDigestMatch')} "
                f"header80={row.get('header80Prefix') or '-'}...{row.get('header80Suffix') or '-'}"
            )
    else:
        print()
        summarize_no_matches(paired_rows, evidence_rows, evidence_counters)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

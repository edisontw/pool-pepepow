#!/usr/bin/env python3
"""Bounded share-event candidate probability audit.

Reads JSONL records from stdin. The live-stratum wrapper feeds this script with
`tail -n`, so this helper must stay streaming and read-only.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any

getcontext().prec = 80


def nested(payload: dict[str, Any], diagnostic: dict[str, Any], key: str, *fallback_keys: str) -> Any:
    if diagnostic.get(key) is not None:
        return diagnostic.get(key)
    if payload.get(key) is not None:
        return payload.get(key)
    for fallback_key in fallback_keys:
        if payload.get(fallback_key) is not None:
            return payload.get(fallback_key)
    return None


def parse_hex_int(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def decimal_ratio(numerator: int, denominator: int | None) -> Decimal | None:
    if denominator in (None, 0):
        return None
    return Decimal(numerator) / Decimal(denominator)


def is_accepted_or_pool_valid(payload: dict[str, Any]) -> bool:
    return (
        payload.get("accepted") is True
        or payload.get("countsAsAcceptedShare") is True
        or payload.get("status") == "accepted"
        or payload.get("shareHashValidationStatus") == "share-hash-valid"
    )


def print_counter(name: str, counter: Counter[Any]) -> None:
    print(f"{name}:")
    if not counter:
        print("  none: 0")
        return
    for key, value in sorted(counter.items(), key=lambda item: str(item[0])):
        print(f"  {key}: {value}")


def main() -> int:
    requested_lines = int(sys.argv[1])
    share_log = sys.argv[2]

    sampled_rows = 0
    json_errors = 0
    accepted_rows: list[dict[str, Any]] = []
    first_ts = None
    last_ts = None

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        sampled_rows += 1
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            json_errors += 1
            continue

        ts = payload.get("timestamp")
        if ts is not None:
            first_ts = first_ts or ts
            last_ts = ts

        if is_accepted_or_pool_valid(payload):
            accepted_rows.append(payload)

    target_status_counts: Counter[Any] = Counter()
    job_status_counts: Counter[Any] = Counter()
    candidate_prep_counts: Counter[Any] = Counter()
    missing_hash = 0
    missing_block_target = 0
    missing_share_target = 0
    invalid_hash = 0
    invalid_block_target = 0
    invalid_share_target = 0
    meets_block_target = 0
    candidate_possible = 0
    candidate_rows = 0
    hash_le_block_but_not_marked = 0
    meets_block_without_candidate_prep = 0
    ratios: list[Decimal] = []
    min_record: dict[str, Any] | None = None

    for payload in accepted_rows:
        diagnostic = payload.get("shareHashDiagnostic")
        if not isinstance(diagnostic, dict):
            diagnostic = {}

        target_status_counts[payload.get("targetValidationStatus", "missing")] += 1
        job_status_counts[payload.get("jobStatus", "missing")] += 1

        prep_status = nested(payload, diagnostic, "candidatePrepStatus") or "missing"
        candidate_prep_counts[prep_status] += 1

        row_meets_block = nested(payload, diagnostic, "meetsBlockTarget") is True
        row_candidate_possible = nested(payload, diagnostic, "candidatePossible") is True
        meets_block_target += int(row_meets_block)
        candidate_possible += int(row_candidate_possible)
        has_candidate_prep_signal = (
            row_candidate_possible
            or payload.get("candidateBlockHash") is not None
            or prep_status not in ("missing", "candidate-not-triggered")
        )
        has_candidate_signal = row_meets_block or has_candidate_prep_signal
        if has_candidate_signal:
            candidate_rows += 1
        if row_meets_block and not has_candidate_prep_signal:
            meets_block_without_candidate_prep += 1

        hash_hex = nested(
            payload,
            diagnostic,
            "localComputedHash",
            "shareHash",
            "shareHashUsed",
            "candidateBlockHash",
        )
        block_target_hex = nested(payload, diagnostic, "blockTargetUsed")
        if block_target_hex is None:
            target_context = payload.get("targetContext")
            if isinstance(target_context, dict):
                block_target_hex = target_context.get("target")
        share_target_hex = nested(payload, diagnostic, "shareTargetUsed", "shareTarget")

        hash_int = parse_hex_int(hash_hex)
        block_target_int = parse_hex_int(block_target_hex)
        share_target_int = parse_hex_int(share_target_hex)

        if hash_hex is None:
            missing_hash += 1
        elif hash_int is None:
            invalid_hash += 1
        if block_target_hex is None:
            missing_block_target += 1
        elif block_target_int is None:
            invalid_block_target += 1
        if share_target_hex is None:
            missing_share_target += 1
        elif share_target_int is None:
            invalid_share_target += 1

        if share_target_int is not None and block_target_int not in (None, 0):
            ratio = decimal_ratio(share_target_int, block_target_int)
            if ratio is not None:
                ratios.append(ratio)

        if hash_int is not None and block_target_int not in (None, 0):
            hash_block_ratio = decimal_ratio(hash_int, block_target_int)
            if hash_int <= block_target_int and not row_meets_block:
                hash_le_block_but_not_marked += 1
            if min_record is None or hash_int < min_record["hash_int"]:
                min_record = {
                    "hash_int": hash_int,
                    "timestamp": payload.get("timestamp"),
                    "job_id": payload.get("jobId"),
                    "job_status": payload.get("jobStatus"),
                    "hash_hex": hash_hex,
                    "block_target_hex": block_target_hex,
                    "share_target_hex": share_target_hex,
                    "hash_block_ratio": hash_block_ratio,
                    "meets_block_target": row_meets_block,
                    "candidate_possible": row_candidate_possible,
                    "candidate_prep_status": prep_status,
                }

    median_ratio = None
    expected_candidates = None
    poisson_zero = None
    if ratios:
        median_ratio = statistics.median(ratios)
        if median_ratio:
            expected_candidates = Decimal(len(accepted_rows)) / median_ratio
            try:
                poisson_zero = math.exp(-float(expected_candidates))
            except (OverflowError, InvalidOperation):
                poisson_zero = None

    accepted_count = len(accepted_rows)
    ratio_coverage = (len(ratios) / accepted_count) if accepted_count else 0.0

    if accepted_count < 20:
        interpretation = "insufficient-sample"
    elif hash_le_block_but_not_marked:
        interpretation = "threshold-semantic-suspicious"
    elif meets_block_without_candidate_prep:
        interpretation = "threshold-semantic-suspicious"
    elif accepted_count and ratio_coverage < 0.5:
        interpretation = "missing-target-context"
    elif (
        min_record is not None
        and min_record["hash_block_ratio"] is not None
        and min_record["hash_block_ratio"] > Decimal(1)
        and expected_candidates is not None
        and expected_candidates < Decimal("0.01")
    ):
        interpretation = "statistical-wait-likely"
    else:
        interpretation = "insufficient-sample"

    print("candidate_probability_audit: ready")
    print(f"share_log: {share_log}")
    print(f"requested_tail_lines: {requested_lines}")
    print(f"sampled_row_count: {sampled_rows}")
    print(f"json_parse_errors: {json_errors}")
    print(f"accepted_share_count: {accepted_count}")
    print(f"timestamp_first: {first_ts}")
    print(f"timestamp_last: {last_ts}")
    print(f"candidate_rows_count: {candidate_rows}")
    print(f"meetsBlockTarget_true: {meets_block_target}")
    print(f"candidatePossible_true: {candidate_possible}")
    print_counter("candidatePrepStatus_counts", candidate_prep_counts)
    print_counter("targetValidationStatus_counts", target_status_counts)
    print_counter("jobStatus_counts", job_status_counts)
    print(f"missing_hash_fields: {missing_hash}")
    print(f"missing_blockTargetUsed_fields: {missing_block_target}")
    print(f"missing_shareTargetUsed_fields: {missing_share_target}")
    print(f"invalid_hash_fields: {invalid_hash}")
    print(f"invalid_blockTargetUsed_fields: {invalid_block_target}")
    print(f"invalid_shareTargetUsed_fields: {invalid_share_target}")
    print(f"ratio_rows: {len(ratios)}")
    if min_record is None:
        print("smallest_hash: none")
    else:
        print("smallest_hash:")
        print(f"  timestamp: {min_record['timestamp']}")
        print(f"  job_id: {min_record['job_id']}")
        print(f"  job_status: {min_record['job_status']}")
        print(f"  hash: {min_record['hash_hex']}")
        print(f"  blockTargetUsed: {min_record['block_target_hex']}")
        print(f"  shareTargetUsed: {min_record['share_target_hex']}")
        print(f"  hash_over_blockTarget: {min_record['hash_block_ratio']}")
        print(f"  meetsBlockTarget: {min_record['meets_block_target']}")
        print(f"  candidatePossible: {min_record['candidate_possible']}")
        print(f"  candidatePrepStatus: {min_record['candidate_prep_status']}")
    if ratios:
        print(f"shareTarget_over_blockTarget_min: {min(ratios)}")
        print(f"shareTarget_over_blockTarget_median: {median_ratio}")
        print(f"shareTarget_over_blockTarget_max: {max(ratios)}")
    else:
        print("shareTarget_over_blockTarget_min: none")
        print("shareTarget_over_blockTarget_median: none")
        print("shareTarget_over_blockTarget_max: none")
    print(f"expected_candidate_count: {expected_candidates if expected_candidates is not None else 'none'}")
    print(f"poisson_p_zero_candidates: {poisson_zero if poisson_zero is not None else 'none'}")
    print(f"hash_le_block_but_meetsBlockTarget_not_true: {hash_le_block_but_not_marked}")
    print(f"meetsBlockTarget_without_candidate_prep: {meets_block_without_candidate_prep}")
    print(f"interpretation: {interpretation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

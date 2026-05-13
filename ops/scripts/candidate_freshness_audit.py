#!/usr/bin/env python3
"""Bounded candidate freshness audit for live Stratum candidate evidence.

This helper is intentionally read-only. The shell wrapper feeds it bounded
`tail -n` snapshots so it never scans the full runtime logs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


FUTURE_FIELDS = [
    "candidatePrevHash",
    "daemonBestHashAtCandidate",
    "daemonBestHashAtSubmitDecision",
    "templateAgeSeconds",
    "candidateAgeSecondsAtSubmitDecision",
]

CHAIN_MATCH_NOT_FOUND_STATUSES = {
    "chain-match-not-found",
    "no-match-found",
}

STALE_PREVBLK_STATUSES = {
    "submit-skipped-stale-prevblk",
}

BUDGET_EXHAUSTED_STATUSES = {
    "submit-skipped-send-budget-exhausted",
    "submit-skipped-budget-exhausted",
}

TERMINAL_PREFIXES = (
    "submit-sent",
    "submit-skipped-",
    "submit-error",
    "submit-disabled-",
)

DECISION_EXPECTED_STATUSES = {
    "submit-sent",
    "submit-skipped-stale-prevblk",
    "submit-skipped-send-budget-exhausted",
    "submit-skipped-budget-exhausted",
}

DECISION_HASH_KEYS = (
    "candidateBlockHash",
    "submitblockPayloadHash",
    "localComputedHash",
)

DECISION_TIMESTAMP_KEYS = (
    "candidateTimestamp",
    "timestamp",
)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    except Exception:
        return []
    return rows


def first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def is_terminal_submit_status(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(TERMINAL_PREFIXES)


def is_submit_error(payload: dict[str, Any], status: Any) -> bool:
    if isinstance(status, str) and ("error" in status or "exception" in status):
        return True
    return payload.get("submitblockDaemonError") is not None or payload.get("submitblockException") is not None


def print_kv(key: str, value: Any) -> None:
    print(f"{key}: {value}")


def render_bool_or_null(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "null"


def is_decision_attribution_expected(status: Any, payload: dict[str, Any]) -> bool:
    if status in DECISION_EXPECTED_STATUSES:
        return True
    return is_submit_error(payload, status)


def candidate_hash_from_row(payload: dict[str, Any]) -> Any:
    return first_present(payload, *DECISION_HASH_KEYS)


def candidate_timestamp_from_row(payload: dict[str, Any]) -> Any:
    return first_present(payload, *DECISION_TIMESTAMP_KEYS)


def row_matches_latest_candidate(
    row: dict[str, Any],
    latest_candidate_job_id: Any,
    latest_candidate_hash_values: set[str],
) -> bool:
    row_job_id = first_present(row, "jobId")
    if latest_candidate_job_id is not None and row_job_id == latest_candidate_job_id:
        return True
    row_hash = candidate_hash_from_row(row)
    return isinstance(row_hash, str) and row_hash in latest_candidate_hash_values


def has_decision_attribution(
    row: dict[str, Any],
    latest_candidate_hash_values: set[str],
) -> bool:
    status = first_present(row, "submitblockRealSubmitStatus")
    if not is_decision_attribution_expected(status, row):
        return False
    row_hash = candidate_hash_from_row(row)
    if not isinstance(row_hash, str):
        return False
    if latest_candidate_hash_values and row_hash not in latest_candidate_hash_values:
        return False
    if row.get("candidatePrevHash") is None:
        return False
    if row.get("daemonBestHashAtSubmitDecision") is None:
        return False
    return candidate_timestamp_from_row(row) is not None


def latest_submit_decision_row(
    related_rows: list[dict[str, Any]],
    latest_candidate_hash_values: set[str],
) -> dict[str, Any] | None:
    for row in related_rows:
        if has_decision_attribution(row, latest_candidate_hash_values):
            return row
    return None


def has_submit_classification_fields(row: dict[str, Any]) -> bool:
    return (
        row.get("candidateFreshnessStatus") is not None
        or row.get("candidatePrevHashMatchesDaemonBestAtSubmitDecision") is not None
    )


def main() -> int:
    if len(sys.argv) != 7:
        print("usage: candidate_freshness_audit.py <tail_lines> <candidate_tail> <submit_tail> <snapshot_json> <followup_tail_or_dash> <outcome_tail_or_dash>", file=sys.stderr)
        return 1

    tail_lines = int(sys.argv[1])
    candidate_rows = load_jsonl(Path(sys.argv[2]))
    submit_rows = load_jsonl(Path(sys.argv[3]))
    snapshot = load_json(Path(sys.argv[4]))
    followup_path = sys.argv[5]
    outcome_path = sys.argv[6]
    followup_rows = [] if followup_path == "-" else load_jsonl(Path(followup_path))
    outcome_rows = [] if outcome_path == "-" else load_jsonl(Path(outcome_path))

    latest_candidate = candidate_rows[-1] if candidate_rows else None
    latest_submit_status = None
    if latest_candidate is not None:
        latest_submit_status = first_present(latest_candidate, "submitblockRealSubmitStatus")

    submit_sent_count = 0
    submit_error_count = 0
    submit_skipped_stale_prevblk_count = 0
    submit_skipped_budget_exhausted_count = 0
    chain_match_not_found_count = 0
    terminal_submit_events = 0

    for row in candidate_rows:
        status = first_present(row, "submitblockRealSubmitStatus")
        if is_terminal_submit_status(status):
            terminal_submit_events += 1
        if row.get("submitblockSent") is True or status == "submit-sent":
            submit_sent_count += 1
        if status in STALE_PREVBLK_STATUSES:
            submit_skipped_stale_prevblk_count += 1
        if status in BUDGET_EXHAUSTED_STATUSES:
            submit_skipped_budget_exhausted_count += 1
        if is_submit_error(row, status):
            submit_error_count += 1
        followup_status = first_present(row, "followupStatus", "candidateOutcomeStatus")
        followup_note = first_present(row, "followupNote")
        if followup_status in CHAIN_MATCH_NOT_FOUND_STATUSES or followup_note == "candidate-block-hash-not-found-on-local-chain":
            chain_match_not_found_count += 1

    if chain_match_not_found_count == 0:
        for source_rows in (followup_rows, outcome_rows):
            for row in source_rows:
                followup_status = first_present(
                    row,
                    "followupStatus",
                    "candidateOutcomeStatus",
                )
                followup_note = first_present(row, "followupNote")
                if followup_status in CHAIN_MATCH_NOT_FOUND_STATUSES or followup_note == "candidate-block-hash-not-found-on-local-chain":
                    chain_match_not_found_count += 1

    meta = snapshot.get("meta", {}) if isinstance(snapshot, dict) else {}
    daemon_best_hash_current = first_present(
        meta,
        "daemonBestHashCurrent",
        "bestBlockHash",
        "bestHash",
    )
    if daemon_best_hash_current is None:
        for row in reversed(candidate_rows):
            daemon_best_hash_current = first_present(row, "submitblockDaemonBestBlockHash")
            if daemon_best_hash_current is not None:
                break
    if daemon_best_hash_current is None:
        for row in reversed(submit_rows):
            daemon_best_hash_current = first_present(row, "submitblockDaemonBestBlockHash")
            if daemon_best_hash_current is not None:
                break

    latest_candidate_hash = None
    latest_candidate_prevhash = None
    latest_candidate_template_age_seconds = None
    if latest_candidate is not None:
        latest_candidate_hash = candidate_hash_from_row(latest_candidate)
        latest_candidate_prevhash = first_present(
            latest_candidate,
            "candidatePrevHash",
            "submitblockCandidatePrevhash",
            "submitblockPayloadPrevhash",
            "submitblockHeaderPrevhash",
            "submitblockJobPrevhash",
        )
        latest_candidate_template_age_seconds = first_present(
            latest_candidate,
            "templateAgeSeconds",
        )

    latest_candidate_has_attribution = (
        latest_candidate is not None
        and latest_candidate_prevhash is not None
        and latest_candidate_template_age_seconds is not None
    )

    related_rows: list[dict[str, Any]] = []
    latest_candidate_job_id = first_present(latest_candidate or {}, "jobId")
    latest_candidate_hash_values: set[str] = set()
    if isinstance(latest_candidate_hash, str):
        latest_candidate_hash_values.add(latest_candidate_hash)
    if latest_candidate is not None:
        related_rows.append(latest_candidate)
    for source_rows in (submit_rows, outcome_rows, followup_rows, candidate_rows[:-1]):
        for row in reversed(source_rows):
            if row_matches_latest_candidate(
                row,
                latest_candidate_job_id,
                latest_candidate_hash_values,
            ):
                related_rows.append(row)
        if latest_candidate_hash is None:
            for row in related_rows:
                row_hash = candidate_hash_from_row(row)
                if isinstance(row_hash, str):
                    latest_candidate_hash = row_hash
                    latest_candidate_hash_values.add(row_hash)
                    break

    submit_decision_fields_expected = (
        latest_candidate is not None
        and is_decision_attribution_expected(latest_submit_status, latest_candidate)
    )
    latest_submit_decision = latest_submit_decision_row(
        related_rows,
        latest_candidate_hash_values,
    )
    latest_submit_has_decision_attribution = latest_submit_decision is not None
    latest_submit_candidate_freshness_status = "unknown"
    latest_submit_prevhash_matches_daemon_best = None
    latest_submit_classification_source = "none"
    if latest_submit_decision is not None:
        if has_submit_classification_fields(latest_submit_decision):
            latest_submit_candidate_freshness_status = first_present(
                latest_submit_decision,
                "candidateFreshnessStatus",
            ) or "unknown"
            latest_submit_prevhash_matches_daemon_best = first_present(
                latest_submit_decision,
                "candidatePrevHashMatchesDaemonBestAtSubmitDecision",
            )
            if latest_submit_decision in submit_rows:
                latest_submit_classification_source = "submit-evidence"
            else:
                latest_submit_classification_source = "unknown"

    if latest_candidate is None:
        attribution_note = "no-latest-candidate"
    elif not latest_candidate_has_attribution:
        attribution_note = "candidate-attribution-missing"
    elif not submit_decision_fields_expected:
        attribution_note = "candidate-attribution-present-submit-disabled"
    elif latest_submit_has_decision_attribution:
        attribution_note = "decision-attribution-present"
    else:
        attribution_note = "decision-attribution-missing"

    has_prevhash_evidence = latest_candidate_prevhash is not None or any(
        first_present(
            row,
            "submitblockCandidatePrevhash",
            "submitblockPayloadPrevhash",
            "submitblockHeaderPrevhash",
            "submitblockJobPrevhash",
        )
        is not None
        for row in candidate_rows
    )
    has_best_hash_evidence = daemon_best_hash_current is not None

    if not candidate_rows:
        freshness_conclusion = "no-candidates-in-window"
    elif submit_skipped_stale_prevblk_count > 0:
        freshness_conclusion = "stale-prevblk-observed"
    elif chain_match_not_found_count > 0:
        freshness_conclusion = "chain-match-not-found-observed"
    elif terminal_submit_events == 0:
        freshness_conclusion = "no-terminal-submit-events"
    elif not has_prevhash_evidence or not has_best_hash_evidence:
        freshness_conclusion = "insufficient-fields"
    else:
        freshness_conclusion = "insufficient-fields"

    print("candidate_freshness_audit: ready")
    print_kv("requested_tail_lines", tail_lines)
    print_kv("candidate_events_inspected", len(candidate_rows))
    print_kv("submit_evidence_rows_inspected", len(submit_rows))
    print_kv(
        "latest_candidate_timestamp",
        candidate_timestamp_from_row(latest_candidate or {}),
    )
    print_kv("latest_candidate_job_id", latest_candidate_job_id)
    print_kv("latest_candidate_hash", latest_candidate_hash)
    print_kv("latest_candidate_prevhash", latest_candidate_prevhash)
    print_kv("latest_candidate_has_attribution", str(latest_candidate_has_attribution).lower())
    print_kv("latest_candidate_template_age_seconds", latest_candidate_template_age_seconds)
    print_kv("latest_submit_status", latest_submit_status)
    print_kv("submit_decision_fields_expected", str(submit_decision_fields_expected).lower())
    print_kv("latest_submit_has_decision_attribution", str(latest_submit_has_decision_attribution).lower())
    print_kv(
        "latest_submit_candidate_freshness_status",
        latest_submit_candidate_freshness_status,
    )
    print_kv(
        "latest_submit_prevhash_matches_daemon_best",
        render_bool_or_null(latest_submit_prevhash_matches_daemon_best),
    )
    print_kv(
        "latest_submit_classification_source",
        latest_submit_classification_source,
    )
    print_kv("attribution_note", attribution_note)
    print_kv("submit_sent_count_in_window", submit_sent_count)
    print_kv("submit_error_count_in_window", submit_error_count)
    print_kv("submit_skipped_stale_prevblk_count_in_window", submit_skipped_stale_prevblk_count)
    print_kv("submit_skipped_budget_exhausted_count_in_window", submit_skipped_budget_exhausted_count)
    print_kv("chain_match_not_found_count_in_window", chain_match_not_found_count)
    print_kv("daemon_best_hash_current", daemon_best_hash_current)
    print_kv("freshness_conclusion", freshness_conclusion)
    if freshness_conclusion == "insufficient-fields":
        print_kv("smallest_future_instrumentation_fields", ",".join(FUTURE_FIELDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

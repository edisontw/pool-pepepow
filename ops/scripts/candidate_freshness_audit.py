#!/usr/bin/env python3
"""Bounded candidate freshness audit for live Stratum candidate evidence.

This helper is intentionally read-only. The shell wrapper feeds it bounded
`tail -n` snapshots so it never scans the full runtime logs.
"""

from __future__ import annotations

import argparse
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


def is_submit_disabled_status(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("submit-disabled-")


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


def normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except Exception:
            return None
    return None


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


def parse_iso(ts_str: Any) -> datetime | None:
    if not isinstance(ts_str, str) or not ts_str:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tail_lines", type=int)
    parser.add_argument("candidate_tail")
    parser.add_argument("submit_tail")
    parser.add_argument("snapshot_json")
    parser.add_argument("followup_tail")
    parser.add_argument("outcome_tail")
    parser.add_argument("--rpc-url")
    parser.add_argument("--rpc-user")
    parser.add_argument("--rpc-password")
    parser.add_argument("--rpc-timeout", type=float, default=5.0)

    args, _ = parser.parse_known_args()

    tail_lines = args.tail_lines
    candidate_rows = load_jsonl(Path(args.candidate_tail))
    submit_rows = load_jsonl(Path(args.submit_tail))
    snapshot = load_json(Path(args.snapshot_json))
    followup_path = args.followup_tail
    outcome_path = args.outcome_tail
    followup_rows = [] if followup_path == "-" else load_jsonl(Path(followup_path))
    outcome_rows = [] if outcome_path == "-" else load_jsonl(Path(outcome_path))

    latest_candidate = candidate_rows[-1] if candidate_rows else None
    latest_submit_status = None
    if latest_candidate is not None:
        latest_submit_status = first_present(latest_candidate, "submitblockRealSubmitStatus")

    submit_sent_count = 0
    submit_sent_latest_ts = None
    submit_error_count = 0
    submit_error_latest_ts = None
    submit_skipped_stale_prevblk_count = 0
    submit_skipped_stale_prevblk_latest_ts = None
    submit_skipped_budget_exhausted_count = 0
    submit_skipped_budget_exhausted_latest_ts = None
    chain_match_not_found_count = 0
    terminal_submit_events = 0

    for row in candidate_rows:
        status = first_present(row, "submitblockRealSubmitStatus")
        row_ts = candidate_timestamp_from_row(row)
        if is_terminal_submit_status(status):
            terminal_submit_events += 1
        if row.get("submitblockSent") is True or status == "submit-sent":
            submit_sent_count += 1
            if row_ts:
                submit_sent_latest_ts = row_ts
        if status in STALE_PREVBLK_STATUSES:
            submit_skipped_stale_prevblk_count += 1
            if row_ts:
                submit_skipped_stale_prevblk_latest_ts = row_ts
        if status in BUDGET_EXHAUSTED_STATUSES:
            submit_skipped_budget_exhausted_count += 1
            if row_ts:
                submit_skipped_budget_exhausted_latest_ts = row_ts
        if is_submit_error(row, status):
            submit_error_count += 1
            if row_ts:
                submit_error_latest_ts = row_ts
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
    real_submit_enabled = normalize_bool(meta.get("realSubmitblockEnabled"))
    real_submit_send_budget_remaining = parse_int(meta.get("realSubmitblockSendBudgetRemaining"))
    template_mode_effective = meta.get("templateModeEffective")
    template_fetch_status = meta.get("templateFetchStatus")
    template_daemon_rpc_reachable = normalize_bool(meta.get("templateDaemonRpcReachable"))
    daemon_best_hash_current = None
    daemon_best_hash_source = "cached"

    if args.rpc_url:
        try:
            pool_core_dir = Path(__file__).resolve().parents[2] / "apps" / "pool-core"
            if str(pool_core_dir) not in sys.path:
                sys.path.insert(0, str(pool_core_dir))
            from daemon_rpc import DaemonRpcClient

            rpc_client = DaemonRpcClient(
                rpc_url=args.rpc_url,
                rpc_user=args.rpc_user or "",
                rpc_password=args.rpc_password or "",
                timeout_seconds=args.rpc_timeout or 5.0,
            )
            rpc_best_hash = rpc_client.get_best_block_hash()
            if rpc_best_hash:
                daemon_best_hash_current = rpc_best_hash
                daemon_best_hash_source = "rpc"
        except Exception:
            pass

    if daemon_best_hash_current is None:
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

    daemon_template_ready = (
        template_mode_effective == "daemon-template"
        and template_fetch_status == "ok"
        and template_daemon_rpc_reachable is True
    )
    if real_submit_enabled is False or is_submit_disabled_status(latest_submit_status):
        latest_submit_readiness_status = "disabled"
    elif latest_submit_candidate_freshness_status == "stale-prevblk":
        latest_submit_readiness_status = "stale-prevblk"
    elif (
        daemon_template_ready
        and real_submit_enabled is True
        and real_submit_send_budget_remaining is not None
        and real_submit_send_budget_remaining > 0
    ):
        latest_submit_readiness_status = "ready"
    else:
        latest_submit_readiness_status = "unknown"

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

    if freshness_conclusion == "stale-prevblk-observed":
        last_share_at_str = meta.get("lastShareAt")
        latest_cand_ts_str = candidate_timestamp_from_row(latest_candidate or {})
        cand_dt = parse_iso(latest_cand_ts_str)
        share_dt = parse_iso(last_share_at_str)
        if cand_dt and share_dt and (share_dt - cand_dt).total_seconds() > 1800:
            freshness_conclusion = "historical stale-prevblk; no fresh candidate yet"

    latest_candidate_recorded_freshness = "unknown"
    latest_candidate_recorded_freshness_status = "unknown"
    if latest_candidate is not None:
        recorded_f = latest_candidate.get("candidate_freshness")
        recorded_status = latest_candidate.get("candidateFreshnessStatus")
        if recorded_f == "fresh" or recorded_status == "current-prevblk":
            latest_candidate_recorded_freshness = "fresh"
        elif recorded_f is not None:
            latest_candidate_recorded_freshness = recorded_f
        
        if recorded_status is not None:
            latest_candidate_recorded_freshness_status = recorded_status

    if latest_candidate_recorded_freshness == "unknown" and latest_candidate_prevhash is not None and daemon_best_hash_current is not None:
        if latest_candidate_prevhash == daemon_best_hash_current:
            latest_candidate_recorded_freshness = "fresh"
        else:
            latest_candidate_recorded_freshness = "stale"
    if latest_candidate_recorded_freshness_status == "unknown" and latest_candidate_prevhash is not None and daemon_best_hash_current is not None:
        if latest_candidate_prevhash == daemon_best_hash_current:
            latest_candidate_recorded_freshness_status = "current-prevblk"
        else:
            latest_candidate_recorded_freshness_status = "stale-prevblk"

    latest_candidate_current_daemon_comparison = "unknown"
    latest_candidate_prevhash_matches_current_daemon_best = None
    latest_candidate_current_daemon_comparison_note = "none"

    if latest_candidate_prevhash is not None and daemon_best_hash_current is not None:
        matches = (latest_candidate_prevhash == daemon_best_hash_current)
        latest_candidate_prevhash_matches_current_daemon_best = matches
        if matches:
            latest_candidate_current_daemon_comparison = "matches-current-daemon-best"
        else:
            latest_candidate_current_daemon_comparison = "historical-candidate-now-stale"
            latest_candidate_current_daemon_comparison_note = "daemon-best-moved-since-candidate"

    latest_candidate_freshness = "unknown"
    if latest_candidate_recorded_freshness == "fresh":
        latest_candidate_freshness = "fresh-prevblk"
    elif latest_candidate_recorded_freshness == "stale":
        latest_candidate_freshness = "stale-prevblk"
    elif latest_candidate_recorded_freshness != "unknown":
        latest_candidate_freshness = latest_candidate_recorded_freshness

    latest_candidate_block_target_used = None
    latest_candidate_hash_int_lte_block_target_int = "unknown"
    latest_candidate_bits = None
    latest_candidate_target_height = None
    latest_candidate_prevhash_matches_latest_template = "unknown"

    if latest_candidate is not None:
        latest_candidate_block_target_used = latest_candidate.get("blockTargetUsed")
        meets_block_target = latest_candidate.get("meetsBlockTarget")
        hash_int = latest_candidate.get("localComputedHashInt") or latest_candidate.get("candidateHashInt")
        target_int = latest_candidate.get("blockTargetInt")
        if meets_block_target is not None:
            latest_candidate_hash_int_lte_block_target_int = str(meets_block_target).lower()
        elif hash_int is not None and target_int is not None:
            latest_candidate_hash_int_lte_block_target_int = str(hash_int <= target_int).lower()
        else:
            c_block_hash = latest_candidate.get("candidate_block_hash") or latest_candidate.get("candidateBlockHash") or latest_candidate_hash
            b_target_used = latest_candidate.get("blockTargetUsed")
            if isinstance(c_block_hash, str) and isinstance(b_target_used, str):
                try:
                    c_val = int(c_block_hash.strip(), 16)
                    t_val = int(b_target_used.strip(), 16)
                    latest_candidate_hash_int_lte_block_target_int = str(c_val <= t_val).lower()
                except Exception:
                    pass

        latest_candidate_bits = latest_candidate.get("bits") or latest_candidate.get("nbits")
        target_context = latest_candidate.get("targetContext")
        if isinstance(target_context, dict):
            latest_candidate_target_height = target_context.get("height")
        if latest_candidate_target_height is None:
            latest_candidate_target_height = latest_candidate.get("targetContext.height") or latest_candidate.get("targetHeight")
        prev_match = latest_candidate.get("prevhashMatchesLatestTemplate")
        if prev_match is True:
            latest_candidate_prevhash_matches_latest_template = "true"
        elif prev_match is False:
            latest_candidate_prevhash_matches_latest_template = "false"
        else:
            latest_candidate_prevhash_matches_latest_template = "unknown"

    # Overrides/adjustments for freshness_conclusion
    if latest_candidate_recorded_freshness == "fresh" and latest_submit_status == "submit-disabled-flag-off":
        freshness_conclusion = "fresh-candidate-recorded-submit-disabled"

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
    print_kv("latest_candidate_freshness", latest_candidate_freshness)
    print_kv("latest_candidate_recorded_freshness", latest_candidate_recorded_freshness)
    print_kv("latest_candidate_recorded_freshness_status", latest_candidate_recorded_freshness_status)
    print_kv("latest_candidate_current_daemon_comparison", latest_candidate_current_daemon_comparison)
    print_kv("latest_candidate_prevhash_matches_current_daemon_best", render_bool_or_null(latest_candidate_prevhash_matches_current_daemon_best))
    print_kv("latest_candidate_current_daemon_comparison_note", latest_candidate_current_daemon_comparison_note)
    print_kv("latest_candidate_block_target_used", latest_candidate_block_target_used)
    print_kv("latest_candidate_hash_int_lte_block_target_int", latest_candidate_hash_int_lte_block_target_int)
    print_kv("latest_candidate_bits", latest_candidate_bits)
    print_kv("latest_candidate_target_height", latest_candidate_target_height)
    print_kv("latest_candidate_prevhash_matches_latest_template", latest_candidate_prevhash_matches_latest_template)
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
    print_kv("latest_submit_readiness_status", latest_submit_readiness_status)
    print_kv("attribution_note", attribution_note)
    print_kv("persistent_tail_submit_sent_count", submit_sent_count)
    print_kv("persistent_tail_submit_sent_latest_timestamp", submit_sent_latest_ts)
    print_kv("persistent_tail_submit_error_count", submit_error_count)
    print_kv("persistent_tail_submit_error_latest_timestamp", submit_error_latest_ts)
    print_kv("persistent_tail_submit_skipped_stale_prevblk_count", submit_skipped_stale_prevblk_count)
    print_kv("persistent_tail_submit_skipped_stale_prevblk_latest_timestamp", submit_skipped_stale_prevblk_latest_ts)
    print_kv("persistent_tail_submit_skipped_budget_exhausted_count", submit_skipped_budget_exhausted_count)
    print_kv("persistent_tail_submit_skipped_budget_exhausted_latest_timestamp", submit_skipped_budget_exhausted_latest_ts)
    print_kv("persistent_tail_counts_may_include_previous_processes", "true")
    print_kv("chain_match_not_found_count_in_window", chain_match_not_found_count)
    print_kv("daemon_best_hash_current", daemon_best_hash_current)
    print_kv("daemon_best_hash_source", daemon_best_hash_source)
    print_kv("freshness_conclusion", freshness_conclusion)
    if freshness_conclusion == "insufficient-fields":
        print_kv("smallest_future_instrumentation_fields", ",".join(FUTURE_FIELDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

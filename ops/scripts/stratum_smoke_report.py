#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize synthetic Stratum smoke evidence into the standard report format."
    )
    parser.add_argument("--share-log", type=Path, required=True)
    parser.add_argument("--activity-snapshot", type=Path)
    parser.add_argument("--pool-log", type=Path)
    parser.add_argument("--miner-log", type=Path)
    parser.add_argument("--miner-name", required=True)
    parser.add_argument("--miner-version", default="unknown")
    parser.add_argument("--source-provenance", default="not provided")
    parser.add_argument("--build-method", default="not provided")
    parser.add_argument("--environment-platform", default="not provided")
    parser.add_argument("--pool-command", default="not provided")
    parser.add_argument("--miner-command", default="not provided")
    parser.add_argument(
        "--set-difficulty",
        choices=("yes", "no", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--notify",
        choices=("yes", "no", "unknown"),
        default="unknown",
    )
    parser.add_argument("--compat-issue", action="append", default=[])
    parser.add_argument("--minimal-fix", action="append", default=[])
    parser.add_argument("--risk", action="append", default=[])
    parser.add_argument("--verification-note", action="append", default=[])
    parser.add_argument("--documentation-updated", action="append", default=[])
    parser.add_argument("--suggested-next-step", default="")
    return parser.parse_args()


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def load_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def infer_set_difficulty(rows: list[dict[str, Any]], configured: str) -> tuple[str, str]:
    if configured != "unknown":
        return configured, "explicit input"
    if rows and all(row.get("difficulty") is not None for row in rows):
        return "yes", "inferred from accepted submit records carrying difficulty"
    return "unknown", "no direct evidence"


def infer_notify(rows: list[dict[str, Any]], configured: str) -> tuple[str, str]:
    if configured != "unknown":
        return configured, "explicit input"
    if rows and all(row.get("jobId") for row in rows):
        return "yes", "inferred from accepted submit records carrying jobId"
    return "unknown", "no direct evidence"


def infer_issues(pool_log_text: str, miner_log_text: str) -> dict[str, str]:
    combined = f"{pool_log_text}\n{miner_log_text}".lower()
    keywords = {
        "disconnect": ("disconnect", "disconnected"),
        "parse error": ("parse error",),
        "protocol mismatch": ("method not found", "unsupported", "protocol mismatch"),
        "hang": ("hang", "stalled"),
    }
    results: dict[str, str] = {}
    for label, terms in keywords.items():
        found = any(term in combined for term in terms)
        results[label] = yes_no_unknown(found if combined else None)
    return results


def main() -> int:
    args = parse_args()
    rows = load_json_lines(args.share_log)
    activity_snapshot = load_json(args.activity_snapshot)
    pool_log_text = load_text(args.pool_log)
    miner_log_text = load_text(args.miner_log)

    share_count = len(rows)
    job_ids = [row.get("jobId") for row in rows if row.get("jobId")]
    unique_job_ids = list(dict.fromkeys(job_ids))
    workers = Counter(row.get("worker", "unknown") for row in rows)
    difficulties = sorted({row.get("difficulty") for row in rows if row.get("difficulty") is not None})
    synthetic_flags_ok = all(row.get("syntheticWork") is True for row in rows) if rows else False
    blockchain_flags_ok = all(row.get("blockchainVerified") is False for row in rows) if rows else False
    validation_modes = sorted({row.get("shareValidationMode") for row in rows if row.get("shareValidationMode")})
    issues = infer_issues(pool_log_text, miner_log_text)
    set_difficulty, set_difficulty_basis = infer_set_difficulty(rows, args.set_difficulty)
    notify, notify_basis = infer_notify(rows, args.notify)
    crossed_periodic_notify = share_count > 0 and len(unique_job_ids) >= 3
    snapshot_exists = activity_snapshot is not None

    summary_line = (
        f"{args.miner_name} {args.miner_version}: "
        f"{share_count} accepted synthetic submit(s), "
        f"{len(unique_job_ids)} distinct jobId(s), "
        f"periodic notify carry-over={yes_no_unknown(crossed_periodic_notify)}."
    )

    compatibility_issues = list(args.compat_issue)
    if not compatibility_issues:
        if share_count == 0:
            compatibility_issues.append(
                "No accepted submit evidence was found in the share log; protocol outcome remains incomplete."
            )
        elif any(value == "yes" for value in issues.values()):
            compatibility_issues.append(
                "Log keywords suggest at least one runtime issue; inspect pool/miner logs before widening scope."
            )
        else:
            compatibility_issues.append("None observed in the available evidence.")

    minimal_fixes = args.minimal_fix or ["None."]
    risks = list(args.risk)
    if not risks:
        risks.append("Synthetic acceptance still does not imply valid shares, real validation, or real block production.")
        if share_count > 0 and len(unique_job_ids) < 3:
            risks.append("Accepted submits were observed, but evidence does not yet prove carry-over across two later periodic notify cycles.")
        if not snapshot_exists:
            risks.append("Activity snapshot evidence was not provided.")

    verification_results = list(args.verification_note)
    verification_results.extend(
        [
            f"Accepted submit count: {share_count}",
            f"Distinct jobId count: {len(unique_job_ids)}",
            f"Workers seen: {', '.join(sorted(workers)) if workers else 'none'}",
            f"Synthetic flags all true: {yes_no_unknown(synthetic_flags_ok)}",
            f"Blockchain flags all false: {yes_no_unknown(blockchain_flags_ok)}",
            f"Share validation modes: {', '.join(validation_modes) if validation_modes else 'none'}",
            f"Activity snapshot present: {yes_no_unknown(snapshot_exists)}",
        ]
    )
    if difficulties:
        verification_results.append(
            f"Observed share difficulty values: {', '.join(str(value) for value in difficulties)}"
        )

    documentation = args.documentation_updated or ["None."]
    next_step = args.suggested_next_step or (
        "If this was a CPU or harness preflight, run the same isolated pool against the external HTN GPU miner and regenerate this report with the GPU evidence."
    )

    print("1. Summary")
    print(summary_line)
    print()
    print("2. Miner Tested")
    print(f"- {args.miner_name}")
    print(f"- version: {args.miner_version}")
    print()
    print("3. Source / Provenance")
    print(f"- {args.source_provenance}")
    print(f"- build or acquisition: {args.build_method}")
    print()
    print("4. Environment / Platform")
    print(f"- {args.environment_platform}")
    print()
    print("5. Exact Commands Used")
    print("```bash")
    print(args.pool_command)
    print("```")
    print("```bash")
    print(args.miner_command)
    print("```")
    print()
    print("6. Observed Protocol Behavior")
    print(f"- received set_difficulty: {set_difficulty} ({set_difficulty_basis})")
    print(f"- received notify: {notify} ({notify_basis})")
    print(f"- successful submit observed: {yes_no_unknown(share_count > 0)}")
    print(f"- crossed later periodic notify with continued submit: {yes_no_unknown(crossed_periodic_notify)}")
    print(f"- distinct jobId count in share log: {len(unique_job_ids)}")
    print(f"- disconnect seen: {issues['disconnect']}")
    print(f"- parse error seen: {issues['parse error']}")
    print(f"- protocol mismatch seen: {issues['protocol mismatch']}")
    print(f"- hang seen: {issues['hang']}")
    print()
    print("7. Compatibility Issues Found")
    for item in compatibility_issues:
        print(f"- {item}")
    print()
    print("8. Minimal Fixes Applied")
    for item in minimal_fixes:
        print(f"- {item}")
    print()
    print("9. Risks / Remaining Gaps")
    for item in risks:
        print(f"- {item}")
    print()
    print("10. Verification Results")
    for item in verification_results:
        print(f"- {item}")
    print()
    print("11. Documentation Updated")
    for item in documentation:
        print(f"- {item}")
    print()
    print("12. Suggested Next Step")
    print(f"- {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

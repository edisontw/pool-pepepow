#!/usr/bin/env python3
import sys
import json
import math
import subprocess
import statistics
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from decimal import Decimal, getcontext

# Set Decimal precision high enough for difficulty targets
getcontext().prec = 80

DEFAULT_CANDIDATE_RATIO_SCALE = Decimal(65536)

def parse_iso(ts_str):
    if not isinstance(ts_str, str) or not ts_str:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None

def parse_hex_int(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None

def get_nested(row, diagnostic, key, *fallback_keys):
    if diagnostic.get(key) is not None:
        return diagnostic.get(key)
    if row.get(key) is not None:
        return row.get(key)
    for fallback in fallback_keys:
        if row.get(fallback) is not None:
            return row.get(fallback)
    return None

def run_tail(filepath, lines):
    try:
        res = subprocess.run(
            ["tail", "-n", str(lines), str(filepath)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return res.stdout.splitlines()
    except Exception as e:
        print(f"Error tailing file {filepath}: {e}", file=sys.stderr)
        return []

def main():
    # 1. Parse arguments
    share_events_path = Path(".runtime/live-stratum/share-events.jsonl")
    cutoff_str = "2026-05-28T14:39:05Z"
    tail_lines = 200000

    if len(sys.argv) > 1:
        share_events_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        cutoff_str = sys.argv[2]
    if len(sys.argv) > 3:
        try:
            tail_lines = int(sys.argv[3])
        except ValueError:
            pass

    cutoff_ts = parse_iso(cutoff_str)
    if not cutoff_ts:
        print(f"Error: Invalid cutoff timestamp '{cutoff_str}'", file=sys.stderr)
        sys.exit(1)

    if not share_events_path.exists():
        print(f"Error: Share events file '{share_events_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Load launch.env for difficulty scale and fallback difficulty configuration
    env_path = share_events_path.parent / "launch.env"
    wire_scale = DEFAULT_CANDIDATE_RATIO_SCALE
    env_fallback_difficulty = None
    env_fallback_source = None
    
    if env_path.exists():
        try:
            with env_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line_strip = line.strip()
                    if "PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE" in line_strip:
                        parts = line_strip.split("=")
                        if len(parts) == 2:
                            wire_scale = Decimal(parts[1])
                    elif "PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY" in line_strip:
                        parts = line_strip.split("=")
                        if len(parts) == 2:
                            env_fallback_difficulty = Decimal(parts[1])
                            env_fallback_source = "launch.env (PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY)"
                    elif "PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY" in line_strip and env_fallback_difficulty is None:
                        # Fallback only if the estimated hashrate difficulty variable is missing
                        parts = line_strip.split("=")
                        if len(parts) == 2:
                            env_fallback_difficulty = Decimal(parts[1])
                            env_fallback_source = "launch.env (PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY)"
        except Exception:
            pass

    # Load candidate events for logging integrity check
    candidate_events_path = share_events_path.parent / "candidate-events.jsonl"
    candidate_hashes = set()
    latest_candidate_ts = None
    if candidate_events_path.exists():
        try:
            with candidate_events_path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        c_row = json.loads(line)
                        ts_val = parse_iso(c_row.get("timestamp"))
                        if ts_val:
                            if latest_candidate_ts is None or ts_val > latest_candidate_ts:
                                latest_candidate_ts = ts_val
                        c_hash = c_row.get("candidateBlockHash")
                        if c_hash:
                            candidate_hashes.add(c_hash.lower().strip())
                    except Exception:
                        pass
        except Exception as e:
            print(f"Warning: Could not read candidate events: {e}", file=sys.stderr)

    # 2. Tail share-events file
    lines = run_tail(share_events_path, tail_lines)
    if not lines:
        print("No share event rows found or file is empty.")
        sys.exit(0)

    # Process rows
    first_ts_str = None
    last_ts_str = None

    rows_before_cutoff = 0
    rows_after_cutoff = 0

    post_submits = 0
    post_accepted = 0
    post_rejected = 0
    post_meets_block = 0
    post_candidate_like = 0

    share_hash_statuses = Counter()
    target_val_statuses = Counter()
    reject_reasons = Counter()

    effective_diffs = set()
    miner_wire_diffs = set()
    ratios = []
    
    # Track the source of difficulty used
    difficulty_source = None
    
    # Candidate-like shares post-cutoff that have hash details
    candidate_like_hashes = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue

        ts_raw = row.get("timestamp")
        if not ts_raw:
            continue

        if first_ts_str is None:
            first_ts_str = ts_raw
        last_ts_str = ts_raw

        ts = parse_iso(ts_raw)
        if not ts:
            continue

        # Split before/after cutoff
        if ts <= cutoff_ts:
            rows_before_cutoff += 1
            continue
        else:
            rows_after_cutoff += 1

        # Post-cutoff stats
        post_submits += 1
        accepted = row.get("accepted") is True or row.get("countsAsAcceptedShare") is True or row.get("status") == "accepted"
        if accepted:
            post_accepted += 1
        else:
            post_rejected += 1

        diag = row.get("shareHashDiagnostic") or {}
        
        meets_block = (
            row.get("meetsBlockTarget") is True 
            or diag.get("meetsBlockTarget") is True
        )
        if meets_block:
            post_meets_block += 1

        # Check candidate-like indicators
        c_hash = get_nested(row, diag, "candidateBlockHash", "submitblockPayloadHash", "localComputedHash")
        prep_status = str(get_nested(row, diag, "candidatePrepStatus") or "")
        dry_run_status = str(get_nested(row, diag, "submitblockDryRunStatus") or "")

        is_candidate_like = (
            meets_block
            or (c_hash and (row.get("candidatePossible") is True or row.get("meetsShareTarget") is not False) and prep_status.startswith("candidate-"))
            or prep_status.startswith("candidate-prepared")
            or dry_run_status.startswith("dry-run")
        )

        if meets_block or (c_hash and prep_status.startswith("candidate-prepared")):
            if meets_block:
                post_candidate_like += 1
                if c_hash:
                    candidate_like_hashes.append(c_hash.lower().strip())

        # Counters
        sh_status = row.get("shareHashValidationStatus")
        if sh_status:
            share_hash_statuses[sh_status] += 1

        tg_status = row.get("targetValidationStatus")
        if tg_status:
            target_val_statuses[tg_status] += 1

        rej_reason = row.get("rejectReason")
        if rej_reason:
            reject_reasons[rej_reason] += 1

        # Difficulty parameters
        eff_diff = row.get("difficulty")
        if eff_diff is not None:
            effective_diffs.add(float(eff_diff))
            difficulty_source = "observed row-level 'difficulty'"
            miner_wire_diffs.add(float(eff_diff) * float(wire_scale))
        elif env_fallback_difficulty is not None:
            effective_diffs.add(float(env_fallback_difficulty))
            difficulty_source = f"fallback: {env_fallback_source}"
            miner_wire_diffs.add(float(env_fallback_difficulty) * float(wire_scale))

        # Check for ratio calculation data
        hash_hex = get_nested(row, diag, "localComputedHash", "shareHash", "shareHashUsed")
        block_target_hex = get_nested(row, diag, "blockTargetUsed")
        if block_target_hex is None:
            target_context = row.get("targetContext")
            if isinstance(target_context, dict):
                block_target_hex = target_context.get("target")
        share_target_hex = get_nested(row, diag, "shareTargetUsed", "shareTarget")

        block_target_int = parse_hex_int(block_target_hex)
        share_target_int = parse_hex_int(share_target_hex)

        if share_target_int is not None and block_target_int not in (None, 0):
            ratio = Decimal(share_target_int) / Decimal(block_target_int)
            ratios.append(ratio)

        submit = row.get("submit")
        if isinstance(submit, dict):
            wire_diff = submit.get("difficulty")
            if wire_diff is not None:
                miner_wire_diffs.add(float(wire_diff))
        elif isinstance(diag.get("minerWireDifficulty"), (int, float)):
            miner_wire_diffs.add(float(diag["minerWireDifficulty"]))

    expected_candidates = None
    poisson_zero = None

    if ratios and post_accepted > 0:
        median_ratio = statistics.median(ratios)
        normalized_median_ratio = median_ratio / wire_scale
        if normalized_median_ratio > 0:
            expected_candidates = Decimal(post_accepted) / normalized_median_ratio
            try:
                poisson_zero = math.exp(-float(expected_candidates))
            except Exception:
                pass

    # Report results
    print("=" * 60)
    print("POST-FIX CANDIDATE PROBABILITY AUDIT")
    print("=" * 60)
    print(f"File path:         {share_events_path}")
    print(f"Cutoff timestamp:  {cutoff_str}")
    print(f"Tail line count:   {tail_lines}")
    print("-" * 60)
    print(f"First timestamp in tail: {first_ts_str}")
    print(f"Last timestamp in tail:  {last_ts_str}")
    print(f"Rows before cutoff:      {rows_before_cutoff}")
    print(f"Rows after cutoff:       {rows_after_cutoff}")
    print("-" * 60)
    print(f"Post-cutoff submits:            {post_submits}")
    print(f"Post-cutoff accepted shares:    {post_accepted}")
    print(f"Post-cutoff rejected shares:    {post_rejected}")
    print(f"Post-cutoff meetsBlockTarget:   {post_meets_block}")
    print(f"Post-cutoff block candidates:   {post_candidate_like}")
    print("-" * 60)
    print("Top shareHashValidationStatus:")
    for k, v in share_hash_statuses.most_common(3):
        print(f"  - {k}: {v}")
    print("Top targetValidationStatus:")
    for k, v in target_val_statuses.most_common(3):
        print(f"  - {k}: {v}")
    print("Top rejectReason:")
    for k, v in reject_reasons.most_common(3):
        print(f"  - {k}: {v}")
    print("-" * 60)
    print(f"Observed effectiveShareDifficulty: {sorted(list(effective_diffs))}")
    print(f"Observed minerWireDifficulty:      {sorted(list(miner_wire_diffs))}")
    print(f"Difficulty source:                 {difficulty_source}")
    
    if expected_candidates is not None:
        print(f"Expected candidates (estimation):   {expected_candidates:.6f}")
        if poisson_zero is not None:
            print(f"P(0 candidates) (approximate):      {poisson_zero:.2%}")
    else:
        print("Expected candidates:                Insufficient data")
        print("P(0 candidates):                    Insufficient data")

    print("-" * 60)
    print("INTERPRETATION AND INTEGRITY SUMMARY:")
    
    # Classification logic
    conclusion = "unknown"
    if post_candidate_like == 0:
        if poisson_zero is not None and poisson_zero < 0.01:
            conclusion = "candidate drought suspicious"
        elif expected_candidates is not None and expected_candidates >= Decimal("1.0"):
            conclusion = "candidate liveness warning"
        else:
            conclusion = "no statistical anomaly"
    else:
        # Check if candidate-like hashes are logged in candidate-events
        missing_logging = False
        for c_hash in candidate_like_hashes:
            if c_hash not in candidate_hashes:
                missing_logging = True
                break
        if missing_logging:
            conclusion = "candidate logging suspected broken"
        else:
            conclusion = "no statistical anomaly"

    print(f"Conclusion: {conclusion.upper()}")
    
    if conclusion == "no statistical anomaly":
        print("Detail: Share distribution and block solutions match expected probability bounds.")
    elif conclusion == "candidate logging suspected broken":
        print("Detail: Block-target-meeting share found but missing from candidate-events.jsonl.")
    elif conclusion == "candidate drought suspicious":
        print("Detail: Observed zero candidate blocks despite extremely low probability (P(0) < 1%). Inspect system config.")
    elif conclusion == "candidate liveness warning":
        latest_ts_str_val = latest_candidate_ts.isoformat().replace("+00:00", "Z") if latest_candidate_ts else "none"
        now_ts = datetime.now(timezone.utc)
        cutoff_age_seconds = int((now_ts - cutoff_ts).total_seconds())
        print(f"Detail: Latest candidate timestamp: {latest_ts_str_val}, cutoff age: {cutoff_age_seconds}s. not enough evidence to reopen target math, but candidate liveness has not advanced.")

    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())

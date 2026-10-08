#!/usr/bin/env python3
"""Write a small, bounded resource-health snapshot for pool operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0]) * 1024
    return values


def process_memory() -> tuple[int, int]:
    try:
        pid = int(subprocess.check_output(["pgrep", "-x", "PEPEPOWd"], text=True).splitlines()[0])
        values = {}
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(("VmRSS:", "VmSwap:")):
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
        return values.get("VmRSS", 0), values.get("VmSwap", 0)
    except Exception:
        return 0, 0


def read_cgroup_number(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
        return None if value == "max" else int(value)
    except (OSError, ValueError):
        return None


def daemon_cgroup_memory() -> dict[str, int | None]:
    empty = {
        "current": None,
        "peak": None,
        "high": None,
        "max": None,
        "events_high": None,
        "events_oom": None,
        "events_oom_kill": None,
    }
    try:
        control_group = subprocess.check_output(
            ["systemctl", "show", "pepepowd.service", "-p", "ControlGroup", "--value"],
            text=True,
        ).strip()
        if not control_group.startswith("/"):
            return empty
        cgroup = Path("/sys/fs/cgroup") / control_group.lstrip("/")
        values = {
            "current": read_cgroup_number(cgroup / "memory.current"),
            "peak": read_cgroup_number(cgroup / "memory.peak"),
            "high": read_cgroup_number(cgroup / "memory.high"),
            "max": read_cgroup_number(cgroup / "memory.max"),
        }
        events = {}
        for line in (cgroup / "memory.events").read_text(encoding="utf-8").splitlines():
            key, value = line.split(maxsplit=1)
            events[key] = int(value)
        values.update(
            events_high=events.get("high", 0),
            events_oom=events.get("oom", 0),
            events_oom_kill=events.get("oom_kill", 0),
        )
        return values
    except (OSError, subprocess.SubprocessError, ValueError):
        return empty


def active_maintenance() -> list[str]:
    units = ("pepepow-pool-auto-payout.service", "pepepow-pool-rounds-refresh.service", "pepepow-pool-solo-lifecycle-refresh.service")
    return [unit for unit in units if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0]


def filesystem_warning(used_percent: float, warning_percent: float = 80.0, critical_percent: float = 90.0) -> str | None:
    if used_percent >= critical_percent:
        return "root-filesystem-usage-critical"
    if used_percent >= warning_percent:
        return "root-filesystem-usage-high"
    return None


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def snapshot_items(path: Path, key: str) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get(key, [])
    except (OSError, ValueError, TypeError):
        return []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def timestamp_epoch(item: dict) -> float:
    try:
        return datetime.fromisoformat(str(item.get("submit_timestamp") or "").replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def attribution_digest(record: dict) -> str:
    payload = {key: record.get(key) for key in (
        "candidate_hash", "total_share_count", "total_share_score", "wallet_count", "worker_count", "shares")}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_has_coverage_proof(record: dict) -> bool:
    proof = record.get("share_window_coverage")
    return bool(
        isinstance(proof, dict)
        and proof.get("status") == "complete"
        and proof.get("candidate_hash") == record.get("candidate_hash")
        and proof.get("previous_pool_boundary") == record.get("previous_pool_boundary")
        and proof.get("segments_contiguous") is True
        and proof.get("sequence_contiguous") is True
        and proof.get("tail_truncated") is False
        and proof.get("malformed_rows") == 0
        and isinstance(proof.get("source_first_sequence"), int)
        and isinstance(proof.get("source_last_sequence"), int)
        and proof.get("source_last_sequence") >= proof.get("source_first_sequence")
        and isinstance(proof.get("attribution_sha256"), str)
        and proof.get("attribution_sha256") == attribution_digest(record)
        and (proof.get("source_coverage_sha256") is None or (
            isinstance(proof.get("source_coverage_sha256"), str)
            and len(proof["source_coverage_sha256"]) == 64
            and all(char in "0123456789abcdef" for char in proof["source_coverage_sha256"])
        ))
    )


def round_attribution_health(
    rounds_path: Path,
    candidates_path: Path,
    payments_path: Path,
    ledger_path: Path,
    *,
    now_epoch: float | None = None,
    recent_seconds: int = 24 * 3600,
) -> dict:
    rounds = snapshot_items(rounds_path, "rounds")
    payout_candidates = snapshot_items(candidates_path, "items")
    payments = snapshot_items(payments_path, "items")
    if not rounds or not payout_candidates:
        return {"available": False}
    now = time.time() if now_epoch is None else now_epoch
    recent_cutoff = now - recent_seconds
    rounds_by_id = {str(item.get("candidate_hash")): item for item in rounds if item.get("candidate_hash")}
    paid_ids: set[str] = set()
    candidate_by_id = {}
    for item in payout_candidates:
        identity = str(item.get("candidateId") or item.get("candidate_hash") or "")
        if identity:
            candidate_by_id[identity] = item
            if item.get("blockedReason") == "blocked_already_paid":
                paid_ids.add(identity)
    for item in payments:
        for key in ("candidateHash", "candidateId", "candidate_id"):
            if item.get(key):
                paid_ids.add(str(item[key]))
        for key in ("sourceCandidateIds", "candidateIds"):
            if isinstance(item.get(key), list):
                paid_ids.update(str(value) for value in item[key] if value)

    ledger_records = []
    if ledger_path.exists():
        try:
            with ledger_path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict) and record.get("miningMode") == "pool":
                        ledger_records.append(record)
        except OSError:
            pass
    ledger_without_durable_proof = [item for item in ledger_records if not record_has_coverage_proof(item)]
    current_source_verified_ids = {
        identity for identity, item in rounds_by_id.items()
        if item.get("attribution_persisted") is True and item.get("attribution_coverage_verified") is True
    }
    ledger_missing_ids = {str(item.get("candidate_hash")) for item in ledger_without_durable_proof
                          if item.get("candidate_hash")}
    source_covered_ledger_ids = ledger_missing_ids & current_source_verified_ids
    historical_unverifiable_ids = ledger_missing_ids - source_covered_ledger_ids
    already_paid_unverified = historical_unverifiable_ids & paid_ids
    confirmed_rounds = [item for item in rounds if item.get("status") == "confirmed"]
    latest_confirmed = max(confirmed_rounds, key=timestamp_epoch, default=None)
    latest_verified = max(
        (item for item in rounds if item.get("attribution_persisted") is True
         and item.get("attribution_coverage_verified") is True),
        key=timestamp_epoch, default=None)

    recent_completed = [item for item in confirmed_rounds if timestamp_epoch(item) >= recent_cutoff]
    recent_persisted = [item for item in recent_completed if item.get("attribution_persisted") is True
                        and item.get("attribution_coverage_verified") is True]
    actionable_reasons = {"blocked_unverified_round_attribution", "missing_share_data", "blocked_missing_round"}
    recent_failures = []
    historical_blocked = 0
    for candidate in payout_candidates:
        identity = str(candidate.get("candidateId") or candidate.get("candidate_hash") or "")
        reason = candidate.get("blockedReason") or candidate.get("reason")
        if (candidate.get("lifecycleStatus") != "confirmed" or reason not in actionable_reasons
                or not identity or identity in paid_ids):
            continue
        round_item = rounds_by_id.get(identity)
        if (round_item and round_item.get("attribution_persisted") is True
                and round_item.get("attribution_coverage_verified") is True):
            continue
        candidate_ts = timestamp_epoch(candidate)
        if candidate_ts and candidate_ts >= recent_cutoff:
            recent_failures.append({"candidateId": identity, "timestamp": candidate.get("submit_timestamp"),
                                    "reason": reason, "ageSeconds": max(0, int(now - candidate_ts))})
        elif candidate_ts:
            historical_blocked += 1
    recent_failures.sort(key=lambda item: item["timestamp"] or "", reverse=True)
    latest_round = max(recent_completed, key=timestamp_epoch, default=None)
    unresolved_epochs = [timestamp_epoch(item) for item in recent_failures if item.get("timestamp")]
    return {
        "available": True,
        "windowSeconds": recent_seconds,
        "newestConfirmedPoolCandidateAt": (latest_confirmed or {}).get("submit_timestamp"),
        "newestVerifiedAttributionAt": (latest_verified or {}).get("submit_timestamp"),
        "ledgerRecordsMissingDurableCoverageProof": len(ledger_without_durable_proof),
        "currentlySourceCoveredLedgerRecordsMissingDurableProof": len(source_covered_ledger_ids),
        "historicalUnverifiableLedgerRecords": len(historical_unverifiable_ids),
        "historicalUnverifiableUnpaidLedgerRecords": len(historical_unverifiable_ids - paid_ids),
        "historicalUnresolvedUnverifiableCandidates": historical_blocked,
        "alreadyPaidButUnverifiedLedgerRecords": len(already_paid_unverified),
        "recentConfirmedMatureUnpaidMissingAttribution": len(recent_failures),
        "recentCompletedRounds": len(recent_completed),
        "recentCompletedRoundsPersisted": len(recent_persisted),
        "latestRecentCompletedRoundPersisted": bool(latest_round and latest_round.get("attribution_persisted") is True
                                                    and latest_round.get("attribution_coverage_verified") is True),
        "latestRecentCompletedRoundAt": (latest_round or {}).get("submit_timestamp"),
        "recentNewlyFailedAttributions": recent_failures[:10],
        "oldestRecentFailureAgeSeconds": max(0, int(now - min(unresolved_epochs))) if unresolved_epochs else 0,
        "newestConfirmedStatus": (latest_confirmed or {}).get("status"),
        "maturityWaitCandidateCount": sum(1 for item in rounds if item.get("status") == "immature"),
        "maturityWaitCandidateCount": sum(1 for item in rounds if item.get("status") == "immature"),
    }


def classify_runtime_storage() -> dict[str, int]:
    roots = (Path("/home/ubuntu/pool-pepepow/.runtime/live-stratum"), Path("/var/lib/pepepow-pool"))
    totals = {"logrotateManagedOperationalBytes": 0, "nonrotatingAuditAccountingBytes": 0,
              "applicationRetainedShareHistoryBytes": 0, "otherRuntimeJsonlBytes": 0}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if not path.is_file():
                    continue
                name = path.name
                size = path.stat().st_size
                if name.startswith("share-events"):
                    totals["applicationRetainedShareHistoryBytes"] += size
                elif ("payment-actions" in name or "round-attribution" in name
                      or (("candidate-events" in name or "candidate-outcome-events" in name)
                          and "solo" not in path.parts)):
                    totals["nonrotatingAuditAccountingBytes"] += size
                elif (name.endswith(".log") or "-evidence.jsonl" in name
                      or "candidate-followup-events.jsonl" in name
                      or ("solo" in path.parts and ("candidate-events.jsonl" in name
                                                      or "candidate-outcome-events.jsonl" in name))):
                    totals["logrotateManagedOperationalBytes"] += size
                elif name.endswith((".jsonl", ".jsonl.gz")):
                    totals["otherRuntimeJsonlBytes"] += size
            except OSError:
                continue
    return totals
    roots = (Path("/home/ubuntu/pool-pepepow/.runtime/live-stratum"), Path("/var/lib/pepepow-pool"))
    total = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("**/*"):
            try:
                if path.is_file() and (path.name.endswith((".log", ".jsonl")) or "evidence" in path.name):
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Write PEPEPOW resource health snapshot")
    parser.add_argument("--output", type=Path, default=Path("/var/lib/pepepow-pool/resource-health.json"))
    parser.add_argument("--memavailable-warning-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--swap-warning-percent", type=float, default=50.0)
    parser.add_argument("--daemon-rss-warning-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--rounds-snapshot", type=Path,
                        default=Path("/home/ubuntu/pool-pepepow/.runtime/live-stratum/rounds-snapshot.json"))
    parser.add_argument("--payout-candidates", type=Path,
                        default=Path("/home/ubuntu/pool-pepepow/.runtime/live-stratum/payout-candidates.json"))
    parser.add_argument("--payments-snapshot", type=Path,
                        default=Path("/home/ubuntu/pool-pepepow/.runtime/live-stratum/payments-snapshot.json"))
    parser.add_argument("--attribution-ledger", type=Path,
                        default=Path("/var/lib/pepepow-pool/round-attribution.jsonl"))
    parser.add_argument("--rotation-state", type=Path,
                        default=Path("/var/lib/logrotate/status"))
    args = parser.parse_args()
    memory = meminfo()
    try:
        previous_health = json.loads(args.output.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous_health = {}
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", 0)
    swap_total = memory.get("SwapTotal", 0)
    swap_used = max(0, swap_total - memory.get("SwapFree", 0))
    daemon_rss, daemon_swap = process_memory()
    daemon_cgroup = daemon_cgroup_memory()
    daemon_current = daemon_cgroup["current"]
    daemon_high = daemon_cgroup["high"]
    daemon_max = daemon_cgroup["max"]
    filesystem = os.statvfs("/")
    root_used_percent = round((1 - filesystem.f_bavail / filesystem.f_blocks) * 100, 2)
    filesystem_status = filesystem_warning(root_used_percent)
    storage_bytes = classify_runtime_storage()
    now_epoch = time.time()
    previous_samples = previous_health.get("storageGrowthSamples", [])
    previous_samples = [sample for sample in previous_samples if isinstance(sample, dict)
                        and isinstance(sample.get("epoch"), (int, float))
                        and isinstance(sample.get("nonrotatingBytes"), int)]
    storage_samples = (previous_samples + [{
        "epoch": now_epoch,
        "nonrotatingBytes": storage_bytes["nonrotatingAuditAccountingBytes"],
    }])[-13:]
    oldest_sample = storage_samples[0] if len(storage_samples) >= 2 else None
    sample_window_seconds = int(now_epoch - oldest_sample["epoch"]) if oldest_sample else 0
    growth_rate = None
    projected_free_hours = None
    if sample_window_seconds >= 1800:
        delta = storage_samples[-1]["nonrotatingBytes"] - oldest_sample["nonrotatingBytes"]
        growth_rate = round(delta / sample_window_seconds, 2)
        if growth_rate > 0:
            projected_free_hours = round(filesystem.f_bavail * filesystem.f_frsize / growth_rate / 3600, 1)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "memAvailableBytes": available,
        "ramUsedPercent": round((1 - available / total) * 100, 2) if total else None,
        "swapUsedBytes": swap_used,
        "swapUsedPercent": round(swap_used / swap_total * 100, 2) if swap_total else 0.0,
        "daemonRssBytes": daemon_rss,
        "daemonSwapBytes": daemon_swap,
        "daemonCgroupMemoryBytes": daemon_cgroup["current"],
        "daemonCgroupMemoryPeakBytes": daemon_cgroup["peak"],
        "daemonMemoryHighBytes": daemon_cgroup["high"],
        "daemonMemoryMaxBytes": daemon_cgroup["max"],
        "daemonMemoryHighUtilizationPercent": (
            round(daemon_current / daemon_high * 100, 2)
            if daemon_current is not None and daemon_high
            else None
        ),
        "daemonMemoryMaxUtilizationPercent": (
            round(daemon_current / daemon_max * 100, 2)
            if daemon_current is not None and daemon_max
            else None
        ),
        "daemonMemoryEventsHigh": daemon_cgroup["events_high"],
        "daemonMemoryEventsOom": daemon_cgroup["events_oom"],
        "daemonMemoryEventsOomKill": daemon_cgroup["events_oom_kill"],
        "loadAverage": list(os.getloadavg()),
        "rootFilesystemUsedPercent": root_used_percent,
        "resourceWarnings": [filesystem_status] if filesystem_status else [],
        "resourceHealthLevel": "critical" if filesystem_status == "root-filesystem-usage-critical" else (
            "warning" if filesystem_status else "ok"
        ),
        "activeMaintenance": active_maintenance(),
        "roundAttribution": round_attribution_health(
            args.rounds_snapshot, args.payout_candidates, args.payments_snapshot, args.attribution_ledger,
            now_epoch=now_epoch,
        ),
        "runtimeStorageBytes": storage_bytes,
        "storageGrowthSamples": storage_samples,
        "storageGrowthTrend": {
            "sampleWindowSeconds": sample_window_seconds,
            "nonrotatingBytesPerSecond": growth_rate,
            "directionalFreeSpaceHoursAtCurrentTrend": projected_free_hours,
            "confidence": "directional trend; not a disk-full deadline" if growth_rate is not None else "insufficient sample window",
        },
    }
    warnings = []
    attribution_health = payload["roundAttribution"]
    if attribution_health.get("recentConfirmedMatureUnpaidMissingAttribution", 0):
        warnings.append("recent-unpaid-pool-attribution-failure")
    if available < args.memavailable_warning_bytes:
        warnings.append("memavailable-low")
    if payload["swapUsedPercent"] > args.swap_warning_percent:
        warnings.append("swap-high")
    if daemon_rss > args.daemon_rss_warning_bytes:
        warnings.append("daemon-rss-high")
    if daemon_current is not None and daemon_high and daemon_current >= daemon_high * 0.9:
        warnings.append("daemon-cgroup-high-approaching")
    critical = False
    if filesystem_status:
        warnings.append(filesystem_status)
        critical = filesystem_status == "root-filesystem-usage-critical"
    rotation_result = subprocess.run(
        ["systemctl", "show", "pepepow-pool-logrotate.service", "-p", "Result", "--value"],
        capture_output=True, text=True,
    ).stdout.strip()
    standard_rotation_result = subprocess.run(
        ["systemctl", "show", "logrotate.service", "-p", "Result", "--value"],
        capture_output=True, text=True,
    ).stdout.strip()
    rotation_timer_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "pepepow-pool-logrotate.timer"], capture_output=True
    ).returncode == 0
    standard_rotation_timer_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "logrotate.timer"], capture_output=True
    ).returncode == 0
    rotation_started = subprocess.run(
        ["systemctl", "show", "pepepow-pool-logrotate.service", "-p", "ExecMainStartTimestamp", "--value"],
        capture_output=True, text=True,
    ).stdout.strip()
    standard_rotation_started = subprocess.run(
        ["systemctl", "show", "logrotate.service", "-p", "ExecMainStartTimestamp", "--value"],
        capture_output=True, text=True,
    ).stdout.strip()
    payload["logRotation"] = {"lastResult": rotation_result or "unknown", "stateFileExists": args.rotation_state.exists(),
                              "timerActive": rotation_timer_active, "lastStartedAt": rotation_started or None,
                              "standardTimerActive": standard_rotation_timer_active,
                              "standardLastResult": standard_rotation_result or "unknown",
                              "standardLastStartedAt": standard_rotation_started or None}
    if (rotation_result not in {"", "success", "unknown"}
            or standard_rotation_result not in {"", "success", "unknown"}
            or not rotation_timer_active or not standard_rotation_timer_active):
        warnings.append("runtime-log-rotation-failed")
    if daemon_current is not None and daemon_max and daemon_current >= daemon_max * 0.9:
        warnings.append("daemon-cgroup-max-critical")
        critical = True
    if warnings:
        level = "critical" if critical else "warning"
        payload["resourceWarnings"] = warnings
        payload["resourceHealthLevel"] = level
        message = f"resource-health-{level} " + " ".join(warnings)
        # stderr is captured by the service journal; keeping the message short
        # makes it useful as a low-noise early warning.
        print(message, file=sys.stderr)
    if growth_rate is not None and (growth_rate >= 1024 * 1024 or
                                    (projected_free_hours is not None and projected_free_hours < 168)):
        warnings.append("nonrotating-accounting-growth-dangerous")
        payload["resourceWarnings"] = warnings
        payload["resourceHealthLevel"] = "critical" if critical or (projected_free_hours is not None and projected_free_hours < 24) else "warning"
        print("resource-health-warning operational-log-growth-dangerous", file=sys.stderr)
    atomic_write(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

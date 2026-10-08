#!/usr/bin/env python3
"""Write a small, bounded resource-health snapshot for pool operations."""

from __future__ import annotations

import argparse
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


def round_attribution_health(snapshot_path: Path) -> dict:
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        rounds = data.get("rounds", [])
    except (OSError, ValueError, TypeError):
        return {"available": False}
    confirmed = [item for item in rounds if isinstance(item, dict) and item.get("status") == "confirmed"]
    awaiting = [item for item in confirmed if item.get("attribution_coverage_verified") is not True]
    verified = [item for item in rounds if isinstance(item, dict) and item.get("attribution_coverage_verified") is True]
    def timestamp(item):
        raw = item.get("submit_timestamp")
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0
    latest = max(confirmed, key=timestamp, default=None)
    newest_verified = max(verified, key=timestamp, default=None)
    oldest = min(awaiting, key=timestamp, default=None)
    reason = (latest or {}).get("attribution_reason")
    missing_data = sum(1 for item in awaiting if item.get("attribution_reason") in {
        "share_window_start_unbounded", "share_window_start_boundary_missing",
        "share_window_end_boundary_missing", "share_window_boundary_sequence_missing",
    })
    incomplete_coverage = sum(1 for item in awaiting if item.get("attribution_reason") in {
        "share_window_sequence_gap", "share_window_malformed_row", "share_log_segment_gap",
        "share_log_sequence_gap_or_missing_sequence", "share_log_malformed_rows",
    })
    if latest and latest.get("attribution_coverage_verified") is True:
        state = "persisted"
    elif latest and reason == "share_window_start_unbounded":
        state = "missing-share-boundary"
    elif latest and reason and ("boundary" in reason or "sequence" in reason or "coverage" in reason):
        state = "incomplete-coverage"
    elif latest:
        state = "awaiting-coverage"
    else:
        state = "no-confirmed-candidate"
    now = time.time()
    return {
        "available": True,
        "newestConfirmedPoolCandidateAt": (latest or {}).get("submit_timestamp"),
        "newestVerifiedAttributionAt": (newest_verified or {}).get("submit_timestamp"),
        "confirmedCandidatesAwaitingCoverage": len(awaiting),
        "confirmedCandidatesMissingShareData": missing_data,
        "confirmedCandidatesWithIncompleteCoverage": incomplete_coverage,
        "oldestUnresolvedAttributionAgeSeconds": max(0, int(now - timestamp(oldest))) if oldest else 0,
        "latestCompletedRoundPersisted": bool(latest and latest.get("attribution_persisted") is True
                                                and latest.get("attribution_coverage_verified") is True),
        "latestCompletedRoundState": state,
        "latestCompletedRoundReason": reason,
        "maturityWaitCandidateCount": sum(1 for item in rounds if isinstance(item, dict) and item.get("status") == "immature"),
    }


def operational_log_bytes() -> int:
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
    parser.add_argument("--rotation-state", type=Path,
                        default=Path("/var/lib/pepepow-pool/logrotate-runtime.status"))
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
    current_log_bytes = operational_log_bytes()
    previous_log = previous_health.get("operationalLogSample", {})
    elapsed = max(1, int(time.time() - float(previous_log.get("sampledAtEpoch", time.time()))))
    growth = max(0, current_log_bytes - int(previous_log.get("bytes", current_log_bytes)))
    growth_rate = growth / elapsed
    projected_free_hours = (filesystem.f_bavail * filesystem.f_frsize / growth_rate / 3600
                            if growth_rate > 0 else None)
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
        "roundAttribution": round_attribution_health(args.rounds_snapshot),
        "operationalLogSample": {"bytes": current_log_bytes, "sampledAtEpoch": time.time(),
                                 "growthBytesPerSecond": round(growth_rate, 2),
                                 "projectedFreeDiskHours": round(projected_free_hours, 1) if projected_free_hours else None},
    }
    warnings = []
    attribution_health = payload["roundAttribution"]
    if attribution_health.get("confirmedCandidatesAwaitingCoverage", 0):
        warnings.append("pool-attribution-awaiting-coverage")
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
    rotation_timer_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "pepepow-pool-logrotate.timer"], capture_output=True
    ).returncode == 0
    rotation_started = subprocess.run(
        ["systemctl", "show", "pepepow-pool-logrotate.service", "-p", "ExecMainStartTimestamp", "--value"],
        capture_output=True, text=True,
    ).stdout.strip()
    payload["logRotation"] = {"lastResult": rotation_result or "unknown", "stateFileExists": args.rotation_state.exists(),
                              "timerActive": rotation_timer_active, "lastStartedAt": rotation_started or None}
    if rotation_result not in {"", "success", "unknown"} or not rotation_timer_active:
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
    if growth_rate >= 1024 * 1024 or (projected_free_hours is not None and projected_free_hours < 168):
        warnings.append("operational-log-growth-dangerous")
        payload["resourceWarnings"] = warnings
        payload["resourceHealthLevel"] = "critical" if critical or (projected_free_hours is not None and projected_free_hours < 24) else "warning"
        print("resource-health-warning operational-log-growth-dangerous", file=sys.stderr)
    atomic_write(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

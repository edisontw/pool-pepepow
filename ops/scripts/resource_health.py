#!/usr/bin/env python3
"""Write a small, bounded resource-health snapshot for pool operations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
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


def active_maintenance() -> list[str]:
    units = ("pepepow-pool-auto-payout.service", "pepepow-pool-rounds-refresh.service", "pepepow-pool-solo-lifecycle-refresh.service")
    return [unit for unit in units if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0]


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Write PEPEPOW resource health snapshot")
    parser.add_argument("--output", type=Path, default=Path("/var/lib/pepepow-pool/resource-health.json"))
    parser.add_argument("--memavailable-warning-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--swap-warning-percent", type=float, default=50.0)
    parser.add_argument("--daemon-rss-warning-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    args = parser.parse_args()
    memory = meminfo()
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", 0)
    swap_total = memory.get("SwapTotal", 0)
    swap_used = max(0, swap_total - memory.get("SwapFree", 0))
    daemon_rss, daemon_swap = process_memory()
    filesystem = os.statvfs("/")
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "memAvailableBytes": available,
        "ramUsedPercent": round((1 - available / total) * 100, 2) if total else None,
        "swapUsedBytes": swap_used,
        "swapUsedPercent": round(swap_used / swap_total * 100, 2) if swap_total else 0.0,
        "daemonRssBytes": daemon_rss,
        "daemonSwapBytes": daemon_swap,
        "loadAverage": list(os.getloadavg()),
        "rootFilesystemUsedPercent": round((1 - filesystem.f_bavail / filesystem.f_blocks) * 100, 2),
        "activeMaintenance": active_maintenance(),
    }
    atomic_write(args.output, payload)
    warnings = []
    if available < args.memavailable_warning_bytes:
        warnings.append("memavailable-low")
    if payload["swapUsedPercent"] > args.swap_warning_percent:
        warnings.append("swap-high")
    if daemon_rss > args.daemon_rss_warning_bytes:
        warnings.append("daemon-rss-high")
    if warnings:
        print("resource-health-warning " + " ".join(warnings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

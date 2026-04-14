from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic Stratum shares")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--rate", type=int, required=True, help="Target shares per second")
    parser.add_argument("--duration", type=int, default=60, help="Run time in seconds")
    parser.add_argument("--connections", type=int, default=20)
    parser.add_argument("--wallet-prefix", default="PEPEPOW1LoadWalletAddress")
    parser.add_argument("--workers-per-wallet", type=int, default=4)
    parser.add_argument("--activity-log-path", type=Path, default=None)
    parser.add_argument("--activity-snapshot-path", type=Path, default=None)
    parser.add_argument("--api-base-url", default=None)
    parser.add_argument("--pid", type=int, default=None, help="PID to sample for CPU/RSS")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


@dataclass
class RunStats:
    sent: int = 0
    responses_ok: int = 0
    responses_error: int = 0
    connect_failures: int = 0
    api_latencies_ms: list[float] = field(default_factory=list)
    api_errors: int = 0
    cpu_percent_samples: list[float] = field(default_factory=list)
    rss_mb_samples: list[float] = field(default_factory=list)
    snapshot_writes_observed: int = 0
    max_snapshot_lag_seconds: float = 0.0
    max_sequence_backlog: int = 0


async def main() -> int:
    args = parse_args()
    stats = RunStats()
    deadline = asyncio.get_running_loop().time() + args.duration
    before_lines = count_lines(args.activity_log_path) if args.activity_log_path else None

    sampler_tasks = [
        asyncio.create_task(
            sample_api(args.api_base_url, deadline, stats),
            name="api-sampler",
        )
        if args.api_base_url
        else None,
        asyncio.create_task(
            sample_process(args.pid, deadline, stats),
            name="process-sampler",
        )
        if args.pid
        else None,
        asyncio.create_task(
            sample_activity_snapshot(args.activity_snapshot_path, deadline, stats, lambda: stats.sent),
            name="snapshot-sampler",
        )
        if args.activity_snapshot_path
        else None,
    ]
    sampler_tasks = [task for task in sampler_tasks if task is not None]

    worker_tasks = [
        asyncio.create_task(
            run_connection(
                index=index,
                host=args.host,
                port=args.port,
                deadline=deadline,
                total_rate=args.rate,
                total_connections=args.connections,
                wallet_prefix=args.wallet_prefix,
                workers_per_wallet=max(1, args.workers_per_wallet),
                stats=stats,
            ),
            name=f"generator-{index}",
        )
        for index in range(max(1, args.connections))
    ]

    await asyncio.gather(*worker_tasks)
    for task in sampler_tasks:
        await task

    after_lines = count_lines(args.activity_log_path) if args.activity_log_path else None
    duration_seconds = float(args.duration)
    summary = {
        "targetRate": args.rate,
        "durationSeconds": args.duration,
        "connections": args.connections,
        "sharesSent": stats.sent,
        "responsesOk": stats.responses_ok,
        "responsesError": stats.responses_error,
        "connectFailures": stats.connect_failures,
        "observedShareRate": stats.sent / duration_seconds if duration_seconds else 0.0,
        "jsonlLinesWritten": (
            after_lines - before_lines
            if before_lines is not None and after_lines is not None
            else None
        ),
        "cpuPercentAvg": average_or_none(stats.cpu_percent_samples),
        "cpuPercentMax": max_or_none(stats.cpu_percent_samples),
        "rssMbAvg": average_or_none(stats.rss_mb_samples),
        "rssMbMax": max_or_none(stats.rss_mb_samples),
        "apiLatencyMsMedian": percentile(stats.api_latencies_ms, 50),
        "apiLatencyMsP95": percentile(stats.api_latencies_ms, 95),
        "apiErrors": stats.api_errors,
        "snapshotWritesObserved": stats.snapshot_writes_observed,
        "maxSnapshotLagSeconds": stats.max_snapshot_lag_seconds,
        "maxSequenceBacklog": stats.max_sequence_backlog,
    }

    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.output is not None:
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


async def run_connection(
    *,
    index: int,
    host: str,
    port: int,
    deadline: float,
    total_rate: int,
    total_connections: int,
    wallet_prefix: str,
    workers_per_wallet: int,
    stats: RunStats,
) -> None:
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError:
        stats.connect_failures += 1
        return

    wallet = f"{wallet_prefix}{index // workers_per_wallet:06d}"
    worker = f"rig{index % workers_per_wallet:02d}"
    login = f"{wallet}.{worker}"

    try:
        await rpc_call(
            reader,
            writer,
            {"id": 1, "method": "mining.subscribe", "params": ["loadgen/1.0"]},
        )
        await rpc_call(
            reader,
            writer,
            {"id": 2, "method": "mining.authorize", "params": [login, "x"]},
        )

        rate_per_connection = max(total_rate / max(1, total_connections), 0.01)
        interval = 1.0 / rate_per_connection
        request_id = 3
        next_at = asyncio.get_running_loop().time()
        share_number = 0

        while asyncio.get_running_loop().time() < deadline:
            response = await rpc_call(
                reader,
                writer,
                {
                    "id": request_id,
                    "method": "mining.submit",
                    "params": [
                        login,
                        f"job-{index}",
                        f"{share_number:08x}",
                        f"{share_number + 1:08x}",
                        f"{share_number + 2:08x}",
                    ],
                },
            )
            stats.sent += 1
            if response.get("result") is True:
                stats.responses_ok += 1
            else:
                stats.responses_error += 1

            request_id += 1
            share_number += 1
            next_at += interval
            delay = next_at - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
    finally:
        writer.close()
        await writer.wait_closed()


async def rpc_call(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    payload: dict[str, Any],
) -> dict[str, Any]:
    writer.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
    await writer.drain()
    request_id = payload.get("id")

    while True:
        raw_response = await reader.readline()
        response = json.loads(raw_response.decode("utf-8"))
        if response.get("id") == request_id:
            return response


async def sample_api(base_url: str | None, deadline: float, stats: RunStats) -> None:
    if not base_url:
        return

    while asyncio.get_running_loop().time() < deadline:
        for endpoint in ("/health", "/pool/summary"):
            started = time.perf_counter()
            try:
                await asyncio.to_thread(fetch_url, f"{base_url}{endpoint}")
            except OSError:
                stats.api_errors += 1
            else:
                stats.api_latencies_ms.append((time.perf_counter() - started) * 1000.0)
        await asyncio.sleep(1.0)


async def sample_process(pid: int | None, deadline: float, stats: RunStats) -> None:
    if pid is None:
        return

    previous = read_process_times(pid)
    if previous is None:
        return

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(1.0)
        current = read_process_times(pid)
        if current is None:
            return
        cpu_percent = ((current[1] - previous[1]) / max(current[0] - previous[0], 0.001)) * 100.0
        stats.cpu_percent_samples.append(cpu_percent)
        stats.rss_mb_samples.append(current[2] / (1024.0 * 1024.0))
        previous = current


async def sample_activity_snapshot(
    snapshot_path: Path | None,
    deadline: float,
    stats: RunStats,
    shares_sent: callable,
) -> None:
    if snapshot_path is None:
        return

    last_generated_at: str | None = None

    while asyncio.get_running_loop().time() < deadline:
        if snapshot_path.exists():
            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                await asyncio.sleep(1.0)
                continue

            generated_at = payload.get("generatedAt")
            meta = payload.get("meta", {})
            if generated_at != last_generated_at and isinstance(generated_at, str):
                stats.snapshot_writes_observed += 1
                last_generated_at = generated_at

            generated_at_dt = parse_iso(generated_at)
            if generated_at_dt is not None:
                lag = max(
                    0.0,
                    (datetime.now(timezone.utc) - generated_at_dt).total_seconds(),
                )
                stats.max_snapshot_lag_seconds = max(stats.max_snapshot_lag_seconds, lag)

            if isinstance(meta, dict):
                sequence = meta.get("sequence")
                if isinstance(sequence, int):
                    stats.max_sequence_backlog = max(
                        stats.max_sequence_backlog, shares_sent() - sequence
                    )

        await asyncio.sleep(1.0)


def count_lines(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            count += chunk.count(b"\n")
    return count


def fetch_url(url: str) -> None:
    with urllib.request.urlopen(url, timeout=5) as response:
        response.read()


def read_process_times(pid: int) -> tuple[float, float, int] | None:
    stat_path = Path(f"/proc/{pid}/stat")
    statm_path = Path(f"/proc/{pid}/statm")
    if not stat_path.exists() or not statm_path.exists():
        return None

    clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    page_size = os.sysconf("SC_PAGE_SIZE")
    stat_fields = stat_path.read_text(encoding="utf-8").split()
    if len(stat_fields) < 24:
        return None

    process_seconds = (int(stat_fields[13]) + int(stat_fields[14])) / clock_ticks
    resident_pages = int(statm_path.read_text(encoding="utf-8").split()[1])
    rss_bytes = resident_pages * page_size
    return time.monotonic(), process_seconds, rss_bytes


def parse_iso(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)


def max_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values)


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

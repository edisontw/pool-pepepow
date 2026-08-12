#!/usr/bin/env python3
"""Bounded runtime log trimmer for live Stratum artifacts."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path


DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_KEEP_LINES = 5000
CHUNK_SIZE = 1024 * 1024

SNAPSHOT_NAMES = {
    "activity-snapshot.json",
    "pool-snapshot.json",
    "accepted-candidates.json",
    "payout-candidates.json",
    "payments-snapshot.json",
    "rounds-snapshot.json",
}


def parse_size(value: str) -> int:
    text = value.strip().lower()
    units = {
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "m": 1024 * 1024,
        "mb": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
        "gb": 1024 * 1024 * 1024,
    }
    for suffix, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if text.endswith(suffix):
            number = text[: -len(suffix)]
            if not number.isdigit():
                raise argparse.ArgumentTypeError(f"invalid size: {value}")
            return int(number) * multiplier
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"invalid size: {value}")
    return int(text)


def is_target(path: Path) -> bool:
    name = path.name
    if name in SNAPSHOT_NAMES:
        return False
    return (
        name.endswith(".log")
        or name.endswith("-evidence.jsonl")
        or name == "candidate-outcome-events.jsonl"
    )


def iter_targets(runtime_dir: Path) -> list[Path]:
    if not runtime_dir.is_dir():
        return []
    return sorted(path for path in runtime_dir.iterdir() if path.is_file() and is_target(path))


def tail_bytes(path: Path, keep_lines: int) -> bytes:
    if keep_lines <= 0:
        return b""

    chunks: list[bytes] = []
    newline_count = 0
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        while position > 0 and newline_count <= keep_lines:
            read_size = min(CHUNK_SIZE, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    data = b"".join(reversed(chunks))
    return b"".join(data.splitlines(keepends=True)[-keep_lines:])


def trim_file(path: Path, keep_lines: int) -> tuple[int, int]:
    before = path.stat().st_size
    retained = tail_bytes(path, keep_lines)
    original_mode = stat.S_IMODE(path.stat().st_mode)

    with path.open("r+b") as handle:
        handle.seek(0)
        handle.write(retained)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(path, original_mode)
    return before, path.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Trim oversized live Stratum runtime logs.")
    parser.add_argument(
        "--runtime-dir",
        default=os.environ.get("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", ".runtime/live-stratum"),
        help="runtime directory to inspect",
    )
    parser.add_argument(
        "--max-bytes",
        type=parse_size,
        default=parse_size(os.environ.get("PEPEPOW_RUNTIME_LOG_MAX_BYTES", "100MB")),
        help="trim files larger than this size; accepts bytes or 100MB style values",
    )
    parser.add_argument(
        "--keep-lines",
        type=int,
        default=int(os.environ.get("PEPEPOW_RUNTIME_LOG_KEEP_LINES", str(DEFAULT_KEEP_LINES))),
        help="number of trailing lines to preserve in oversized files",
    )
    args = parser.parse_args()

    if args.max_bytes <= 0:
        parser.error("--max-bytes must be greater than zero")
    if args.keep_lines < 0:
        parser.error("--keep-lines must be zero or greater")

    runtime_dir = Path(args.runtime_dir)
    checked = 0
    rotated = 0
    bytes_before = 0
    bytes_after = 0

    for path in iter_targets(runtime_dir):
        checked += 1
        size = path.stat().st_size
        bytes_before += size
        if size > args.max_bytes:
            before, after = trim_file(path, args.keep_lines)
            rotated += 1
            bytes_after += after
            print(f"trimmed {path.name}: {before} -> {after}")
        else:
            bytes_after += size

    print(
        "runtime_log_rotation: "
        f"checked={checked} rotated={rotated} "
        f"bytes_before={bytes_before} bytes_after={bytes_after}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

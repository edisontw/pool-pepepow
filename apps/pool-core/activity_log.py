from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ROTATED_SEQUENCE_WIDTH = 20


@dataclass(frozen=True)
class ActivityLogSegment:
    path: Path
    active: bool
    first_sequence: int | None = None
    last_sequence: int | None = None


def rotated_log_path(active_log_path: Path, first_sequence: int, last_sequence: int) -> Path:
    return active_log_path.with_name(
        f"{active_log_path.stem}.{first_sequence:0{ROTATED_SEQUENCE_WIDTH}d}-"
        f"{last_sequence:0{ROTATED_SEQUENCE_WIDTH}d}{active_log_path.suffix}"
    )


def discover_log_segments(active_log_path: Path) -> list[ActivityLogSegment]:
    parent = active_log_path.parent
    if not parent.exists():
        return []

    pattern = re.compile(
        rf"^{re.escape(active_log_path.stem)}\."
        rf"(?P<first>\d{{{ROTATED_SEQUENCE_WIDTH}}})-"
        rf"(?P<last>\d{{{ROTATED_SEQUENCE_WIDTH}}})"
        rf"{re.escape(active_log_path.suffix)}$"
    )

    rotated_segments: list[ActivityLogSegment] = []
    for path in parent.iterdir():
        if not path.is_file():
            continue
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        rotated_segments.append(
            ActivityLogSegment(
                path=path,
                active=False,
                first_sequence=int(match.group("first")),
                last_sequence=int(match.group("last")),
            )
        )

    rotated_segments.sort(
        key=lambda segment: (
            segment.first_sequence or 0,
            segment.last_sequence or 0,
            segment.path.name,
        )
    )

    if active_log_path.exists():
        rotated_segments.append(ActivityLogSegment(path=active_log_path, active=True))

    return rotated_segments


def prune_rotated_logs(active_log_path: Path, retention_files: int) -> list[Path]:
    rotated_segments = [
        segment
        for segment in discover_log_segments(active_log_path)
        if not segment.active
    ]
    excess = len(rotated_segments) - retention_files
    if excess <= 0:
        return []

    removed: list[Path] = []
    for segment in rotated_segments[:excess]:
        segment.path.unlink(missing_ok=True)
        removed.append(segment.path)
    return removed

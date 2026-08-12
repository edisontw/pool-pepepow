from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "solo_lifecycle_refresh.py"
SPEC = importlib.util.spec_from_file_location("solo_lifecycle_refresh", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SoloLifecycleRefreshTests(unittest.TestCase):
    def test_tail_json_objects_is_bounded_to_requested_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate-events.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for i in range(10):
                    handle.write(json.dumps({"i": i}) + "\n")

            rows = MODULE._tail_json_objects(path, 3)

        self.assertEqual([row["i"] for row in rows], [7, 8, 9])

    def test_only_submitted_unresolved_candidate_needs_rpc_check(self):
        now = datetime.now(timezone.utc)
        candidate = {
            "candidateBlockHash": "abc",
            "submitblockSent": True,
            "submitblockSubmittedAt": (now - timedelta(minutes=1)).isoformat(),
        }

        self.assertTrue(
            MODULE._should_check_candidate(
                candidate,
                None,
                now=now,
                retry_no_match_seconds=600,
            )
        )
        self.assertFalse(
            MODULE._should_check_candidate(
                candidate,
                {"followupStatus": "match-found"},
                now=now,
                retry_no_match_seconds=600,
            )
        )

        stale_unsubmitted = dict(candidate)
        stale_unsubmitted["submitblockSent"] = False
        self.assertFalse(
            MODULE._should_check_candidate(
                stale_unsubmitted,
                None,
                now=now,
                retry_no_match_seconds=600,
            )
        )

    def test_no_match_retry_window_is_bounded(self):
        now = datetime.now(timezone.utc)
        recent = {
            "candidateBlockHash": "recent",
            "submitblockSent": True,
            "submitblockSubmittedAt": (now - timedelta(minutes=2)).isoformat(),
        }
        old = {
            "candidateBlockHash": "old",
            "submitblockSent": True,
            "submitblockSubmittedAt": (now - timedelta(minutes=30)).isoformat(),
        }
        previous = {"followupStatus": "no-match-found"}

        self.assertTrue(
            MODULE._should_check_candidate(
                recent,
                previous,
                now=now,
                retry_no_match_seconds=600,
            )
        )
        self.assertFalse(
            MODULE._should_check_candidate(
                old,
                previous,
                now=now,
                retry_no_match_seconds=600,
            )
        )

    def test_identical_check_error_does_not_append_duplicate(self):
        previous = {
            "followupStatus": "check-error",
            "followupObservedHeight": None,
            "followupObservedBlockHash": None,
            "followupNote": "RPC getblockheader returned HTTP 401",
        }
        current = dict(previous)

        self.assertFalse(MODULE._followup_changed(previous, current))

        current["followupNote"] = "different error"
        self.assertTrue(MODULE._followup_changed(previous, current))


if __name__ == "__main__":
    unittest.main()

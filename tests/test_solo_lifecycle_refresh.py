from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


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

    def test_incremental_snapshot_preserves_existing_candidates_and_merges_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted = root / "accepted-candidates.json"
            pool_snapshot = root / "pool-snapshot.json"
            accepted.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-08-12T00:00:00Z",
                        "accepted_candidates": [
                            {
                                "candidate_hash": "old",
                                "submit_timestamp": "2026-08-12T00:00:00Z",
                                "lifecycle_status": "confirmed",
                                "mining_mode": "solo",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pool_snapshot.write_text(
                json.dumps({"network": {"height": 1000}, "blocks": []}),
                encoding="utf-8",
            )

            def fake_normalize(row, _blocks, _height):
                block_hash = row.get("candidateBlockHash") or row.get("candidate_hash")
                return {
                    "candidate_hash": block_hash,
                    "submit_timestamp": row.get("candidateTimestamp") or row.get("submit_timestamp"),
                    "lifecycle_status": "confirmed" if block_hash == "old" else "submit_accepted",
                    "mining_mode": "solo",
                }

            with mock.patch.object(MODULE, "_normalized_record_from_outcome", side_effect=fake_normalize):
                count = MODULE._merge_incremental_accepted_candidates(
                    outcome_rows=[
                        {
                            "candidateBlockHash": "new",
                            "candidateTimestamp": "2026-08-12T00:01:00Z",
                        }
                    ],
                    accepted_candidates=accepted,
                    pool_snapshot=pool_snapshot,
                )

            payload = json.loads(accepted.read_text(encoding="utf-8"))
            self.assertEqual(count, 2)
            self.assertEqual(
                [item["candidate_hash"] for item in payload["accepted_candidates"]],
                ["old", "new"],
            )

    def test_existing_snapshot_avoids_full_outcome_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted = root / "accepted-candidates.json"
            pool_snapshot = root / "pool-snapshot.json"
            outcome_events = root / "candidate-outcome-events.jsonl"
            accepted.write_text(json.dumps({"accepted_candidates": []}), encoding="utf-8")
            pool_snapshot.write_text(
                json.dumps({"network": {"height": 1}, "blocks": []}),
                encoding="utf-8",
            )
            outcome_events.write_text("", encoding="utf-8")

            with mock.patch.object(MODULE.subprocess, "run") as run_mock:
                mode, count = MODULE._rebuild_accepted_candidates(
                    repo_root=root,
                    outcome_events=outcome_events,
                    outcome_rows=[],
                    accepted_candidates=accepted,
                    pool_snapshot=pool_snapshot,
                )

            run_mock.assert_not_called()
            self.assertEqual(mode, "incremental")
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

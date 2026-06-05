from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

# Add ops/scripts to python path
import sys
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "ops" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import track_accepted_candidates

class TrackAcceptedCandidatesTests(unittest.TestCase):
    def test_map_lifecycle_status(self):
        # Case 1: Match found
        row_match = {
            "followupStatus": "match-found",
            "candidateOutcomeStatus": "chain-match-found",
        }
        self.assertEqual(track_accepted_candidates.map_lifecycle_status(row_match), "chain_match_found")

        # Case 2: No match found
        row_no_match = {
            "followupStatus": "no-match-found",
            "candidateOutcomeStatus": "chain-match-not-found",
        }
        self.assertEqual(track_accepted_candidates.map_lifecycle_status(row_no_match), "chain_match_not_found")

        # Case 3: Submitted but not checked (recent)
        row_recent = {
            "followupStatus": "not-checked",
            "submitblockSent": True,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self.assertEqual(track_accepted_candidates.map_lifecycle_status(row_recent), "submitted")

        # Case 4: Submitted but not checked (old -> pending followup)
        row_old = {
            "followupStatus": "not-checked",
            "submitblockSent": True,
            "timestamp": "2026-06-05T12:00:00Z",
        }
        self.assertEqual(track_accepted_candidates.map_lifecycle_status(row_old), "pending_followup")

        # Case 5: Unknown/disabled status
        row_disabled = {
            "followupStatus": "not-checked",
            "submitblockSent": False,
            "submitblockRealSubmitStatus": "submit-disabled-flag-off",
        }
        self.assertEqual(track_accepted_candidates.map_lifecycle_status(row_disabled), "unknown")

    def test_track_candidates_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "candidate-outcome-events.jsonl"
            out_path = Path(tmpdir) / "accepted-candidates.json"

            events = [
                # Submitted but disabled - should NOT be included
                {
                    "candidateBlockHash": "hash1",
                    "followupStatus": "not-checked",
                    "submitblockSent": False,
                    "submitblockRealSubmitStatus": "submit-disabled-flag-off",
                    "timestamp": "2026-06-05T12:00:00Z",
                },
                # Submitted successfully, not checked (old) - should be included as pending_followup
                {
                    "candidateBlockHash": "hash2",
                    "jobId": "job2",
                    "followupStatus": "not-checked",
                    "submitblockSent": True,
                    "submitblockDaemonAcceptedLikely": True,
                    "submitblockSubmittedAt": "2026-06-05T12:05:00Z",
                    "timestamp": "2026-06-05T12:05:00Z",
                },
                # Submitted successfully, followup match found - should be included as chain_match_found
                {
                    "candidateBlockHash": "hash3",
                    "jobId": "job3",
                    "followupStatus": "match-found",
                    "submitblockSent": True,
                    "submitblockDaemonAcceptedLikely": True,
                    "followupObservedHeight": 12345,
                    "followupObservedBlockHash": "hash3",
                    "submitblockSubmittedAt": "2026-06-05T12:10:00Z",
                    "timestamp": "2026-06-05T12:12:00Z",
                }
            ]

            # Write events
            with log_path.open("w", encoding="utf-8") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")

            # Run tracking logic by mocking sys.argv
            orig_argv = sys.argv
            sys.argv = ["track_accepted_candidates.py", str(log_path), str(out_path)]
            try:
                exit_code = track_accepted_candidates.main()
                self.assertEqual(exit_code, 0)
            finally:
                sys.argv = orig_argv

            # Verify JSON file exists
            self.assertTrue(out_path.exists())
            data = json.loads(out_path.read_text(encoding="utf-8"))

            self.assertIn("updated_at", data)
            accepted = data["accepted_candidates"]
            self.assertEqual(len(accepted), 2)  # hash2 and hash3

            # Check hash2 (pending followup)
            self.assertEqual(accepted[0]["candidate_hash"], "hash2")
            self.assertEqual(accepted[0]["lifecycle_status"], "pending_followup")
            self.assertEqual(accepted[0]["job_id"], "job2")

            # Check hash3 (chain match found)
            self.assertEqual(accepted[1]["candidate_hash"], "hash3")
            self.assertEqual(accepted[1]["lifecycle_status"], "chain_match_found")
            self.assertEqual(accepted[1]["matched_height"], 12345)

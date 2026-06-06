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
        # Case 1: Match found, no confirmations in snapshot
        row_match = {
            "followupStatus": "match-found",
            "candidateOutcomeStatus": "chain-match-found",
            "candidateBlockHash": "hash3",
        }
        status, conf, maturity = track_accepted_candidates.map_lifecycle_status(row_match, [], 0)
        self.assertEqual(status, "chain_match_found")
        self.assertIsNone(conf)
        self.assertEqual(maturity, "immature")

        # Case 2: No match found (orphan)
        row_no_match = {
            "followupStatus": "no-match-found",
            "candidateOutcomeStatus": "chain-match-not-found",
        }
        status, conf, maturity = track_accepted_candidates.map_lifecycle_status(row_no_match, [], 0)
        self.assertEqual(status, "orphan")

        # Case 3: Match found, but immature confirmations (e.g. 5 confirms)
        row_immature = {
            "followupStatus": "match-found",
            "candidateBlockHash": "hash-imm",
        }
        snapshot_blocks = [{"hash": "hash-imm", "confirmations": 5}]
        status, conf, maturity = track_accepted_candidates.map_lifecycle_status(row_immature, snapshot_blocks, 0)
        self.assertEqual(status, "immature")
        self.assertEqual(conf, 5)
        self.assertEqual(maturity, "immature")

        # Case 4: Match found, confirmed (e.g. 100 confirms)
        row_confirmed = {
            "followupStatus": "match-found",
            "candidateBlockHash": "hash-conf",
        }
        snapshot_blocks = [{"hash": "hash-conf", "confirmations": 105}]
        status, conf, maturity = track_accepted_candidates.map_lifecycle_status(row_confirmed, snapshot_blocks, 0)
        self.assertEqual(status, "confirmed")
        self.assertEqual(conf, 105)
        self.assertEqual(maturity, "mature")

        # Case 5: Disabled submit - candidate_recorded
        row_disabled = {
            "followupStatus": "not-checked",
            "submitblockSent": False,
            "submitblockRealSubmitStatus": "submit-disabled-flag-off",
        }
        status, conf, maturity = track_accepted_candidates.map_lifecycle_status(row_disabled, [], 0)
        self.assertEqual(status, "candidate_recorded")

    def test_track_candidates_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "candidate-outcome-events.jsonl"
            out_path = Path(tmpdir) / "accepted-candidates.json"

            events = [
                # Submitted but disabled - should be included as candidate_recorded
                {
                    "candidateBlockHash": "hash1",
                    "followupStatus": "not-checked",
                    "submitblockSent": False,
                    "submitblockRealSubmitStatus": "submit-disabled-flag-off",
                    "timestamp": "2026-06-05T12:00:00Z",
                },
                # Submitted successfully, not checked - should be included as submit_accepted
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
            self.assertEqual(len(accepted), 3)  # hash1, hash2 and hash3

            # Check hash1 (candidate_recorded)
            self.assertEqual(accepted[0]["candidate_hash"], "hash1")
            self.assertEqual(accepted[0]["lifecycle_status"], "candidate_recorded")

            # Check hash2 (submit_accepted)
            self.assertEqual(accepted[1]["candidate_hash"], "hash2")
            self.assertEqual(accepted[1]["lifecycle_status"], "submit_accepted")
            self.assertEqual(accepted[1]["job_id"], "job2")

            # Check hash3 (chain_match_found because confirmations are not in empty snapshot blocks)
            self.assertEqual(accepted[2]["candidate_hash"], "hash3")
            self.assertEqual(accepted[2]["lifecycle_status"], "chain_match_found")
            self.assertEqual(accepted[2]["matched_height"], 12345)


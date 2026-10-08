from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import resource_health  # noqa: E402


class ResourceHealthTests(unittest.TestCase):
    def test_root_filesystem_warning_thresholds(self):
        self.assertIsNone(resource_health.filesystem_warning(79.99))
        self.assertEqual(resource_health.filesystem_warning(80.0), "root-filesystem-usage-high")
        self.assertEqual(resource_health.filesystem_warning(89.99), "root-filesystem-usage-high")
        self.assertEqual(resource_health.filesystem_warning(90.0), "root-filesystem-usage-critical")

    def test_round_attribution_health_separates_maturity_and_missing_coverage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "rounds.json"
            path.write_text(json.dumps({"rounds": [
                {"status": "immature", "submit_timestamp": "2026-10-08T10:00:00Z"},
                {"status": "confirmed", "submit_timestamp": "2026-10-08T11:00:00Z",
                 "attribution_reason": "share_window_sequence_gap", "attribution_coverage_verified": False},
                {"status": "confirmed", "submit_timestamp": "2026-10-08T12:00:00Z",
                 "attribution_persisted": True, "attribution_coverage_verified": True},
            ]}), encoding="utf-8")
            health = resource_health.round_attribution_health(path)
            self.assertEqual(health["newestConfirmedPoolCandidateAt"], "2026-10-08T12:00:00Z")
            self.assertEqual(health["confirmedCandidatesAwaitingCoverage"], 1)
            self.assertTrue(health["latestCompletedRoundPersisted"])
            self.assertEqual(health["maturityWaitCandidateCount"], 1)


if __name__ == "__main__":
    unittest.main()

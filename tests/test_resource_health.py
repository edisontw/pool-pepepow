from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()

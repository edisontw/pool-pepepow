from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))

from runtime_io import write_json_atomic  # noqa: E402


class RuntimeIoTests(unittest.TestCase):
    def test_write_json_atomic_replaces_existing_file_without_tmp_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "snapshot.json"
            output_path.write_text('{"stale": true}\n', encoding="utf-8")

            write_json_atomic({"fresh": True}, output_path)

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"fresh": True})
            temp_files = list(Path(tmp_dir).glob(".snapshot.json.*.tmp"))
            self.assertEqual(temp_files, [])


if __name__ == "__main__":
    unittest.main()

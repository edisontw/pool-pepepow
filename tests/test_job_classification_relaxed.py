import unittest
import sys
from pathlib import Path
from unittest import mock

POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))

import stratum_ingress

class JobClassificationTests(unittest.TestCase):
    def test_classify_submit_job_id_relaxed(self):
        # current job A, previous job B
        # Job C was issued before B but is still in active cache
        
        current_job_id = "job-A"
        previous_job_id = "job-B"
        
        # Case 1: current job
        res = stratum_ingress._classify_submit_job_id(
            "job-A",
            current_job_id=current_job_id,
            previous_job_id=previous_job_id,
            cached_job=mock.Mock(),
            is_stale_job=False
        )
        self.assertEqual(res, "current")
        
        # Case 2: exactly previous job
        res = stratum_ingress._classify_submit_job_id(
            "job-B",
            current_job_id=current_job_id,
            previous_job_id=previous_job_id,
            cached_job=mock.Mock(),
            is_stale_job=False
        )
        self.assertEqual(res, "previous")
        
        # Case 3: older job but still in cache
        res = stratum_ingress._classify_submit_job_id(
            "job-C",
            current_job_id=current_job_id,
            previous_job_id=previous_job_id,
            cached_job=mock.Mock(),
            is_stale_job=False
        )
        self.assertEqual(res, "previous") # Should be "previous" instead of "unknown" or "stale"
        
        # Case 4: stale job (in retired cache)
        res = stratum_ingress._classify_submit_job_id(
            "job-D",
            current_job_id=current_job_id,
            previous_job_id=previous_job_id,
            cached_job=None,
            is_stale_job=True
        )
        self.assertEqual(res, "stale")

if __name__ == "__main__":
    unittest.main()

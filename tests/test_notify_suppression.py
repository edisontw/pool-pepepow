import asyncio
import unittest
import sys
import json
from pathlib import Path
from unittest import mock
import tempfile
from datetime import datetime, timezone

POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))

import stratum_ingress
import template_jobs
import config
import stratum_protocol

class MockWriter:
    def __init__(self):
        self.messages = []
        self.closed = False
    def write(self, data):
        self.messages.append(data)
    async def drain(self):
        pass
    def is_closing(self):
        return self.closed
    def get_extra_info(self, name):
        return ("127.0.0.1", 12345)

class NotifySuppressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_loop_suppresses_redundant(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            
            # Mock environment for load_config
            env_mock = {
                "PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH": str(tmp_path / "shares.jsonl"),
                "PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT": str(tmp_path / "snapshot.json"),
                "PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT": str(tmp_path / "pool.json"),
                "PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS": "1",
            }
            
            with mock.patch.dict("os.environ", env_mock):
                cfg = config.load_config()
            
            # Force interval to be even smaller for the test if possible, 
            # but config.py has a max(1.0, ...) clamp.
            # We'll just wait for 1.1s.
            
            service = stratum_ingress.StratumIngressService(cfg)
            
            state = stratum_protocol.new_connection_state()
            state.authorized = True
            state.last_notified_anchor = "anchor-1"
            
            writer = MockWriter()
            send_lock = asyncio.Lock()
            
            # Mock job manager
            service._job_manager = mock.Mock(spec=template_jobs.TemplateJobManager)
            service._job_manager.latest_template_anchor = "anchor-1"
            
            # We also need to mock _new_notify_message because it calls issue_job
            service._new_notify_message = mock.Mock(return_value={"method": "mining.notify", "params": ["job-X", "prev", "c1", "c2", [], "v", "b", "t", True]})
            
            # Start notify loop
            service._stop_event = asyncio.Event()
            loop_task = asyncio.create_task(service._notify_loop(state, writer, send_lock))
            
            # Wait 1.5s (more than the 1.0s interval)
            await asyncio.sleep(1.5)
            
            # Should have sent 0 messages (all redundant)
            self.assertEqual(len(writer.messages), 0)
            
            # Now change anchor
            service._job_manager.latest_template_anchor = "anchor-2"
            
            # Wait 1.5s
            await asyncio.sleep(1.5)
            
            # Should have sent 1 message now
            self.assertGreater(len(writer.messages), 0)
            
            last_msg = json.loads(writer.messages[-1].decode().strip())
            self.assertEqual(last_msg["method"], "mining.notify")
            
            service._stop_event.set()
            await loop_task

if __name__ == "__main__":
    unittest.main()

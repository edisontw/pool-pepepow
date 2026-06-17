#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import pool_wallet_monitor


class PoolWalletWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.accepted = self.tmp_path / "accepted-candidates.json"
        self.actions = self.tmp_path / "payment-actions.jsonl"
        self.payments = self.tmp_path / "payments-snapshot.json"
        self.state = self.tmp_path / "watchdog-state.json"
        self.output = self.tmp_path / "watchdog.json"
        self.old_env = dict(os.environ)
        os.environ["PEPEPOW_POOL_FEE_PERCENT"] = "2.0"
        os.environ["PEPEPOW_MIN_PAYOUT"] = "25.0"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp_dir.cleanup()

    def _args(self, balance):
        return [
            "watchdog",
            "--accepted-candidates", str(self.accepted),
            "--payment-actions", str(self.actions),
            "--payments-snapshot", str(self.payments),
            "--state", str(self.state),
            "--output", str(self.output),
            "--balance", str(balance),
            "--format", "json",
        ]

    def _write_inputs(self, candidates, actions=None, payments=None):
        with self.accepted.open("w", encoding="utf-8") as f:
            json.dump({"accepted_candidates": candidates}, f)
        with self.actions.open("w", encoding="utf-8") as f:
            for action in actions or []:
                f.write(json.dumps(action) + "\n")
        with self.payments.open("w", encoding="utf-8") as f:
            json.dump({"items": payments or []}, f)

    def _run_main(self, args):
        with redirect_stdout(StringIO()):
            return pool_wallet_monitor.main(args)

    def test_watchdog_records_baseline_without_alert(self):
        self._write_inputs([
            {"candidate_hash": "cand1", "lifecycle_status": "confirmed", "matched_height": 10}
        ])

        rc = self._run_main(self._args(1000.0))

        self.assertEqual(rc, 0)
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "baseline")
        self.assertIsNone(data["expectedDelta"])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["seenCandidateIds"], ["cand1"])

    def test_watchdog_accepts_expected_confirmed_block_and_payment_delta(self):
        self._write_inputs([{"candidate_hash": "old", "lifecycle_status": "confirmed"}])
        self._run_main(self._args(1000.0))
        self._write_inputs(
            [
                {"candidate_hash": "old", "lifecycle_status": "confirmed"},
                {"candidate_hash": "new", "lifecycle_status": "confirmed", "matched_height": 11},
            ],
            actions=[
                {
                    "action": "manual_payment_recorded",
                    "candidate_id": "new",
                    "wallet": "minerWallet",
                    "amount": 1000.0,
                    "txid": "tx1",
                }
            ],
        )

        rc = self._run_main(self._args(4322.5))

        self.assertEqual(rc, 0)
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertAlmostEqual(data["actualDelta"], 3322.5)
        self.assertAlmostEqual(data["expectedDelta"], 3322.5)
        self.assertAlmostEqual(data["accounting"]["newPoolRetainedTotal"], 86.45)
        self.assertAlmostEqual(data["accounting"]["newMinerNetTotal"], 4236.05)

    def test_watchdog_alerts_on_unexpected_increase(self):
        self._write_inputs([])
        self._run_main(self._args(1000.0))
        self._write_inputs([])

        rc = self._run_main(self._args(1010.5))

        self.assertEqual(rc, 1)
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "warning")
        self.assertAlmostEqual(data["unexpectedIncrease"], 10.5)

    def test_watchdog_deduplicates_actions_and_payment_snapshot(self):
        self._write_inputs([])
        self._run_main(self._args(1000.0))
        action = {
            "action": "manual_payment_recorded",
            "candidate_id": "old",
            "wallet": "minerWallet",
            "amount": 100.0,
            "txid": "tx1",
        }
        self._write_inputs([], actions=[action], payments=[{"wallet": "minerWallet", "amount": 100.0, "txid": "tx1"}])

        rc = self._run_main(self._args(900.0))

        self.assertEqual(rc, 0)
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(data["accounting"]["newOutgoingPaymentCount"], 1)
        self.assertAlmostEqual(data["expectedDelta"], -100.0)

    def test_live_stratum_wrapper_runs_watchdog(self):
        self._write_inputs([])
        script = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "live-stratum.sh"
        env = dict(os.environ)
        env["PEPEPOW_LIVE_STRATUM_RUNTIME_DIR"] = str(self.tmp_path)

        res = subprocess.run(
            [
                str(script),
                "pool-wallet-watchdog",
                "--balance",
                "1000",
                "--format",
                "json",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, msg=f"stdout: {res.stdout}\nstderr: {res.stderr}")
        data = json.loads(res.stdout.strip())
        self.assertEqual(data["status"], "baseline")


if __name__ == "__main__":
    unittest.main()

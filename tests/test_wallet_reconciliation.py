#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ops/scripts"))

import pool_wallet_monitor
import payout_helper


class TestWalletReconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.now_dt = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
        self.t_now = int(self.now_dt.timestamp())
        self.t_24h_ago = self.t_now - 86400

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_exact_positive_reconciliation_ok(self, mock_daemon, mock_wallet):
        # 1. Exact positive reconciliation -> OK
        # Setup: 1 mature block generated (1000 PEPEW), 1 send (400 PEPEW to miner + fee 0.001)
        # Expected liquidity change = 1000 - 400 - 0.001 = +599.999 PEPEW
        tx_gen = {
            "txid": "gen001",
            "blockhash": "block001",
            "category": "generate",
            "amount": 1000.0,
            "confirmations": 101,
            "time": self.t_now - 3600,
        }
        tx_send = {
            "txid": "send001",
            "category": "send",
            "amount": -400.001,
            "fee": -0.001,
            "time": self.t_now - 1800,
            "hex": "deadbeef",
        }

        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_gen, tx_send],
            "gettransaction": {
                "txid": "send001",
                "fee": -0.001,
                "hex": "deadbeef",
                "details": [{"category": "send", "amount": -400.0}],
            },
            "validateaddress": {"ismine": params[0] == "P_WALLET_CHANGE"},
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 400.0, "scriptPubKey": {"addresses": ["P_MINER_EXTERNAL"]}},
                    {"value": 600.0, "scriptPubKey": {"addresses": ["P_WALLET_CHANGE"]}},
                ]
            }
        }.get(method)

        # Payment action log
        act_log = self.tmp_path / "payment-actions.jsonl"
        act_log.write_text(json.dumps({
            "txid": "send001",
            "wallet": "P_MINER_EXTERNAL",
            "amount": 400.0,
            "timestamp": "2026-08-14T11:30:00Z"
        }) + "\n", encoding="utf-8")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
                tolerance=Decimal("0.01"),
            )

        self.assertEqual(recon["status"], "ok")
        self.assertEqual(recon["reconciliationDifference"], 0.0)
        self.assertAlmostEqual(recon["expectedLiquidityChange"], 599.999, places=3)
        self.assertEqual(recon["unrecordedExternalTransactions"], 0)
        self.assertEqual(recon["duplicateOrExcessPayouts"], 0)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_exact_negative_liquidity_reconciliation_ok(self, mock_daemon, mock_wallet):
        # 2. Exact negative liquidity reconciliation -> OK
        # Setup: 1 mature block (1000 PEPEW), 1 send (1500 PEPEW external payout + 0.001 fee)
        # Expected liquidity change = 1000 - 1500 - 0.001 = -500.001 PEPEW
        tx_gen = {
            "txid": "gen002",
            "blockhash": "block002",
            "category": "generate",
            "amount": 1000.0,
            "confirmations": 120,
            "time": self.t_now - 5000,
        }
        tx_send = {
            "txid": "send002",
            "category": "send",
            "amount": -1500.001,
            "fee": -0.001,
            "time": self.t_now - 2000,
            "hex": "feedbeef",
        }

        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_gen, tx_send],
            "gettransaction": {
                "txid": "send002",
                "fee": -0.001,
                "hex": "feedbeef",
            },
            "validateaddress": {"ismine": params[0] == "P_CHANGE_ADDR"},
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 1500.0, "scriptPubKey": {"addresses": ["P_MINER_A"]}},
                    {"value": 5000.0, "scriptPubKey": {"addresses": ["P_CHANGE_ADDR"]}},
                ]
            }
        }.get(method)

        act_log = self.tmp_path / "payment-actions.jsonl"
        act_log.write_text(json.dumps({
            "txid": "send002",
            "wallet": "P_MINER_A",
            "amount": 1500.0,
            "timestamp": "2026-08-14T11:26:40Z"
        }) + "\n", encoding="utf-8")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
                tolerance=Decimal("0.01"),
            )

        self.assertEqual(recon["status"], "ok")
        self.assertAlmostEqual(recon["expectedLiquidityChange"], -500.001, places=3)
        self.assertAlmostEqual(recon["actualLiquidityChange"], -500.001, places=3)
        self.assertEqual(recon["reconciliationDifference"], 0.0)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_dynamic_unseen_ismine_address_is_internal(self, mock_daemon, mock_wallet):
        # 3. Newly generated unseen ismine=true address -> internal wallet output, not external
        tx_send = {
            "txid": "send_unseen",
            "category": "send",
            "amount": -50.0,
            "fee": -0.0005,
            "time": self.t_now - 1000,
            "hex": "aa11bb22",
        }
        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_send],
            "gettransaction": {"txid": "send_unseen", "fee": -0.0005, "hex": "aa11bb22"},
            "validateaddress": {"ismine": params[0] == "P_COMPLETELY_NEW_CHANGE_ADDR_123"},
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 50.0, "scriptPubKey": {"addresses": ["P_MINER_DEST"]}},
                    {"value": 950.0, "scriptPubKey": {"addresses": ["P_COMPLETELY_NEW_CHANGE_ADDR_123"]}},
                ]
            }
        }.get(method)

        act_log = self.tmp_path / "payment-actions.jsonl"
        act_log.write_text(json.dumps({
            "txid": "send_unseen",
            "wallet": "P_MINER_DEST",
            "amount": 50.0,
            "timestamp": "2026-08-14T11:43:20Z"
        }) + "\n", encoding="utf-8")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["poolExternalPayouts"], 50.0)
        self.assertEqual(recon["walletOwnedOutputCount"], 1)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_multiple_ismine_outputs_plus_external_output(self, mock_daemon, mock_wallet):
        # 4. Multiple ismine=true outputs + one external miner output -> only external counts
        tx_send = {
            "txid": "send_multi_internal",
            "category": "send",
            "amount": -100.0,
            "fee": -0.001,
            "time": self.t_now - 1200,
            "hex": "multi_hex",
        }
        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_send],
            "gettransaction": {"txid": "send_multi_internal", "fee": -0.001, "hex": "multi_hex"},
            "validateaddress": {"ismine": params[0] in ("P_INTERNAL_1", "P_INTERNAL_2", "P_REWARD_ADDR")},
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 100.0, "scriptPubKey": {"addresses": ["P_MINER_TARGET"]}},
                    {"value": 300.0, "scriptPubKey": {"addresses": ["P_INTERNAL_1"]}},
                    {"value": 200.0, "scriptPubKey": {"addresses": ["P_INTERNAL_2"]}},
                    {"value": 50.0, "scriptPubKey": {"addresses": ["P_REWARD_ADDR"]}},
                ]
            }
        }.get(method)

        act_log = self.tmp_path / "payment-actions.jsonl"
        act_log.write_text(json.dumps({
            "txid": "send_multi_internal",
            "wallet": "P_MINER_TARGET",
            "amount": 100.0,
            "timestamp": "2026-08-14T11:40:00Z"
        }) + "\n", encoding="utf-8")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["poolExternalPayouts"], 100.0)
        self.assertEqual(recon["walletOwnedOutputCount"], 3)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_largest_output_external_and_smallest_internal_do_not_rely_on_heuristics(self, mock_daemon, mock_wallet):
        # 5 & 6. Largest output is external (e.g. 50,000 PEPEW payout) and change is small (10 PEPEW)
        tx_send = {
            "txid": "send_large_payout",
            "category": "send",
            "amount": -50000.0,
            "fee": -0.001,
            "time": self.t_now - 1500,
            "hex": "large_hex",
        }
        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_send],
            "gettransaction": {"txid": "send_large_payout", "fee": -0.001, "hex": "large_hex"},
            "validateaddress": {"ismine": params[0] == "P_SMALL_CHANGE"},
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 50000.0, "scriptPubKey": {"addresses": ["P_WHALE_MINER"]}},
                    {"value": 10.0, "scriptPubKey": {"addresses": ["P_SMALL_CHANGE"]}},
                ]
            }
        }.get(method)

        act_log = self.tmp_path / "payment-actions.jsonl"
        act_log.write_text(json.dumps({
            "txid": "send_large_payout",
            "wallet": "P_WHALE_MINER",
            "amount": 50000.0,
            "timestamp": "2026-08-14T11:35:00Z"
        }) + "\n", encoding="utf-8")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["poolExternalPayouts"], 50000.0)
        self.assertEqual(recon["unrecordedExternalTransactions"], 0)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_unrecorded_external_transaction_triggers_alert(self, mock_daemon, mock_wallet):
        # 7. Unrecorded external transaction -> ALERT (critical)
        tx_send = {
            "txid": "unrecorded_rogue_send",
            "category": "send",
            "amount": -500.0,
            "fee": -0.001,
            "time": self.t_now - 1000,
            "hex": "rogue_hex",
        }
        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_send],
            "gettransaction": {"txid": "unrecorded_rogue_send", "fee": -0.001, "hex": "rogue_hex"},
            "validateaddress": {"ismine": False},
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 500.0, "scriptPubKey": {"addresses": ["P_UNKNOWN_EXTERNAL"]}},
                ]
            }
        }.get(method)

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["status"], "critical")
        self.assertEqual(recon["unrecordedExternalTransactions"], 1)
        self.assertIn("unrecorded_rogue_send", recon["unrecordedTxids"])

    @patch("payout_helper.wallet_readonly_call")
    def test_duplicate_excess_payout_triggers_alert(self, mock_wallet):
        # 8. Duplicate / excess payout in action log -> ALERT (critical)
        mock_wallet.side_effect = lambda method, params: {"listtransactions": []}.get(method, {})

        act_log = self.tmp_path / "payment-actions.jsonl"
        dup_row = json.dumps({
            "txid": "tx_dup",
            "wallet": "P_MINER_DUP",
            "amount": 100.0,
            "timestamp": "2026-08-14T11:00:00Z"
        }) + "\n"
        act_log.write_text(dup_row + dup_row, encoding="utf-8")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["status"], "critical")
        self.assertGreaterEqual(recon["duplicateOrExcessPayouts"], 1)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_material_unknown_output_triggers_warning_incomplete(self, mock_daemon, mock_wallet):
        # 9. Material unknown output ownership -> WARN (incomplete)
        tx_send = {
            "txid": "send_unknown_ownership",
            "category": "send",
            "amount": -100.0,
            "fee": -0.001,
            "time": self.t_now - 1000,
            "hex": "unknown_hex",
        }
        # validateaddress fails/returns None
        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_send],
            "gettransaction": {"txid": "send_unknown_ownership", "fee": -0.001, "hex": "unknown_hex"},
            "validateaddress": None,
        }.get(method)

        mock_daemon.side_effect = lambda method, params: {
            "decoderawtransaction": {
                "vout": [
                    {"value": 100.0, "scriptPubKey": {"addresses": ["P_AMBIGUOUS"]}},
                ]
            }
        }.get(method)

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["status"], "warning")
        self.assertFalse(recon["reconciliationComplete"])
        self.assertGreaterEqual(recon["unknownOutputCount"], 1)

    @patch("payout_helper.wallet_readonly_call")
    def test_missing_wallet_rpc_triggers_warning(self, mock_wallet):
        # 10. Missing wallet RPC / error -> WARN, never false OK
        mock_wallet.side_effect = Exception("Wallet RPC connection refused")

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["status"], "warning")
        self.assertFalse(recon["reconciliationComplete"])
        self.assertTrue(len(recon["errors"]) > 0)

    @patch("payout_helper.wallet_readonly_call")
    @patch("payout_helper.daemon_readonly_call")
    def test_distinguish_pool_and_solo_rewards(self, mock_daemon, mock_wallet):
        # 13. Pool and SOLO rewards remain distinguishable
        solo_cand_file = self.tmp_path / "solo/accepted-candidates.json"
        solo_cand_file.parent.mkdir(parents=True, exist_ok=True)
        solo_cand_file.write_text(json.dumps({
            "accepted_candidates": [{"matched_block_hash": "solo_block_hash_01"}]
        }), encoding="utf-8")

        tx_pool = {
            "txid": "gen_pool",
            "blockhash": "pool_block_hash_01",
            "category": "generate",
            "amount": 3737.5,
            "confirmations": 150,
            "time": self.t_now - 1000,
        }
        tx_solo = {
            "txid": "gen_solo",
            "blockhash": "solo_block_hash_01",
            "category": "generate",
            "amount": 3737.5,
            "confirmations": 150,
            "time": self.t_now - 800,
        }

        mock_wallet.side_effect = lambda method, params: {
            "listtransactions": [tx_pool, tx_solo],
        }.get(method, {})

        with patch("pool_wallet_monitor.RUNTIME_DIR", self.tmp_path):
            recon = pool_wallet_monitor.compute_wallet_reconciliation(
                now_dt=self.now_dt,
                window_hours=24.0,
            )

        self.assertEqual(recon["poolRewardsReceived"], 3737.5)
        self.assertEqual(recon["soloRewardsReceived"], 3737.5)
        self.assertEqual(recon["poolMatureBlockCount"], 1)
        self.assertEqual(recon["soloMatureBlockCount"], 1)


if __name__ == "__main__":
    unittest.main()

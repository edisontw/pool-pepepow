from __future__ import annotations

import asyncio
import io
import importlib.util
import json
import re
import sys
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))


def _load_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, POOL_CORE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pool_core_config = _load_module("pool_core_config", "config.py")
sys.modules["config"] = pool_core_config
stratum_ingress = _load_module("pool_core_stratum_ingress", "stratum_ingress.py")
pool_core_daemon_rpc = sys.modules["daemon_rpc"]
stratum_protocol = sys.modules["stratum_protocol"]
template_jobs = sys.modules["template_jobs"]

PoolCoreConfig = pool_core_config.PoolCoreConfig
StratumIngressService = stratum_ingress.StratumIngressService
DaemonRpcUnavailableError = pool_core_daemon_rpc.DaemonRpcUnavailableError
DaemonRpcResponseError = pool_core_daemon_rpc.DaemonRpcResponseError
SessionStats = stratum_ingress.SessionStats
SubmitAssessment = stratum_ingress.SubmitAssessment


class SuccessfulTemplateRpcClient:
    def __init__(
        self,
        *,
        allow_submitblock: bool = False,
        submitblock_result: object = None,
    ) -> None:
        self.submitblock_calls: list[tuple[object, ...]] = []
        self._allow_submitblock = allow_submitblock
        self._submitblock_result = submitblock_result

    def get_block_template(self) -> dict[str, object]:
        return {
            "previousblockhash": "1" * 64,
            "transactions": [
                {
                    "data": (
                        "01000000010000000000000000000000000000000000000000000000000000000000000000"
                        "00000000ffffffff0100000000000000000000000000"
                    ),
                }
            ],
            "coinbaseaux": {"flags": "f00d"},
            "coinbasevalue": 5_000_000_000,
            "bits": "1c0ffff0",
            "target": "0f" * 32,
            "height": 123456,
            "version": 536870912,
            "curtime": 1713225600,
        }

    def submitblock(self, *args: object) -> object:
        self.submitblock_calls.append(args)
        if not self._allow_submitblock:
            raise AssertionError("submitblock must not be called during dry-run prep")
        return self._submitblock_result


class PartialTemplateRpcClient(SuccessfulTemplateRpcClient):
    def get_block_template(self) -> dict[str, object]:
        payload = super().get_block_template()
        payload["transactions"] = [{"hash": "2" * 64}]
        return payload


class ErroringSubmitblockRpcClient(SuccessfulTemplateRpcClient):
    def submitblock(self, *args: object) -> object:
        self.submitblock_calls.append(args)
        raise RuntimeError("submitblock failed")


class FollowupFoundRpcClient:
    def get_block_header(self, block_hash: str) -> dict[str, object]:
        return {"hash": block_hash, "height": 123456}


class FollowupNotFoundRpcClient:
    def get_block_header(self, block_hash: str) -> dict[str, object]:
        raise DaemonRpcResponseError(
            "RPC getblockheader error: {'code': -5, 'message': 'Block not found'}"
        )


class FollowupErrorRpcClient:
    def get_block_header(self, block_hash: str) -> dict[str, object]:
        raise DaemonRpcUnavailableError("RPC getblockheader failed: connection refused")


class FailingTemplateRpcClient:
    def get_block_template(self) -> dict[str, object]:
        raise DaemonRpcUnavailableError("template RPC unavailable")


class EmptyMasternodeTemplateRpcClient(SuccessfulTemplateRpcClient):
    def get_block_template(self) -> dict[str, object]:
        payload = super().get_block_template()
        payload["masternode"] = {}
        payload["foundation"] = [
            {
                "script": "76a9143ec00d0d0e9a538b564d0bae64e1076d7ddd286688ac",
                "amount": 0,
            }
        ]
        return payload


class StratumIngressTests(unittest.IsolatedAsyncioTestCase):
    def test_load_config_clamps_hashrate_assumed_share_difficulty_to_pool_floor(self):
        with mock.patch.dict(
            "os.environ",
            {"PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY": "1e-08"},
            clear=False,
        ):
            config = pool_core_config.load_config()

        self.assertEqual(config.hashrate_assumed_share_difficulty, 0.01)
        self.assertEqual(config.estimated_hashrate_assumed_share_difficulty, 0.01)

    def test_load_config_reads_stratum_vardiff_settings(self):
        with mock.patch.dict(
            "os.environ",
            {
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED": "true",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY": "0.2",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY": "0.02",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MAX_DIFFICULTY": "32",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_RETARGET_INTERVAL_SECONDS": "90",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_SHARES": "5",
            },
            clear=False,
        ):
            config = pool_core_config.load_config()

        self.assertTrue(config.stratum_vardiff_enabled)
        self.assertEqual(config.stratum_vardiff_initial_difficulty, 0.2)
        self.assertEqual(config.stratum_vardiff_min_difficulty, 0.02)
        self.assertEqual(config.stratum_vardiff_max_difficulty, 32.0)
        self.assertEqual(config.stratum_vardiff_retarget_interval_seconds, 90.0)
        self.assertEqual(config.stratum_vardiff_min_shares, 5)

    def test_load_config_reads_stratum_wire_difficulty_scale(self):
        with mock.patch.dict(
            "os.environ",
            {"PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE": "65536"},
            clear=False,
        ):
            config = pool_core_config.load_config()

        self.assertEqual(config.stratum_wire_difficulty_scale, 65536.0)

    def test_load_config_reads_low_diff_share_full_log_every_n(self):
        with mock.patch.dict(
            "os.environ",
            {"PEPEPOW_POOL_CORE_LOW_DIFF_SHARE_FULL_LOG_EVERY_N": "10"},
            clear=False,
        ):
            config = pool_core_config.load_config()

        self.assertEqual(config.low_diff_share_full_log_every_n, 10)

    def test_load_config_allows_fixed_stratum_difficulty_of_point_zero_zero_one(self):
        with mock.patch.dict(
            "os.environ",
            {
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY": "0.001",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY": "0.001",
            },
            clear=False,
        ):
            config = pool_core_config.load_config()

        self.assertEqual(config.stratum_vardiff_initial_difficulty, 0.001)
        self.assertEqual(config.stratum_vardiff_min_difficulty, 0.001)

    def test_load_config_allows_fixed_stratum_difficulty_of_point_zero_zero_zero_zero_zero_one_five(self):
        with mock.patch.dict(
            "os.environ",
            {
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY": "0.0000015",
                "PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY": "0.0000015",
            },
            clear=False,
        ):
            config = pool_core_config.load_config()

        self.assertEqual(config.stratum_vardiff_initial_difficulty, 0.0000015)
        self.assertEqual(config.stratum_vardiff_min_difficulty, 0.0000015)

    def test_pepepow_header_hash_matches_known_chain_vector(self):
        header_hex = (
            "0040002038e31388c54124146478ff691985eecd02610db91efbc9cd7aabca4900000000"
            "07647f0508057dbf8c99ddaa87543c04e31dfe3f383e7386903d50c91728fabe830be169"
            "71e3021da96d9d33"
        )
        expected_hash = (
            "00000001fb895a82973fca52938848908d6a6cb3c0dfb93995dc61020ced0a6b"
        )
        share_hash = stratum_ingress._calculate_pepepow_share_hash(
            bytes.fromhex(header_hex)
        )
        self.assertEqual(share_hash.hex(), expected_hash)

    def test_format_prevhash_for_stratum_word_swaps_live_capture(self):
        canonical_prevhash = (
            "00000001aa59f20d1eb2b2c8407ef1dcb707927fb908704a1908006726cb42fa"
        )
        expected_wire_prevhash = (
            "010000000df259aac8b2b21edcf17e407f9207b74a7008b967000819fa42cb26"
        )

        self.assertEqual(
            stratum_protocol.format_prevhash_for_stratum(canonical_prevhash),
            expected_wire_prevhash,
        )

    def test_notify_notification_word_swaps_prevhash_only_on_wire(self):
        canonical_prevhash = (
            "00000001aa59f20d1eb2b2c8407ef1dcb707927fb908704a1908006726cb42fa"
        )
        notify_message = stratum_protocol.notify_notification(
            job_id="job-123",
            prevhash=canonical_prevhash,
            coinb1="aa",
            coinb2="bb",
            merkle_branch=["cc" * 32],
            version="20004000",
            nbits="1d0487ce",
            ntime="69ee38d8",
            clean_jobs=True,
        )

        self.assertEqual(notify_message["method"], "mining.notify")
        self.assertEqual(
            notify_message["params"][1],
            "010000000df259aac8b2b21edcf17e407f9207b74a7008b967000819fa42cb26",
        )
        self.assertEqual(canonical_prevhash, "00000001aa59f20d1eb2b2c8407ef1dcb707927fb908704a1908006726cb42fa")

    def test_notify_notification_rejects_invalid_prevhash(self):
        with self.assertRaisesRegex(ValueError, "prevhash must be 64-character hex"):
            stratum_protocol.notify_notification(
                job_id="job-123",
                prevhash="abcd",
                coinb1="aa",
                coinb2="bb",
                merkle_branch=[],
                version="20004000",
                nbits="1d0487ce",
                ntime="69ee38d8",
                clean_jobs=True,
            )

    def test_share_hash_threshold_summary_uses_canonical_hash_order(self):
        canonical_hash = bytes.fromhex(
            "00000001fb895a82973fca52938848908d6a6cb3c0dfb93995dc61020ced0a6b"
        )
        summary = stratum_ingress._build_share_hash_threshold_summary(
            share_hash=canonical_hash,
            block_target_int=int("0f" * 32, 16),
            share_target_int=int(canonical_hash.hex(), 16),
        )
        self.assertTrue(summary["meetsShareTarget"])

    def test_pepepow_share_target_uses_pool_diff1_baseline(self):
        self.assertEqual(
            stratum_ingress.STRATUM_DIFF1_TARGET,
            int(
                "0000ffff00000000000000000000000000000000000000000000000000000000",
                16,
            ),
        )

    def test_pepepow_share_target_from_representative_difficulties(self):
        cases = {
            0.1: "0009fff600000000000000000000000000000000000000000000000000000000",
            0.2: "0004fffb00000000000000000000000000000000000000000000000000000000",
            3.2: "00004fffb0000000000000000000000000000000000000000000000000000000",
        }

        for difficulty, expected_target in cases.items():
            with self.subTest(difficulty=difficulty):
                target = stratum_ingress._share_target_from_difficulty(difficulty)

                self.assertEqual(f"{target:064x}", expected_target)

    def test_share_hash_threshold_summary_keeps_pool_share_target_distinct(self):
        block_target_int = int("00ff" + "00" * 30, 16)
        share_target_int = int("000f" + "00" * 30, 16)
        share_hash = (share_target_int - 1).to_bytes(32, "big")

        summary = stratum_ingress._build_share_hash_threshold_summary(
            share_hash=share_hash,
            block_target_int=block_target_int,
            share_target_int=share_target_int,
        )

        self.assertNotEqual(summary["shareTargetUsed"], summary["blockTargetUsed"])
        self.assertEqual(summary["shareTargetUsed"], f"{share_target_int:064x}")
        self.assertEqual(summary["blockTargetUsed"], f"{block_target_int:064x}")
        self.assertTrue(summary["meetsShareTarget"])
        self.assertTrue(summary["meetsBlockTarget"])

    def test_assess_share_hash_uses_job_assigned_difficulty_for_previous_job(self):
        tmp_path = Path(tempfile.mkdtemp())
        config = self._make_config(tmp_path)
        service = StratumIngressService(config)
        state = stratum_ingress.new_connection_state()
        state.extranonce1 = "aabbccdd"
        state.current_difficulty = 2.0

        class _Job:
            source = "daemon-template"
            assigned_difficulty = 1.0
            target_context = {"target": "00" * 31 + "01"}
            authoritative_context = {}
            template_anchor = "anchor"
            version = "20000000"
            prevhash = "00" * 32
            nbits = "1d00ffff"
            ntime = "01020304"
            coinb1 = "01"
            coinb2 = "ff"
            merkle_branch = ()
            preimage_context = {"source": "template-derived"}

        # hash is below diff=1 target but above diff=2 target
        share_hash = (
            stratum_ingress._share_target_from_difficulty(1.0) - 1
        ).to_bytes(32, "big")
        self.assertGreater(
            int.from_bytes(share_hash, "big"),
            stratum_ingress._share_target_from_difficulty(2.0),
        )

        with mock.patch.object(
            stratum_ingress,
            "_build_share_header_preimage",
            return_value=stratum_ingress.ShareHeaderPreimage(
                status="preimage-ready",
                reject_reason=None,
                header=b"\x00" * 80,
            ),
        ), mock.patch.object(
            stratum_ingress,
            "_calculate_pepepow_share_hash",
            return_value=share_hash,
        ):
            assessment = service._assess_share_hash(
                ["wallet.rig", "job-1", "00000001", "01020304", "00000000"],
                state=state,
                cached_job=_Job(),
                target_context_check=stratum_ingress.TargetContextCheck(
                    status="candidate-possible",
                    reject_reason=None,
                    candidate_possible=True,
                ),
            )

        self.assertEqual(assessment.status, "share-hash-valid")
        self.assertEqual(assessment.diagnostic["shareDifficultyUsed"], 1.0)

    def test_daemon_template_share_hash_uses_pool_share_target_not_block_target(self):
        tmp_path = Path(tempfile.mkdtemp())
        config = self._make_config(tmp_path)
        service = StratumIngressService(config)
        state = stratum_ingress.new_connection_state()
        state.extranonce1 = "aabbccdd"
        state.current_difficulty = 51.2
        share_target_int = stratum_ingress._share_target_from_difficulty(51.2)
        self.assertIsNotNone(share_target_int)
        block_target_int = share_target_int // 4

        class _Job:
            source = "daemon-template"
            assigned_difficulty = 51.2
            target_context = {"target": f"{block_target_int:064x}"}
            authoritative_context = {}
            template_anchor = "anchor"
            version = "20000000"
            prevhash = "00" * 32
            nbits = "1d00ffff"
            ntime = "01020304"
            coinb1 = "01"
            coinb2 = "ff"
            merkle_branch = ()
            preimage_context = {"source": "template-derived"}

        self.assertNotEqual(share_target_int, block_target_int)
        share_hash = (share_target_int - 1).to_bytes(32, "big")

        with mock.patch.object(
            stratum_ingress,
            "_build_share_header_preimage",
            return_value=stratum_ingress.ShareHeaderPreimage(
                status="preimage-ready",
                reject_reason=None,
                header=b"\x00" * 80,
            ),
        ), mock.patch.object(
            stratum_ingress,
            "_calculate_pepepow_share_hash",
            return_value=share_hash,
        ):
            assessment = service._assess_share_hash(
                ["wallet.rig", "job-1", "00000001", "01020304", "00000000"],
                state=state,
                cached_job=_Job(),
                target_context_check=stratum_ingress.TargetContextCheck(
                    status="candidate-possible",
                    reject_reason=None,
                    candidate_possible=True,
                ),
            )

        self.assertEqual(assessment.status, "share-hash-valid")
        self.assertTrue(assessment.diagnostic["meetsShareTarget"])
        self.assertFalse(assessment.diagnostic["meetsBlockTarget"])
        self.assertEqual(
            assessment.diagnostic["shareTargetUsed"],
            f"{share_target_int:064x}",
        )
        self.assertEqual(
            assessment.diagnostic["blockTargetUsed"],
            f"{block_target_int:064x}",
        )

    def test_daemon_template_block_candidate_uses_block_target_separately(self):
        tmp_path = Path(tempfile.mkdtemp())
        config = self._make_config(tmp_path)
        service = StratumIngressService(config)
        state = stratum_ingress.new_connection_state()
        state.extranonce1 = "aabbccdd"

        class _Job:
            source = "daemon-template"
            assigned_difficulty = 32768.0
            target_context = {
                "target": "00000004248e0000000000000000000000000000000000000000000000000000"
            }
            authoritative_context = {}
            template_anchor = "anchor"
            job_id = "job-1"
            version = "20000000"
            prevhash = "00" * 32
            nbits = "1d00ffff"
            ntime = "01020304"
            coinb1 = "01"
            coinb2 = "ff"
            merkle_branch = ()
            preimage_context = {"source": "template-derived"}

        block_target_int = int(_Job.target_context["target"], 16)
        share_target_int = stratum_ingress._share_target_from_difficulty(
            _Job.assigned_difficulty
        )
        self.assertIsNotNone(share_target_int)
        self.assertLess(share_target_int, block_target_int)
        share_hash = (block_target_int - 1).to_bytes(32, "big")

        with mock.patch.object(
            stratum_ingress,
            "_build_share_header_preimage",
            return_value=stratum_ingress.ShareHeaderPreimage(
                status="preimage-ready",
                reject_reason=None,
                header=b"\x00" * 80,
            ),
        ), mock.patch.object(
            stratum_ingress,
            "_calculate_pepepow_share_hash",
            return_value=share_hash,
        ), mock.patch.object(
            service,
            "_append_candidate_evidence",
        ):
            assessment = service._assess_share_hash(
                ["wallet.rig", "job-1", "00000001", "01020304", "00000000"],
                state=state,
                cached_job=_Job(),
                target_context_check=stratum_ingress.TargetContextCheck(
                    status="candidate-possible",
                    reject_reason=None,
                    candidate_possible=True,
                ),
            )

        self.assertEqual(assessment.status, "block-candidate")
        self.assertFalse(assessment.diagnostic["meetsShareTarget"])
        self.assertTrue(assessment.diagnostic["meetsBlockTarget"])

    def test_candidate_followup_defaults(self):
        result = pool_core_daemon_rpc.candidate_followup_defaults()
        self.assertEqual(result["followupStatus"], "not-checked")
        self.assertIsNone(result["followupCheckedAt"])
        self.assertIsNone(result["followupObservedHeight"])
        self.assertIsNone(result["followupObservedBlockHash"])
        self.assertIsNone(result["followupNote"])

    def test_candidate_followup_check_found(self):
        result = pool_core_daemon_rpc.check_candidate_followup(
            "ab" * 32,
            rpc_client=FollowupFoundRpcClient(),
        )
        self.assertEqual(result["followupStatus"], "match-found")
        self.assertEqual(result["followupObservedHeight"], 123456)
        self.assertEqual(result["followupObservedBlockHash"], "ab" * 32)
        self.assertEqual(
            result["followupNote"], "candidate-block-hash-found-on-local-chain"
        )
        self.assertIsInstance(result["followupCheckedAt"], str)

    def test_candidate_followup_check_not_found(self):
        result = pool_core_daemon_rpc.check_candidate_followup(
            "cd" * 32,
            rpc_client=FollowupNotFoundRpcClient(),
        )
        self.assertEqual(result["followupStatus"], "no-match-found")
        self.assertIsNone(result["followupObservedHeight"])
        self.assertIsNone(result["followupObservedBlockHash"])
        self.assertEqual(
            result["followupNote"], "candidate-block-hash-not-found-on-local-chain"
        )

    def test_candidate_followup_check_error(self):
        result = pool_core_daemon_rpc.check_candidate_followup(
            "ef" * 32,
            rpc_client=FollowupErrorRpcClient(),
        )
        self.assertEqual(result["followupStatus"], "check-error")
        self.assertIsNone(result["followupObservedHeight"])
        self.assertIsNone(result["followupObservedBlockHash"])
        self.assertIn("connection refused", result["followupNote"])

    def test_daemon_rpc_http_json_error_surfaces_as_response_error(self):
        client = pool_core_daemon_rpc.DaemonRpcClient(
            rpc_url="http://127.0.0.1:8834",
            rpc_user="user",
            rpc_password="pass",
            timeout_seconds=5,
        )
        http_error = urllib.error.HTTPError(
            url="http://127.0.0.1:8834",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(
                b'{"result":null,"error":{"code":-5,"message":"Block not found"},"id":1}'
            ),
        )

        with mock.patch.object(
            pool_core_daemon_rpc.urllib.request,
            "urlopen",
            side_effect=http_error,
        ):
            with self.assertRaises(DaemonRpcResponseError) as ctx:
                client.get_block_header("ab" * 32)

        self.assertIn("Block not found", str(ctx.exception))

    def test_build_candidate_outcome_event_defaults_to_submitted(self):
        candidate_event = {
            "timestamp": "2026-04-18T06:30:00Z",
            "jobId": "job-0000000000000000",
            "candidateBlockHash": "aa" * 32,
            "candidatePrepStatus": "candidate-prepared-complete",
            "submitblockRealSubmitStatus": "submit-sent",
            "submitblockAttempted": True,
            "submitblockSent": True,
            "submitblockSubmittedAt": "2026-04-18T06:31:00Z",
        }

        payload = pool_core_daemon_rpc.build_candidate_outcome_event(candidate_event)

        self.assertEqual(payload["candidateOutcomeStatus"], "submitted")
        self.assertEqual(payload["followupStatus"], "not-checked")
        self.assertEqual(payload["candidateBlockHash"], "aa" * 32)
        self.assertEqual(payload["submitblockRealSubmitStatus"], "submit-sent")
        self.assertTrue(payload["submitblockAttempted"])
        self.assertTrue(payload["submitblockSent"])
        self.assertEqual(payload["submitblockSubmittedAt"], "2026-04-18T06:31:00Z")

    def test_build_candidate_outcome_event_maps_recorded_followup_states(self):
        candidate_event = {
            "timestamp": "2026-04-18T06:30:00Z",
            "jobId": "job-0000000000000000",
            "candidateBlockHash": "aa" * 32,
            "candidatePrepStatus": "candidate-prepared-complete",
            "submitblockRealSubmitStatus": "submit-sent",
        }
        expected_states = {
            "match-found": "chain-match-found",
            "no-match-found": "chain-match-not-found",
            "check-error": "check-error",
        }

        for followup_status, expected_outcome_status in expected_states.items():
            with self.subTest(followup_status=followup_status):
                payload = pool_core_daemon_rpc.build_candidate_outcome_event(
                    candidate_event,
                    {
                        "followupStatus": followup_status,
                        "followupCheckedAt": "2026-04-18T06:32:00Z",
                        "followupObservedHeight": 123456,
                        "followupObservedBlockHash": "bb" * 32,
                        "followupNote": "test-note",
                    },
                )

                self.assertEqual(
                    payload["candidateOutcomeStatus"], expected_outcome_status
                )
                self.assertEqual(payload["followupStatus"], followup_status)

    def test_extract_template_outputs_ignores_empty_object(self):
        outputs = template_jobs._extract_template_outputs(
            {
                "masternode": {},
                "foundation": [
                    {
                        "script": "76a9143ec00d0d0e9a538b564d0bae64e1076d7ddd286688ac",
                        "amount": 0,
                    }
                ],
            }
        )
        self.assertEqual(
            outputs,
            [
                {
                    "amount": 0,
                    "script": "76a9143ec00d0d0e9a538b564d0bae64e1076d7ddd286688ac",
                    "kind": "foundation",
                }
            ],
        )

    def test_append_candidate_followup_event_records_match_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            followup_path = tmp_path / "candidate-followup-events.jsonl"
            outcome_path = tmp_path / "candidate-outcome-events.jsonl"
            candidate_event = {
                "timestamp": "2026-04-18T06:30:00Z",
                "jobId": "job-0000000000000001",
                "templateAnchor": "anchor-1",
                "wallet": "wallet1",
                "worker": "rig01",
                "candidateBlockHash": "ab" * 32,
                "candidatePrepStatus": "candidate-prepared-complete",
                "submitblockRealSubmitStatus": "submit-sent",
            }
            followup = pool_core_daemon_rpc.check_candidate_followup(
                candidate_event["candidateBlockHash"],
                rpc_client=FollowupFoundRpcClient(),
            )
            payload = pool_core_daemon_rpc.append_candidate_followup_event(
                followup_path,
                candidate_event,
                followup,
                outcome_path=outcome_path,
            )

            self.assertEqual(payload["followupStatus"], "match-found")
            lines = followup_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            recorded = json.loads(lines[0])
            self.assertEqual(recorded["candidateBlockHash"], "ab" * 32)
            self.assertEqual(recorded["followupStatus"], "match-found")
            self.assertEqual(recorded["followupObservedHeight"], 123456)
            self.assertEqual(recorded["followupObservedBlockHash"], "ab" * 32)
            outcome_recorded = json.loads(
                outcome_path.read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(
                outcome_recorded["candidateOutcomeStatus"], "chain-match-found"
            )
            self.assertEqual(outcome_recorded["followupStatus"], "match-found")

    def test_append_candidate_followup_event_records_no_match_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            followup_path = tmp_path / "candidate-followup-events.jsonl"
            candidate_event = {
                "timestamp": "2026-04-18T06:30:00Z",
                "jobId": "job-0000000000000002",
                "candidateBlockHash": "cd" * 32,
                "candidatePrepStatus": "candidate-prepared-complete",
                "submitblockRealSubmitStatus": "submit-disabled-flag-off",
            }
            followup = pool_core_daemon_rpc.check_candidate_followup(
                candidate_event["candidateBlockHash"],
                rpc_client=FollowupNotFoundRpcClient(),
            )
            payload = pool_core_daemon_rpc.append_candidate_followup_event(
                followup_path,
                candidate_event,
                followup,
            )

            self.assertEqual(payload["followupStatus"], "no-match-found")
            recorded = json.loads(followup_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(recorded["followupStatus"], "no-match-found")
            self.assertIsNone(recorded["followupObservedHeight"])
            self.assertIsNone(recorded["followupObservedBlockHash"])
            self.assertEqual(
                recorded["followupNote"],
                "candidate-block-hash-not-found-on-local-chain",
            )

    def test_append_candidate_followup_event_records_check_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            followup_path = tmp_path / "candidate-followup-events.jsonl"
            candidate_event = {
                "timestamp": "2026-04-18T06:30:00Z",
                "jobId": "job-0000000000000003",
                "candidateBlockHash": "ef" * 32,
                "candidatePrepStatus": "candidate-prepared-complete",
                "submitblockRealSubmitStatus": "submit-error",
            }
            followup = pool_core_daemon_rpc.check_candidate_followup(
                candidate_event["candidateBlockHash"],
                rpc_client=FollowupErrorRpcClient(),
            )
            payload = pool_core_daemon_rpc.append_candidate_followup_event(
                followup_path,
                candidate_event,
                followup,
            )

            self.assertEqual(payload["followupStatus"], "check-error")
            recorded = json.loads(followup_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(recorded["followupStatus"], "check-error")
            self.assertIn("connection refused", recorded["followupNote"])

    async def test_authorize_pushes_synthetic_difficulty_and_notify(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=30.0,
                stratum_vardiff_initial_difficulty=0.001,
                stratum_vardiff_min_difficulty=0.001,
            )
            config = replace(config, hashrate_assumed_share_difficulty=0.05)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 1,
                        "method": "mining.subscribe",
                        "params": ["test-miner/1.0"],
                    },
                )
                subscriptions = subscribe_response["result"][0]
                self.assertEqual(
                    [entry[0] for entry in subscriptions],
                    [
                        "mining.set_difficulty",
                        "mining.notify",
                    ],
                )
                self.assertEqual(len({entry[1] for entry in subscriptions}), 1)
                self.assertEqual(subscribe_response["result"][2], 4)

                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": [
                                "PEPEPOW1KnownWalletAddress000000.rig01",
                                "x",
                            ],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                authorize_response = await self._read_json(reader)
                difficulty_message = await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertTrue(authorize_response["result"])
                self.assertEqual(difficulty_message["method"], "mining.set_difficulty")
                self.assertEqual(
                    difficulty_message["params"],
                    [65.536],
                )
                self.assertEqual(notify_message["method"], "mining.notify")
                self.assertEqual(len(notify_message["params"]), 9)
                self.assertTrue(notify_message["params"][8])
                issued_job = service._job_manager.get_job(notify_message["params"][0])
                self.assertIsNotNone(issued_job)
                self.assertEqual(
                    issued_job.assigned_difficulty,
                    config.stratum_vardiff_initial_difficulty,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "windowReplaySequenceFloor"
                        )
                        == 1
                    )
                )

                share_lines = config.activity_log_path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(share_lines), 1)
                share_event = json.loads(share_lines[0])
                self.assertEqual(
                    share_event["wallet"], "PEPEPOW1KnownWalletAddress000000"
                )
                self.assertEqual(share_event["worker"], "rig01")
                self.assertEqual(share_event["jobId"], notify_message["params"][0])
                self.assertEqual(
                    share_event["difficulty"],
                    config.stratum_vardiff_initial_difficulty,
                )
                self.assertEqual(share_event["jobStatus"], "current")
                self.assertTrue(share_event["syntheticWork"])
                self.assertFalse(share_event["blockchainVerified"])
                self.assertEqual(
                    share_event["shareValidationMode"], "structural-skeleton"
                )
                snapshot = self._load_json(config.activity_snapshot_output_path)
                active_sessions = snapshot["activeSessions"]
                self.assertEqual(len(active_sessions), 1)
                session = next(iter(active_sessions.values()))
                self.assertEqual(
                    session["effectiveShareDifficulty"],
                    config.stratum_vardiff_initial_difficulty,
                )
                self.assertEqual(session["minerWireDifficulty"], 65.536)
                self.assertEqual(session["difficultyScale"], 65536.0)

                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "windowReplaySequenceFloor"
                        )
                        == 1
                    )
                )
                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["syntheticJobMode"],
                    "synthetic-stratum-v1",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["shareValidationMode"],
                    "structural-skeleton",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["windowReplaySequenceFloor"],
                    1,
                )
                self.assertEqual(activity_snapshot["pool"]["activeMiners"], 1)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_authorize_starts_at_vardiff_initial_difficulty_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                stratum_vardiff_enabled=True,
                stratum_vardiff_initial_difficulty=0.1,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 1,
                        "method": "mining.subscribe",
                        "params": ["test-miner/1.0"],
                    },
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": [
                                "PEPEPOW1KnownWalletAddress000000.rig01",
                                "x",
                            ],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()
                with self.assertLogs("pepepow.stratum_ingress", level="INFO") as captured:
                    self.assertTrue((await self._read_json(reader))["result"])
                    difficulty_message = await self._read_json(reader)
                self.assertEqual(difficulty_message["method"], "mining.set_difficulty")
                self.assertEqual(difficulty_message["params"], [6553.6])
                combined_logs = "\n".join(captured.output)
                self.assertIn("Difficulty sent: session=", combined_logs)
                self.assertIn("remote=", combined_logs)
                self.assertIn("wallet=PEPEPOW1KnownWalletAddress000000", combined_logs)
                self.assertIn("worker=rig01", combined_logs)
                self.assertIn("effectiveShareDifficulty=0.1", combined_logs)
                self.assertIn("minerWireDifficulty=6553.6", combined_logs)
                self.assertIn("difficultyScale=65536.0", combined_logs)
                self.assertIn("reason=authorize-fixed", combined_logs)
                self.assertIn("vardiffEnabled=True", combined_logs)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    def test_vardiff_fast_share_session_retargets_upward(self):
        service = StratumIngressService(
            self._make_config(Path(tempfile.mkdtemp()), stratum_vardiff_enabled=True)
        )
        state = stratum_ingress.new_connection_state()
        state.authorized_wallet = "walletA"
        state.authorized_worker = "rigA"
        state.current_difficulty = 0.1
        stats = SessionStats()
        start = datetime(2026, 4, 22, tzinfo=timezone.utc)

        message = None
        with self.assertLogs("pepepow.stratum_ingress", level="INFO") as captured:
            for index, offset in enumerate(range(0, 65, 5), start=1):
                stats.accepted_share_count = index
                stats.first_share_at = start
                message = service._maybe_update_vardiff(
                    state=state,
                    session_stats=stats,
                    observed_at=start + timedelta(seconds=offset),
                    sample_for_vardiff=True,
                )

        self.assertEqual(state.current_difficulty, 0.2)
        self.assertEqual(message["method"], "mining.set_difficulty")
        self.assertEqual(message["params"], [13107.2])
        combined_logs = "\n".join(captured.output)
        self.assertIn("Vardiff retarget: session=", combined_logs)
        self.assertIn("Difficulty sent: session=", combined_logs)
        self.assertIn("remote=unknown", combined_logs)
        self.assertIn("wallet=walletA", combined_logs)
        self.assertIn("worker=rigA", combined_logs)
        self.assertIn("effectiveShareDifficulty=0.2", combined_logs)
        self.assertIn("minerWireDifficulty=13107.2", combined_logs)
        self.assertIn("reason=vardiff-retarget", combined_logs)
        self.assertIn("vardiffEnabled=True", combined_logs)

    def test_vardiff_slow_share_session_retargets_downward(self):
        service = StratumIngressService(
            self._make_config(Path(tempfile.mkdtemp()), stratum_vardiff_enabled=True)
        )
        state = stratum_ingress.new_connection_state()
        state.current_difficulty = 0.1
        stats = SessionStats()
        start = datetime(2026, 4, 22, tzinfo=timezone.utc)

        message = None
        for index, offset in enumerate((0, 30, 60, 90), start=1):
            stats.accepted_share_count = index
            stats.first_share_at = start
            message = service._maybe_update_vardiff(
                state=state,
                session_stats=stats,
                observed_at=start + timedelta(seconds=offset),
                sample_for_vardiff=True,
            )

        self.assertEqual(state.current_difficulty, 0.05)
        self.assertEqual(message["params"], [0.05])

    def test_vardiff_does_not_retarget_before_minimum_window_conditions(self):
        service = StratumIngressService(
            self._make_config(Path(tempfile.mkdtemp()), stratum_vardiff_enabled=True)
        )
        state = stratum_ingress.new_connection_state()
        state.current_difficulty = 0.1
        stats = SessionStats()
        start = datetime(2026, 4, 22, tzinfo=timezone.utc)

        for index, offset in enumerate((0, 5, 10, 15), start=1):
            stats.accepted_share_count = index
            stats.first_share_at = start
            message = service._maybe_update_vardiff(
                state=state,
                session_stats=stats,
                observed_at=start + timedelta(seconds=offset),
                sample_for_vardiff=True,
            )
            self.assertIsNone(message)

        self.assertEqual(state.current_difficulty, 0.1)

    def test_vardiff_low_difficulty_share_samples_can_retarget_upward(self):
        service = StratumIngressService(
            self._make_config(Path(tempfile.mkdtemp()), stratum_vardiff_enabled=True)
        )
        state = stratum_ingress.new_connection_state()
        state.current_difficulty = 0.1
        stats = SessionStats()
        start = datetime(2026, 4, 22, tzinfo=timezone.utc)

        message = None
        for offset in range(0, 65, 5):
            message = service._maybe_update_vardiff(
                state=state,
                session_stats=stats,
                observed_at=start + timedelta(seconds=offset),
                sample_for_vardiff=True,
            )

        self.assertEqual(stats.vardiff_sample_count, 13)
        self.assertEqual(state.current_difficulty, 0.2)
        self.assertEqual(message["params"], [13107.2])

    def test_vardiff_retarget_next_notify_carries_new_assigned_difficulty(self):
        service = StratumIngressService(
            self._make_config(Path(tempfile.mkdtemp()), stratum_vardiff_enabled=True)
        )
        state = stratum_ingress.new_connection_state()
        state.current_difficulty = 0.1
        stats = SessionStats()
        start = datetime(2026, 4, 22, tzinfo=timezone.utc)

        for offset in range(0, 65, 5):
            service._maybe_update_vardiff(
                state=state,
                session_stats=stats,
                observed_at=start + timedelta(seconds=offset),
                sample_for_vardiff=True,
            )

        self.assertEqual(state.current_difficulty, 0.2)
        notify_message = service._new_notify_message(state)
        job_id = notify_message["params"][0]
        issued_job = service._job_manager.get_job(job_id)
        self.assertIsNotNone(issued_job)
        self.assertEqual(issued_job.assigned_difficulty, 0.2)

    def test_submit_validation_uses_newly_issued_job_difficulty_after_vardiff(self):
        service = StratumIngressService(
            self._make_config(Path(tempfile.mkdtemp()), stratum_vardiff_enabled=True)
        )
        state = stratum_ingress.new_connection_state()
        state.extranonce1 = "aabbccdd"
        state.current_difficulty = 0.2
        notify_message = service._new_notify_message(state)
        job_id = notify_message["params"][0]
        cached_job = service._job_manager.get_job(job_id)
        self.assertIsNotNone(cached_job)
        target_context = dict(cached_job.target_context)
        target_context["target"] = "00" * 31 + "01"
        cached_job = replace(
            cached_job,
            source="daemon-template",
            target_context=target_context,
        )

        share_hash = (
            stratum_ingress._share_target_from_difficulty(0.2) - 1
        ).to_bytes(32, "big")

        with mock.patch.object(
            stratum_ingress,
            "_build_share_header_preimage",
            return_value=stratum_ingress.ShareHeaderPreimage(
                status="preimage-ready",
                reject_reason=None,
                header=b"\x00" * 80,
            ),
        ), mock.patch.object(
            stratum_ingress,
            "_calculate_pepepow_share_hash",
            return_value=share_hash,
        ):
            assessment = service._assess_share_hash(
                ["wallet.rig", job_id, "00000001", "01020304", "00000000"],
                state=state,
                cached_job=cached_job,
                target_context_check=stratum_ingress.TargetContextCheck(
                    status="candidate-possible",
                    reject_reason=None,
                    candidate_possible=True,
                ),
            )

        self.assertEqual(assessment.diagnostic["shareDifficultyUsed"], 0.2)
        self.assertTrue(assessment.diagnostic["meetsShareTarget"])

    def test_vardiff_sample_predicate_allows_only_clean_low_difficulty_shares(self):
        class _Job:
            pass

        clean_low_diff = SubmitAssessment(
            job_status="current",
            submit_job_id="job-1",
            cached_job=_Job(),
            accepted=False,
            reject_reason="low-difficulty-share",
            target_validation_status="context-valid",
            share_hash_validation_status="low-difficulty-share",
            share_hash_valid=False,
        )
        self.assertTrue(stratum_ingress._counts_as_vardiff_sample(clean_low_diff))

        excluded = [
            replace(clean_low_diff, job_status="malformed", reject_reason="malformed-submit"),
            replace(clean_low_diff, job_status="unknown", reject_reason="unknown-job"),
            replace(clean_low_diff, job_status="stale", reject_reason="stale-job"),
            replace(clean_low_diff, target_validation_status="context-mismatch"),
            replace(clean_low_diff, cached_job=None),
            replace(clean_low_diff, duplicate_submit=True),
        ]
        for assessment in excluded:
            with self.subTest(
                job_status=assessment.job_status,
                reject_reason=assessment.reject_reason,
                target_validation_status=assessment.target_validation_status,
            ):
                self.assertFalse(stratum_ingress._counts_as_vardiff_sample(assessment))

    async def test_real_submitblock_enabled_logs_startup_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                enable_real_submitblock=True,
            )
            service = StratumIngressService(config)
            with self.assertLogs("pepepow.stratum_ingress", level="WARNING") as captured:
                await service.start()
            try:
                self.assertTrue(
                    any(
                        "REAL submitblock ENABLED via PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true"
                        in entry
                        for entry in captured.output
                    )
                )
            finally:
                await service.stop()

    async def test_authorized_connection_receives_periodic_notify_refresh(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=1.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                authorize_response = await self._read_json(reader)
                first_notify = None
                for _ in range(2):
                    message = await self._read_json(reader)
                    if message.get("method") == "mining.notify":
                        first_notify = message
                self.assertTrue(authorize_response["result"])
                self.assertIsNotNone(first_notify)

                periodic_notify = await asyncio.wait_for(self._read_json(reader), timeout=2.5)
                self.assertEqual(periodic_notify["method"], "mining.notify")
                self.assertNotEqual(periodic_notify["params"][0], first_notify["params"][0])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_legacy_clean_jobs_encoding_honors_toggle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                stratum_notify_clean_jobs_legacy=True,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)  # authorize response
                await self._read_json(reader)  # set_difficulty
                notify_message = await self._read_json(reader)

                self.assertEqual(notify_message["method"], "mining.notify")
                # When legacy toggle is ON, clean_jobs (params[8]) should be 1, not True
                self.assertIsInstance(notify_message["params"][8], int)
                self.assertEqual(notify_message["params"][8], 1)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_daemon_template_mode_populates_job_cache_and_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "0" * 63 + "1"
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                self.assertEqual(notify_message["method"], "mining.notify")
                self.assertEqual(notify_message["params"][1], "11111111" * 8)
                self.assertNotEqual(
                    notify_message["params"][2], stratum_ingress.SYNTHETIC_COINB1
                )
                self.assertNotEqual(
                    notify_message["params"][3], stratum_ingress.SYNTHETIC_COINB2
                )
                self.assertEqual(len(notify_message["params"][4]), 1)
                self.assertEqual(notify_message["params"][6], "1c0ffff0")
                self.assertEqual(notify_message["params"][7], "661dbf80")

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertIsNone(submit_response["result"])
                self.assertEqual(
                    submit_response["error"],
                    [23, "Low difficulty share", None],
                )

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertFalse(share_event["accepted"])
                self.assertEqual(share_event["status"], "rejected")
                self.assertEqual(share_event["jobSource"], "daemon-template")
                self.assertFalse(share_event["syntheticWork"])
                self.assertIsNotNone(share_event["templateAnchor"])
                self.assertEqual(share_event["targetContext"]["bits"], "1c0ffff0")
                self.assertEqual(
                    share_event["preimageContext"]["source"], "template-derived"
                )
                self.assertEqual(
                    share_event["preimageContext"]["merkleBranchLength"], 1
                )
                self.assertEqual(
                    share_event["targetValidationStatus"], "context-valid"
                )
                self.assertFalse(share_event["candidatePossible"])
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "low-difficulty-share"
                )
                self.assertFalse(share_event["shareHashValid"])
                self.assertFalse(share_event["countsAsAcceptedShare"])
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["meetsShareTarget"]
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["meetsBlockTarget"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["blockTargetUsed"],
                    "0" * 63 + "1",
                )
                self.assertIsInstance(
                    share_event["shareHashDiagnostic"]["shareTargetUsed"], str
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["comparisonStage"],
                    "share-hash-compare",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["reasonCode"],
                    "low-difficulty-share",
                )
                self.assertIsInstance(
                    share_event["shareHashDiagnostic"]["localComputedHash"], str
                )
                local_hash = share_event["shareHashDiagnostic"]["localComputedHash"]
                reversed_local_hash = bytes.fromhex(local_hash)[::-1].hex()
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["localComputedHashReversed"],
                    reversed_local_hash,
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["localComputedHashOrder"],
                    "canonical-big-endian-target-compare",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["inputSummary"]["ntime"],
                    notify_message["params"][7],
                )
                # refinedReasonCode and related structural fields are only present for
                # structural mismatches (header80-mismatch). For low-difficulty-share,
                # we don't expect them.
                self.assertNotIn(
                    "refinedReasonCode", share_event["shareHashDiagnostic"]
                )
                self.assertNotIn(
                    "observedHeaderAvailable", share_event["shareHashDiagnostic"]
                )
                self.assertNotIn(
                    "header80ObservedHex", share_event["shareHashDiagnostic"]
                )
                self.assertNotIn(
                    "header80ExpectedHex", share_event["shareHashDiagnostic"]
                )
                self.assertIsInstance(
                    share_event["shareHashDiagnostic"]["localComputedHash"], str
                )
                self.assertNotIn(
                    "refinedMerkleReasonCode", share_event["shareHashDiagnostic"]
                )
                self.assertNotIn(
                    "merkleRootExpected", share_event["shareHashDiagnostic"]
                )
                # No heavy structural probe is expected for simple low-difficulty shares
                self.assertEqual(len(self._read_share_hash_probe_events(config)), 0)
                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["submitShareHashValidationCounts"][
                        "low-difficulty-share"
                    ],
                    1,
                )
                self.assertEqual(
                    activity_snapshot["jobs"]["active"][0]["preimageContext"][
                        "source"
                    ],
                    "template-derived",
                )
                await self._wait_for(
                    lambda: self._load_json(config.activity_snapshot_output_path)
                    .get("miners", {})
                    .get("PEPEPOW1KnownWalletAddress000000", {})
                    .get("summary", {})
                    .get("rejectedShares")
                    == 1
                )
                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                wallet_summary = activity_snapshot["miners"][
                    "PEPEPOW1KnownWalletAddress000000"
                ]["summary"]
                self.assertEqual(wallet_summary["acceptedShares"], 0)
                self.assertEqual(wallet_summary["rejectedShares"], 1)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    def test_daemon_template_notify_context_matches_submit_time_reconstruction(self):
        raw_template = SuccessfulTemplateRpcClient().get_block_template()
        fetched_at = stratum_ingress.utc_now()
        snapshot = template_jobs._parse_block_template(
            raw_template,
            fetched_at=fetched_at,
        )
        job = template_jobs.JobRecord(
            job_id="job-0000000000000001",
            template_anchor=snapshot.template_anchor,
            assigned_difficulty=1e-08,
            target_context=snapshot.target_context,
            created_at=fetched_at,
            expires_at=fetched_at,
            stale_basis="test",
            source="daemon-template",
            prevhash=snapshot.prevhash,
            version=snapshot.version,
            nbits=snapshot.nbits,
            ntime=snapshot.ntime,
            coinb1=snapshot.coinb1,
            coinb2=snapshot.coinb2,
            merkle_branch=snapshot.merkle_branch,
            preimage_context=snapshot.preimage_context,
            authoritative_context=snapshot.authoritative_context,
        )

        extranonce1 = "aabbccdd"
        extranonce2 = "00000001"
        nonce = "11223344"
        preimage = stratum_ingress._build_share_header_preimage(
            job,
            extranonce1=extranonce1,
            extranonce2=extranonce2,
            ntime=job.ntime,
            nonce=nonce,
        )

        self.assertEqual(preimage.status, "preimage-ready")
        assert preimage.header is not None
        coinbase_hex = f"{job.coinb1}{extranonce1}{extranonce2}{job.coinb2}"
        coinbase_hash = stratum_ingress._double_sha256(bytes.fromhex(coinbase_hex))
        self.assertEqual(
            preimage.header[36:68],
            stratum_ingress._apply_merkle_branch(coinbase_hash, job.merkle_branch),
        )

        authoritative_reference = (
            stratum_ingress._build_independent_authoritative_header80_reference(
                job,
                extranonce1_hex=extranonce1,
                extranonce2_hex=extranonce2,
                ntime_hex=job.ntime,
                nonce_hex=nonce,
            )
        )
        self.assertIsNotNone(authoritative_reference)
        assert authoritative_reference is not None
        self.assertEqual(preimage.header.hex(), authoritative_reference["header80"].hex())
        self.assertEqual(
            stratum_ingress._calculate_pepepow_share_hash(preimage.header).hex(),
            authoritative_reference["shareHash"],
        )

    async def test_daemon_template_share_event_exports_resolved_target_validation_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "0" * 63 + "1"
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertEqual(share_event["targetValidationStatus"], "context-valid")
                self.assertFalse(share_event["candidatePossible"])
                self.assertFalse(share_event["shareHashDiagnostic"]["meetsBlockTarget"])
                self.assertEqual(
                    share_event["candidatePossible"],
                    share_event["shareHashDiagnostic"]["meetsBlockTarget"],
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_share_hash_valid_is_classified_without_rejection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            rpc_client = SuccessfulTemplateRpcClient()
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=rpc_client,
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "f" * 64
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertTrue(share_event["accepted"])
                self.assertEqual(share_event["status"], "accepted")
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "block-candidate"
                )
                self.assertTrue(share_event["shareHashValid"])
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["meetsShareTarget"]
                )
                self.assertTrue(
                    share_event["shareHashDiagnostic"]["meetsBlockTarget"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["candidatePrepStatus"],
                    "candidate-prepared-complete",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["localComputedHashOrder"],
                    "canonical-big-endian-target-compare",
                )
                self.assertIsInstance(
                    share_event["shareHashDiagnostic"]["shareTargetUsed"], str
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["localComputedHashReversed"],
                    bytes.fromhex(
                        share_event["shareHashDiagnostic"]["localComputedHash"]
                    )[::-1].hex(),
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["blockTargetUsed"],
                    "f" * 64,
                )
                self.assertIsInstance(
                    share_event["shareHashDiagnostic"]["candidateArtifact"][
                        "candidateBlockHex"
                    ],
                    str,
                )
                self.assertTrue(
                    share_event["shareHashDiagnostic"]["candidateArtifact"][
                        "completeEnoughForFutureSubmitblock"
                    ]
                )
                self.assertTrue(
                    share_event["shareHashDiagnostic"]["submitblockDryRunReady"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockDryRunStatus"],
                    "dry-run-prepared-complete",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockRpcMethod"],
                    "submitblock",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockPayloadHex"],
                    share_event["shareHashDiagnostic"]["candidateArtifact"][
                        "candidateBlockHex"
                    ],
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockPayloadHash"],
                    share_event["shareHashDiagnostic"]["candidateArtifact"][
                        "candidateBlockHash"
                    ],
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockPayloadBytes"],
                    len(
                        bytes.fromhex(
                            share_event["shareHashDiagnostic"]["candidateArtifact"][
                                "candidateBlockHex"
                            ]
                        )
                    ),
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockRpcParams"],
                    [
                        share_event["shareHashDiagnostic"]["candidateArtifact"][
                            "candidateBlockHex"
                        ]
                    ],
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["missingData"],
                    [],
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["submitblockAttempted"]
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["submitblockSent"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockRealSubmitStatus"],
                    "submit-disabled-flag-off",
                )
                self.assertIsNone(
                    share_event["shareHashDiagnostic"]["submitblockSubmittedAt"]
                )
                self.assertIsNone(
                    share_event["shareHashDiagnostic"]["submitblockDaemonResult"]
                )
                self.assertIsNone(
                    share_event["shareHashDiagnostic"]["submitblockException"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["candidateArtifact"][
                        "nonCoinbaseTransactionCount"
                    ],
                    1,
                )
                self.assertEqual(rpc_client.submitblock_calls, [])
                await self._wait_for(
                    lambda: len(self._read_candidate_events(config)) == 1
                )
                candidate_event = json.loads(self._read_candidate_events(config)[0])
                self.assertEqual(candidate_event["jobId"], job_id)
                self.assertEqual(
                    candidate_event["wallet"], "PEPEPOW1KnownWalletAddress000000"
                )
                self.assertEqual(candidate_event["worker"], "rig01")
                self.assertEqual(
                    candidate_event["candidatePrepStatus"],
                    "candidate-prepared-complete",
                )
                self.assertTrue(candidate_event["submitblockDryRunReady"])
                self.assertEqual(
                    candidate_event["submitblockDryRunStatus"],
                    "dry-run-prepared-complete",
                )
                self.assertFalse(candidate_event["realSubmitblockEnabled"])
                self.assertFalse(candidate_event["submitblockAttempted"])
                self.assertFalse(candidate_event["submitblockSent"])
                self.assertEqual(
                    candidate_event["submitblockRealSubmitStatus"],
                    "submit-disabled-flag-off",
                )
                self.assertEqual(
                    candidate_event["submitblockPayloadHash"],
                    share_event["shareHashDiagnostic"]["submitblockPayloadHash"],
                )
                self.assertEqual(
                    candidate_event["submitblockPayloadBytes"],
                    share_event["shareHashDiagnostic"]["submitblockPayloadBytes"],
                )
                self.assertEqual(candidate_event["followupStatus"], "not-checked")
                self.assertIsNone(candidate_event["followupCheckedAt"])
                self.assertIsNone(candidate_event["followupObservedHeight"])
                self.assertIsNone(candidate_event["followupObservedBlockHash"])
                self.assertIsNone(candidate_event["followupNote"])
                await self._wait_for(
                    lambda: len(self._read_candidate_outcome_events(config)) == 1
                )
                candidate_outcome_event = json.loads(
                    self._read_candidate_outcome_events(config)[0]
                )
                self.assertEqual(
                    candidate_outcome_event["candidateBlockHash"],
                    candidate_event["candidateBlockHash"],
                )
                self.assertEqual(
                    candidate_outcome_event["submitblockRealSubmitStatus"],
                    "submit-disabled-flag-off",
                )
                self.assertEqual(
                    candidate_outcome_event["candidateOutcomeStatus"],
                    "submitted",
                )
                self.assertEqual(
                    candidate_outcome_event["followupStatus"],
                    "not-checked",
                )
                await self._wait_for(
                    lambda: self._load_json(config.activity_snapshot_output_path)["meta"].get(
                        "realSubmitblockLastStatus"
                    )
                    == "submit-disabled-flag-off"
                )
                snapshot_meta = self._load_json(config.activity_snapshot_output_path)["meta"]
                self.assertEqual(snapshot_meta["submitHashValidCount"], 1)
                self.assertEqual(snapshot_meta["submitHashInvalidCount"], 0)
                self.assertFalse(snapshot_meta["realSubmitblockEnabled"])
                self.assertEqual(snapshot_meta["realSubmitblockSendBudget"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockSendBudgetRemaining"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockAttemptCount"], 0)
                self.assertEqual(snapshot_meta["realSubmitblockSentCount"], 0)
                self.assertEqual(
                    snapshot_meta["realSubmitblockLastStatus"],
                    "submit-disabled-flag-off",
                )
                await self._wait_for(
                    lambda: self._load_json(config.activity_snapshot_output_path)
                    .get("miners", {})
                    .get("PEPEPOW1KnownWalletAddress000000", {})
                    .get("summary", {})
                    .get("acceptedShares")
                    == 1
                )
                wallet_summary = self._load_json(config.activity_snapshot_output_path)[
                    "miners"
                ]["PEPEPOW1KnownWalletAddress000000"]["summary"]
                self.assertEqual(wallet_summary["acceptedShares"], 1)
                self.assertEqual(wallet_summary["rejectedShares"], 0)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_real_submit_enabled_calls_submitblock_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            rpc_client = SuccessfulTemplateRpcClient(
                allow_submitblock=True,
                submitblock_result="inconclusive",
            )
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
                enable_real_submitblock=True,
            )
            service = StratumIngressService(
                config,
                rpc_client=rpc_client,
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "f" * 64
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                diag = share_event["shareHashDiagnostic"]
                self.assertEqual(
                    diag["candidatePrepStatus"],
                    "candidate-prepared-complete",
                )
                self.assertTrue(diag["submitblockDryRunReady"])
                self.assertTrue(diag["submitblockAttempted"])
                self.assertTrue(diag["submitblockSent"])
                self.assertEqual(diag["submitblockRealSubmitStatus"], "submit-sent")
                self.assertEqual(diag["submitblockRpcMethod"], "submitblock")
                self.assertEqual(diag["submitblockDaemonResult"], "inconclusive")
                self.assertIsInstance(diag["submitblockSubmittedAt"], str)
                self.assertEqual(
                    rpc_client.submitblock_calls,
                    [(diag["candidateArtifact"]["candidateBlockHex"],)],
                )
                await self._wait_for(
                    lambda: len(self._read_candidate_events(config)) == 1
                )
                candidate_event = json.loads(self._read_candidate_events(config)[0])
                self.assertTrue(candidate_event["realSubmitblockEnabled"])
                self.assertTrue(candidate_event["submitblockAttempted"])
                self.assertTrue(candidate_event["submitblockSent"])
                self.assertEqual(
                    candidate_event["submitblockRealSubmitStatus"], "submit-sent"
                )
                self.assertEqual(
                    candidate_event["submitblockDaemonResult"], "inconclusive"
                )
                self.assertEqual(
                    candidate_event["submitblockPayloadHash"],
                    diag["submitblockPayloadHash"],
                )
                await self._wait_for(
                    lambda: self._load_json(config.activity_snapshot_output_path)["meta"].get(
                        "realSubmitblockSentCount"
                    )
                    == 1
                )
                snapshot_meta = self._load_json(config.activity_snapshot_output_path)["meta"]
                self.assertTrue(snapshot_meta["realSubmitblockEnabled"])
                self.assertEqual(snapshot_meta["realSubmitblockSendBudget"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockSendBudgetRemaining"], 0)
                self.assertEqual(snapshot_meta["realSubmitblockAttemptCount"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockSentCount"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockErrorCount"], 0)
                self.assertEqual(
                    snapshot_meta["realSubmitblockLastStatus"],
                    "submit-sent",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_real_submit_enabled_one_shot_budget_stops_second_send(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            rpc_client = SuccessfulTemplateRpcClient(
                allow_submitblock=True,
                submitblock_result="first-send-ok",
            )
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
                enable_real_submitblock=True,
                real_submitblock_max_sends=1,
            )
            service = StratumIngressService(
                config,
                rpc_client=rpc_client,
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "f" * 64
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                first_submit = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                            extranonce2="00000001",
                            nonce="00000001",
                        ),
                    },
                )
                self.assertTrue(first_submit["result"])

                second_submit = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 4,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                            extranonce2="00000002",
                            nonce="00000002",
                        ),
                    },
                )
                self.assertTrue(second_submit["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 2
                )
                share_events = [
                    json.loads(line)
                    for line in self._read_share_events(config.activity_log_path)
                ]
                first_diag = share_events[0]["shareHashDiagnostic"]
                second_diag = share_events[1]["shareHashDiagnostic"]
                self.assertEqual(first_diag["submitblockRealSubmitStatus"], "submit-sent")
                self.assertEqual(
                    second_diag["submitblockRealSubmitStatus"],
                    "submit-skipped-send-budget-exhausted",
                )
                self.assertFalse(second_diag["submitblockAttempted"])
                self.assertFalse(second_diag["submitblockSent"])
                self.assertEqual(len(rpc_client.submitblock_calls), 1)

                await self._wait_for(
                    lambda: self._load_json(config.activity_snapshot_output_path)["meta"].get(
                        "realSubmitblockLastStatus"
                    )
                    == "submit-skipped-send-budget-exhausted"
                )
                snapshot_meta = self._load_json(config.activity_snapshot_output_path)["meta"]
                self.assertEqual(snapshot_meta["realSubmitblockSendBudget"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockSendBudgetRemaining"], 0)
                self.assertEqual(snapshot_meta["realSubmitblockAttemptCount"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockSentCount"], 1)
                self.assertEqual(
                    snapshot_meta["realSubmitblockLastStatus"],
                    "submit-skipped-send-budget-exhausted",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_real_submit_enabled_records_submit_error_evidence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            rpc_client = ErroringSubmitblockRpcClient(allow_submitblock=True)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
                enable_real_submitblock=True,
            )
            service = StratumIngressService(
                config,
                rpc_client=rpc_client,
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "f" * 64
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                diag = share_event["shareHashDiagnostic"]
                self.assertTrue(diag["submitblockAttempted"])
                self.assertFalse(diag["submitblockSent"])
                self.assertEqual(diag["submitblockRealSubmitStatus"], "submit-error")
                self.assertEqual(diag["submitblockException"], "submitblock failed")
                self.assertEqual(len(rpc_client.submitblock_calls), 1)

                await self._wait_for(
                    lambda: len(self._read_candidate_events(config)) == 1
                )
                candidate_event = json.loads(self._read_candidate_events(config)[0])
                self.assertTrue(candidate_event["submitblockAttempted"])
                self.assertFalse(candidate_event["submitblockSent"])
                self.assertEqual(
                    candidate_event["submitblockRealSubmitStatus"], "submit-error"
                )
                self.assertEqual(
                    candidate_event["submitblockException"], "submitblock failed"
                )
                self.assertEqual(
                    candidate_event["submitblockPayloadHash"],
                    diag["submitblockPayloadHash"],
                )

                await self._wait_for(
                    lambda: self._load_json(config.activity_snapshot_output_path)["meta"].get(
                        "realSubmitblockErrorCount"
                    )
                    == 1
                )
                snapshot_meta = self._load_json(config.activity_snapshot_output_path)["meta"]
                self.assertEqual(snapshot_meta["realSubmitblockAttemptCount"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockSentCount"], 0)
                self.assertEqual(snapshot_meta["realSubmitblockErrorCount"], 1)
                self.assertEqual(snapshot_meta["realSubmitblockLastStatus"], "submit-error")
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_real_submit_enabled_skips_incomplete_candidate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            rpc_client = PartialTemplateRpcClient()
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
                enable_real_submitblock=True,
            )
            service = StratumIngressService(
                config,
                rpc_client=rpc_client,
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "f" * 64
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                diag = share_event["shareHashDiagnostic"]
                self.assertEqual(
                    diag["candidatePrepStatus"],
                    "candidate-prepared-partial",
                )
                self.assertFalse(diag["submitblockDryRunReady"])
                self.assertEqual(
                    diag["submitblockDryRunStatus"],
                    "dry-run-prepared-partial",
                )
                self.assertFalse(diag["submitblockAttempted"])
                self.assertFalse(diag["submitblockSent"])
                self.assertEqual(
                    diag["submitblockRealSubmitStatus"],
                    "submit-skipped-incomplete-candidate",
                )
                self.assertIn("non-coinbase-transaction-data", diag["missingData"])
                self.assertEqual(rpc_client.submitblock_calls, [])
                await self._wait_for(
                    lambda: len(self._read_candidate_events(config)) == 1
                )
                candidate_event = json.loads(self._read_candidate_events(config)[0])
                self.assertEqual(
                    candidate_event["candidatePrepStatus"],
                    "candidate-prepared-partial",
                )
                self.assertFalse(candidate_event["submitblockDryRunReady"])
                self.assertFalse(candidate_event["submitblockAttempted"])
                self.assertFalse(candidate_event["submitblockSent"])
                self.assertEqual(
                    candidate_event["submitblockRealSubmitStatus"],
                    "submit-skipped-incomplete-candidate",
                )
                self.assertIn(
                    "non-coinbase-transaction-data", candidate_event["missingData"]
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_daemon_template_failure_falls_back_without_breaking_submit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=FailingTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "error"
                    )
                )

                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertEqual(notify_message["method"], "mining.notify")
                self.assertEqual(notify_message["params"][1], "0" * 64)

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertEqual(share_event["jobSource"], "synthetic")
                self.assertTrue(share_event["syntheticWork"])

                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["templateModeEffective"],
                    "daemon-template-fallback-synthetic",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateDaemonRpcStatus"],
                    "unreachable",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateFetchStatus"],
                    "error",
                )
                self.assertGreaterEqual(activity_snapshot["meta"]["activeJobCount"], 1)
                self.assertEqual(
                    activity_snapshot["jobs"]["active"][0]["source"],
                    "synthetic",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_daemon_template_share_hash_uses_pool_difficulty_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = replace(
                self._make_config(
                    tmp_path,
                    template_mode="daemon-template",
                    template_fetch_interval_seconds=5.0,
                    stratum_vardiff_initial_difficulty=0.001,
                    stratum_vardiff_min_difficulty=0.001,
                ),
                hashrate_assumed_share_difficulty=0.00000001,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                difficulty_message = await self._read_json(reader)
                notify_message = await self._read_json(reader)
                self.assertEqual(difficulty_message["method"], "mining.set_difficulty")
                self.assertEqual(difficulty_message["params"], [0.001])

                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "0" * 63 + "1"
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )
                extranonce1 = subscribe_response["result"][1]
                extranonce2 = "00000001"
                share_target_int = stratum_ingress._share_target_from_difficulty(
                    difficulty_message["params"][0]
                )
                self.assertIsNotNone(share_target_int)
                submit_nonce = None
                for nonce_int in range(10000):
                    candidate_nonce = f"{nonce_int:08x}"
                    preimage = stratum_ingress._build_share_header_preimage(
                        cached_job,
                        extranonce1=extranonce1,
                        extranonce2=extranonce2,
                        ntime=notify_message["params"][7],
                        nonce=candidate_nonce,
                    )
                    self.assertEqual(preimage.status, "preimage-ready")
                    assert preimage.header is not None
                    share_hash = stratum_ingress._calculate_pepepow_share_hash(
                        preimage.header
                    )
                    if (
                        int.from_bytes(share_hash, byteorder="big", signed=False)
                        <= share_target_int
                    ):
                        submit_nonce = candidate_nonce
                        break
                self.assertIsNotNone(submit_nonce)

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                            extranonce2=extranonce2,
                            nonce=submit_nonce,
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "share-hash-valid"
                )
                self.assertTrue(share_event["shareHashValid"])
                self.assertTrue(
                    share_event["shareHashDiagnostic"]["meetsShareTarget"]
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["meetsBlockTarget"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["candidatePrepStatus"],
                    "candidate-not-triggered",
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["submitblockDryRunReady"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockDryRunStatus"],
                    "dry-run-not-triggered",
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["submitblockAttempted"]
                )
                self.assertFalse(
                    share_event["shareHashDiagnostic"]["submitblockSent"]
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["submitblockRealSubmitStatus"],
                    "submit-not-triggered",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["blockTargetUsed"],
                    "0" * 63 + "1",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["shareHashComparisonMode"],
                    "effective-pool-share-target-and-block-target",
                )
                local_hash = share_event["shareHashDiagnostic"]["localComputedHash"]
                reversed_local_hash = bytes.fromhex(local_hash)[::-1].hex()
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["localComputedHashReversed"],
                    reversed_local_hash,
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["localComputedHashOrder"],
                    "canonical-big-endian-target-compare",
                )
                self.assertFalse(self._candidate_event_log_path(config).exists())
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_activity_snapshot_uses_estimation_difficulty_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = replace(
                self._make_config(tmp_path),
                hashrate_assumed_share_difficulty=1e-08,
                estimated_hashrate_assumed_share_difficulty=1e-11,
            )
            service = StratumIngressService(config)
            self.assertEqual(service._synthetic_difficulty(), 1e-08)
            self.assertEqual(service._engine.assumed_share_difficulty, 1e-11)

    async def test_notify_debug_capture_default_limit_zero_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
                notify_debug_capture_limit=0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                self.assertEqual(notify_message["method"], "mining.notify")

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            extranonce2="00000001",
                            nonce="00000000",
                        ),
                    },
                )
                self.assertIn("result", submit_response)
                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                self.assertFalse(self._notify_debug_capture_path(config).exists())
                self.assertEqual(
                    subscribe_response["result"][2],
                    4,
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_notify_debug_capture_is_bounded_and_matches_wire_notify(self):
        class NotifyCaptureTemplateRpcClient(SuccessfulTemplateRpcClient):
            def get_block_template(self) -> dict[str, object]:
                payload = super().get_block_template()
                payload["previousblockhash"] = (
                    "00000001aa59f20d1eb2b2c8407ef1dcb707927fb908704a1908006726cb42fa"
                )
                return payload

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
                notify_debug_capture_limit=1,
            )
            service = StratumIngressService(
                config,
                rpc_client=NotifyCaptureTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                difficulty_message = await self._read_json(reader)
                notify_message = await self._read_json(reader)
                self.assertEqual(difficulty_message["method"], "mining.set_difficulty")
                self.assertEqual(notify_message["method"], "mining.notify")
                await self._wait_for(
                    lambda: len(self._read_notify_debug_capture_events(config)) == 1
                )
                capture_record = json.loads(
                    self._read_notify_debug_capture_events(config)[0]
                )
                self.assertEqual(capture_record["event"], "notify")
                self.assertEqual(capture_record["notifyParams"], notify_message["params"])
                self.assertEqual(capture_record["jobId"], notify_message["params"][0])
                self.assertEqual(
                    capture_record["canonicalPrevhash"],
                    "00000001aa59f20d1eb2b2c8407ef1dcb707927fb908704a1908006726cb42fa",
                )
                self.assertEqual(
                    capture_record["wireNotifyPrevhash"],
                    "010000000df259aac8b2b21edcf17e407f9207b74a7008b967000819fa42cb26",
                )

                first_submit = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            extranonce2="00000001",
                            nonce="00000000",
                        ),
                    },
                )
                second_submit = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 4,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            extranonce2="00000001",
                            nonce="00000001",
                        ),
                    },
                )
                self.assertIsNotNone(first_submit)
                self.assertIsNotNone(second_submit)

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 2
                )
                self.assertEqual(
                    len(self._read_notify_debug_capture_events(config)),
                    1,
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_missing_target_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context={},
                )

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(
                    share_event["rejectReason"], "target-context-missing"
                )
                self.assertEqual(
                    share_event["targetValidationStatus"], "target-context-missing"
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_mismatched_target_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            "00000000",
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(
                    share_event["rejectReason"], "target-context-mismatch"
                )
                self.assertEqual(
                    share_event["targetValidationStatus"], "target-context-mismatch"
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_preimage_missing_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    prevhash=None,
                )

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["rejectReason"], "preimage-missing")
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "preimage-missing"
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["comparisonStage"],
                    "template-context",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["reasonCode"],
                    "template-context-mismatch",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_preimage_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                issued_ntime = int(notify_message["params"][7], 16)
                mismatched_ntime = f"{issued_ntime + 1:08x}"

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            mismatched_ntime,
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["rejectReason"], "preimage-mismatch")
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "preimage-mismatch"
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["comparisonStage"],
                    "ntime-normalization",
                )
                self.assertEqual(
                    share_event["shareHashDiagnostic"]["reasonCode"],
                    "ntime-normalization-mismatch",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_extranonce_subscribe_is_a_noop_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                extranonce_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 2, "method": "mining.extranonce.subscribe", "params": []},
                )
                self.assertTrue(extranonce_response["result"])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_previous_job_id_is_tagged_previous(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=1.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                first_notify = await self._read_json(reader)
                second_notify = await asyncio.wait_for(self._read_json(reader), timeout=2.5)

                self.assertEqual(first_notify["method"], "mining.notify")
                self.assertEqual(second_notify["method"], "mining.notify")

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            first_notify["params"][0],
                            first_notify["params"][7],
                        ),
                    },
                )
                self.assertTrue(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "previous")
                self.assertEqual(share_event["jobId"], first_notify["params"][0])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_malformed_params_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "", "extra"],
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "malformed")
                self.assertEqual(share_event["status"], "rejected")
                self.assertEqual(share_event["rejectReason"], "malformed-submit")
                self.assertIsNone(share_event["jobId"])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_wrong_extranonce2_width_is_rejected_as_malformed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                subscribe_response = None
                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertEqual(subscribe_response["result"][2], 4)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            extranonce2="000001",
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "malformed")
                self.assertEqual(share_event["rejectReason"], "malformed-submit")
                self.assertEqual(
                    share_event["rejectDetail"],
                    "submit extranonce2 must be 8-char hex",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_non_hex_nonce_is_rejected_as_malformed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            nonce="zzzzzzzz",
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "malformed")
                self.assertEqual(share_event["rejectReason"], "malformed-submit")
                self.assertEqual(
                    share_event["rejectDetail"],
                    "submit nonce must be 8-char hex",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_unknown_job_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": [
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            "job-not-known-here",
                            "00000000",
                            "661dc000",
                            "00000000",
                        ],
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "unknown")
                self.assertEqual(share_event["status"], "rejected")
                self.assertEqual(share_event["rejectReason"], "unknown-job")
                self.assertEqual(share_event["jobId"], "job-not-known-here")
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_restart_like_unknown_job_id_gets_backlog_detail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertEqual(notify_message["method"], "mining.notify")

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": [
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            "job-0000000000000010",
                            "00000000",
                            "661dc000",
                            "00000000",
                        ],
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "unknown")
                self.assertEqual(share_event["rejectReason"], "unknown-job")
                self.assertEqual(
                    share_event["rejectDetail"],
                    "job id not present in active or retired cache; possible restart backlog from prior ingress process",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_stale_job_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=30.0,
                template_job_ttl_seconds=1,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                await asyncio.sleep(1.2)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "stale")
                self.assertEqual(share_event["rejectReason"], "stale-job")
                self.assertEqual(share_event["status"], "rejected")
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_duplicate_submit_is_rejected_within_bounded_window(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                submit_params = self._submit_params(
                    "PEPEPOW1KnownWalletAddress000000.rig01",
                    notify_message["params"][0],
                    notify_message["params"][7],
                )
                first_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": submit_params,
                    },
                )
                duplicate_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 4,
                        "method": "mining.submit",
                        "params": submit_params,
                    },
                )

                self.assertTrue(first_response["result"])
                self.assertFalse(duplicate_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 2
                )
                share_events = [
                    json.loads(line)
                    for line in self._read_share_events(config.activity_log_path)
                ]
                self.assertEqual(share_events[0]["status"], "accepted")
                self.assertEqual(share_events[1]["status"], "rejected")
                self.assertEqual(
                    share_events[1]["rejectReason"], "duplicate-submit"
                )
                self.assertTrue(share_events[1]["duplicateSubmit"])
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "submitHashInvalidCount"
                        )
                        == 1
                    )
                )
                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["submitHashValidCount"], 1
                )
                self.assertEqual(
                    activity_snapshot["meta"]["submitHashInvalidCount"], 1
                )
                self.assertEqual(
                    activity_snapshot["meta"]["submitRejectReasonCounts"][
                        "duplicate-submit"
                    ],
                    1,
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_repeated_unknown_reject_logs_are_summarized(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            session_stats = SessionStats()
            assessment = SubmitAssessment(
                job_status="unknown",
                submit_job_id="job-0000000000000010",
                cached_job=None,
                accepted=False,
                reject_reason="unknown-job",
                detail="job id not present in active or retired cache; possible restart backlog from prior ingress process",
            )

            with self.assertLogs("pepepow.stratum_ingress", level="WARNING") as captured:
                service._log_submit_outcome(
                    session_id="session-1",
                    remote_address="127.0.0.1:9999",
                    share_count=1,
                    submit_job_id=assessment.submit_job_id,
                    current_job_id="job-0000000000000003",
                    previous_job_id="job-0000000000000002",
                    assessment=assessment,
                    session_stats=session_stats,
                )
                service._log_submit_outcome(
                    session_id="session-1",
                    remote_address="127.0.0.1:9999",
                    share_count=2,
                    submit_job_id=assessment.submit_job_id,
                    current_job_id="job-0000000000000003",
                    previous_job_id="job-0000000000000002",
                    assessment=assessment,
                    session_stats=session_stats,
                )
                service._flush_reject_log_summary(
                    session_id="session-1",
                    remote_address="127.0.0.1:9999",
                    session_stats=session_stats,
                )

            self.assertEqual(len(captured.records), 2)
            self.assertIn("Submit rejected:", captured.output[0])
            self.assertIn("Submit rejected repeatedly:", captured.output[1])
            self.assertIn("suppressedCount=1", captured.output[1])

    async def test_stop_closes_active_client_after_notify_loop_started(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=1.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                await self._read_json(reader)

                await asyncio.wait_for(service.stop(), timeout=2.0)
                self.assertEqual(await asyncio.wait_for(reader.readline(), timeout=2.0), b"")
                writer.close()
                await writer.wait_closed()
                writer = None
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_rotation_and_restart_recovery_preserve_activity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                activity_log_rotate_bytes=900,
                activity_log_retention_files=4,
            )

            pre_snapshot = await self._run_share_session(config, share_count=24)
            rotated_logs = sorted(tmp_path.glob("shares.*-*.jsonl"))
            self.assertGreaterEqual(len(rotated_logs), 1)
            self.assertTrue(
                all(
                    re.fullmatch(r"shares\.\d{20}-\d{20}\.jsonl", path.name)
                    for path in rotated_logs
                )
            )

            restart_service = StratumIngressService(config)
            await restart_service.start()
            try:
                post_snapshot = self._load_json(config.activity_snapshot_output_path)
            finally:
                await restart_service.stop()

            self.assertEqual(
                pre_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
                post_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
            )
            self.assertEqual(
                pre_snapshot["pool"]["rolling"]["15m"]["shareCount"],
                post_snapshot["pool"]["rolling"]["15m"]["shareCount"],
            )
            self.assertEqual(pre_snapshot["meta"]["warningCount"], 0)
            self.assertEqual(post_snapshot["meta"]["warningCount"], 0)

    async def test_replay_window_boundary_warns_when_retention_truncates_tail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                activity_log_rotate_bytes=200,
                activity_log_retention_files=1,
            )

            pre_snapshot = await self._run_share_session(
                config,
                share_count=60,
                submit_pause_seconds=0.02,
            )
            self.assertEqual(pre_snapshot["meta"]["warningCount"], 0)
            rotated_logs = list(tmp_path.glob("shares.*-*.jsonl"))
            self.assertEqual(len(rotated_logs), 1)

            restart_service = StratumIngressService(config)
            await restart_service.start()
            try:
                post_snapshot = self._load_json(config.activity_snapshot_output_path)
            finally:
                await restart_service.stop()

            self.assertGreater(post_snapshot["meta"]["warningCount"], 0)
            self.assertEqual(
                pre_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
                post_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
            )
            self.assertLess(
                post_snapshot["pool"]["rolling"]["15m"]["shareCount"],
                pre_snapshot["pool"]["rolling"]["15m"]["shareCount"],
            )

    async def _run_share_session(
        self,
        config: PoolCoreConfig,
        *,
        share_count: int,
        submit_pause_seconds: float = 0.0,
    ) -> dict:
        service = StratumIngressService(config)
        await service.start()

        reader = writer = None
        try:
            reader, writer = await self._open_client(service)
            await self._rpc_call(
                reader,
                writer,
                {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
            )
            writer.write(
                json.dumps(
                    {
                        "id": 2,
                        "method": "mining.authorize",
                        "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                    }
                ).encode("utf-8")
                + b"\n"
            )
            await writer.drain()

            await self._read_json(reader)
            await self._read_json(reader)
            notify_message = await self._read_json(reader)
            self.assertEqual(notify_message["method"], "mining.notify")

            for request_id in range(3, 3 + share_count):
                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": request_id,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            extranonce2=f"{request_id:08x}",
                            nonce=f"{(request_id + 1):08x}",
                        ),
                    },
                )
                self.assertTrue(response["result"])
                if submit_pause_seconds > 0:
                    await asyncio.sleep(submit_pause_seconds)

            writer.close()
            await writer.wait_closed()
            writer = None
            await service.stop()
            return self._load_json(config.activity_snapshot_output_path)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def _open_client(self, service: StratumIngressService):
        assert service._server is not None
        host, port = service._server.sockets[0].getsockname()[:2]
        return await asyncio.open_connection(host, port)

    async def _rpc_call(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        payload: dict[str, object],
    ) -> dict:
        writer.write(json.dumps(payload).encode("utf-8") + b"\n")
        await writer.drain()
        request_id = payload["id"]

        while True:
            response = await self._read_json(reader)
            if response.get("id") == request_id:
                return response

    async def _read_json(self, reader: asyncio.StreamReader) -> dict:
        return json.loads((await reader.readline()).decode("utf-8"))

    def _submit_params(
        self,
        login: str,
        job_id: str,
        ntime: str,
        *,
        extranonce2: str = "00000001",
        nonce: str = "00000001",
    ) -> list[str]:
        return [login, job_id, extranonce2, ntime, nonce]

    async def _wait_for(self, predicate, timeout: float = 3.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
        self.fail("Timed out waiting for predicate")

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_share_events(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _candidate_event_log_path(self, config: PoolCoreConfig) -> Path:
        return config.activity_log_path.with_name("candidate-events.jsonl")

    def _read_candidate_events(self, config: PoolCoreConfig) -> list[str]:
        path = self._candidate_event_log_path(config)
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _candidate_outcome_event_log_path(self, config: PoolCoreConfig) -> Path:
        return config.activity_log_path.with_name("candidate-outcome-events.jsonl")

    def _read_candidate_outcome_events(self, config: PoolCoreConfig) -> list[str]:
        path = self._candidate_outcome_event_log_path(config)
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _share_hash_probe_log_path(self, config: PoolCoreConfig) -> Path:
        return config.activity_log_path.with_name("share-hash-probe.jsonl")

    def _read_share_hash_probe_events(self, config: PoolCoreConfig) -> list[str]:
        path = self._share_hash_probe_log_path(config)
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _notify_debug_capture_path(self, config: PoolCoreConfig) -> Path:
        return config.activity_log_path.with_name("notify-debug-capture.jsonl")

    def _read_notify_debug_capture_events(self, config: PoolCoreConfig) -> list[str]:
        path = self._notify_debug_capture_path(config)
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _make_config(
        self,
        tmp_path: Path,
        *,
        synthetic_job_interval_seconds: float = 30.0,
        template_mode: str = "synthetic",
        template_fetch_interval_seconds: float = 15.0,
        template_job_ttl_seconds: int = 180,
        enable_real_submitblock: bool = False,
        real_submitblock_max_sends: int = 1,
        activity_log_rotate_bytes: int = 32 * 1024 * 1024,
        activity_log_retention_files: int = 8,
        notify_debug_capture_limit: int = 0,
        low_diff_share_full_log_every_n: int = 1,
        stratum_notify_clean_jobs_legacy: bool = False,
        stratum_wire_difficulty_scale: float = 65536.0,
        stratum_vardiff_enabled: bool = False,
        stratum_vardiff_initial_difficulty: float = 0.1,
        stratum_vardiff_min_difficulty: float = 0.01,
        stratum_vardiff_max_difficulty: float = 64.0,
    ) -> PoolCoreConfig:
        return PoolCoreConfig(
            coin_name="PEPEPOW",
            algorithm="hoohashv110-pepew",
            fee_percent=1.0,
            min_payout=10.0,
            stratum_host="pool.example.com",
            stratum_port=3333,
            stratum_tls=False,
            stratum_bind_host="127.0.0.1",
            stratum_bind_port=0,
            rpc_url="http://127.0.0.1:8834",
            rpc_user="",
            rpc_password="",
            rpc_timeout_seconds=1.0,
            snapshot_output_path=tmp_path / "runtime.json",
            activity_snapshot_output_path=tmp_path / "activity-snapshot.json",
            snapshot_interval_seconds=60,
            activity_snapshot_interval_seconds=0.1,
            rpc_cache_ttl_seconds=1,
            recent_blocks_limit=1,
            stale_after_seconds=180,
            producer_name="test",
            activity_log_path=tmp_path / "shares.jsonl",
            activity_window_seconds=900,
            activity_mode="testing-local-ingest",
            stratum_queue_maxsize=1000,
            hashrate_assumed_share_difficulty=1.0,
            estimated_hashrate_assumed_share_difficulty=1.0,
            synthetic_job_interval_seconds=synthetic_job_interval_seconds,
            template_mode=template_mode,
            template_fetch_interval_seconds=template_fetch_interval_seconds,
            template_job_ttl_seconds=template_job_ttl_seconds,
            template_job_cache_size=64,
            enable_real_submitblock=enable_real_submitblock,
            real_submitblock_max_sends=real_submitblock_max_sends,
            activity_log_rotate_bytes=activity_log_rotate_bytes,
            activity_log_retention_files=activity_log_retention_files,
            low_diff_share_full_log_every_n=low_diff_share_full_log_every_n,
            notify_debug_capture_limit=notify_debug_capture_limit,
            stratum_notify_clean_jobs_legacy=stratum_notify_clean_jobs_legacy,
            stratum_wire_difficulty_scale=stratum_wire_difficulty_scale,
            stratum_vardiff_enabled=stratum_vardiff_enabled,
            stratum_vardiff_initial_difficulty=stratum_vardiff_initial_difficulty,
            stratum_vardiff_min_difficulty=stratum_vardiff_min_difficulty,
            stratum_vardiff_max_difficulty=stratum_vardiff_max_difficulty,
            stratum_vardiff_target_share_interval_seconds=15.0,
            stratum_vardiff_retarget_interval_seconds=60.0,
            stratum_vardiff_min_shares=4,
            stratum_vardiff_fast_share_interval_seconds=8.0,
            stratum_vardiff_slow_share_interval_seconds=25.0,
        )


if __name__ == "__main__":
    unittest.main()


class RejectEvidenceArtifactTests(unittest.TestCase):
    """Unit tests for _append_submit_evidence new reject-evidence fields."""

    def _make_state(self, *, clean_jobs_legacy=False):
        from stratum_protocol import ConnectionState
        state = ConnectionState(session_id="sid-test", extranonce1="aabbccdd")
        state.authorized_wallet = "wallet1"
        state.authorized_worker = "rig01"
        state.clean_jobs_legacy = clean_jobs_legacy
        state.current_difficulty = 1.0
        return state

    def _make_daemon_job(self, *, source="daemon-template"):
        class _Job:
            pass
        job = _Job()
        job.source = source
        job.version = "20000000"
        job.prevhash = "a" * 64
        job.nbits = "1d00ffff"
        job.ntime = "01020304"
        job.coinb1 = "01"
        job.coinb2 = "ff"
        job.merkle_branch = ()
        job.target_context = {
            "bits": "1d00ffff",
            "version": "20000000",
            "curtime": 0x01020304,
            "target": "00000000ffff" + "00" * 26,
        }
        job.preimage_context = {"source": "template-derived"}
        job.template_anchor = "anchor-abc"
        job.authoritative_context = None
        return job

    def _make_rejected_assessment(self, job):
        return SubmitAssessment(
            job_status="current",
            submit_job_id="job-0011223344556677",
            cached_job=job,
            accepted=False,
            reject_reason="low-difficulty-share",
            detail="local share hash exceeded effective share target",
            share_hash_validation_status="share-hash-invalid",
            share_hash_valid=False,
            share_hash_diagnostic={
                "comparisonStage": "share-hash-compare",
                "reasonCode": "header80-mismatch",
                "refinedReasonCode": "ntime-mismatch",
                "header80Hex": "aa" * 80,
                "localComputedHash": "bb" * 32,
                "shareTargetUsed": "cc" * 32,
                "meetsShareTarget": False,
                "meetsBlockTarget": False,
                "header80VariantTargetMatches": {
                    "versionSourceOrder": False,
                    "ntimeSourceOrder": True,
                    "allFieldsSourceOrder": False,
                },
            },
        )

    def test_reject_evidence_captures_new_fields(self):
        """Rejected daemon-template submit captures cleanJobsLegacy, shareHashValidationMode,
        preimage source fields, refinedReasonCode, and variantTargetMatches."""
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            evidence_path = tmp_path / "submit-evidence.jsonl"

            service = StratumIngressService.__new__(StratumIngressService)
            service._submit_evidence_path = evidence_path

            job = self._make_daemon_job()
            state = self._make_state(clean_jobs_legacy=True)
            assessment = self._make_rejected_assessment(job)
            params = ["wallet1.rig01", "job-0011223344556677", "00000001", "01020304", "aabbccdd"]
            observed_at = datetime(2026, 4, 19, 11, 0, 0, tzinfo=timezone.utc)

            service._append_submit_evidence(assessment, state, "1.2.3.4:5678", params, observed_at)

            self.assertTrue(evidence_path.exists())
            records = [json.loads(line) for line in evidence_path.read_text().splitlines() if line.strip()]
            self.assertEqual(len(records), 1)
            rec = records[0]

            self.assertEqual(rec["cleanJobsLegacy"], True)
            self.assertEqual(rec["shareHashValidationMode"], "hoohashv110-pepew-header80")
            self.assertEqual(rec["preimageVersion"], "20000000")
            self.assertEqual(rec["preimagePrevhash"], "a" * 64)
            self.assertEqual(rec["preimageNbits"], "1d00ffff")
            self.assertEqual(rec["preimageJobNtime"], "01020304")
            self.assertEqual(rec["issuedJobCoinb1"], "01")
            self.assertEqual(rec["issuedJobCoinb2"], "ff")
            self.assertEqual(rec["issuedJobMerkleBranch"], [])
            self.assertEqual(rec["refinedReasonCode"], "ntime-mismatch")
            self.assertIn("variantTargetMatches", rec)
            variants = rec["variantTargetMatches"]
            self.assertIsInstance(variants, dict)
            self.assertTrue(variants.get("ntimeSourceOrder"))
            self.assertFalse(variants.get("versionSourceOrder"))
            self.assertNotIn("issuedVsSubmitReconstructionMatch", rec)
            self.assertEqual(rec["rejectReason"], "low-difficulty-share")

    def test_reject_evidence_skipped_for_synthetic_source(self):
        """No record is written for synthetic-source jobs."""
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            evidence_path = tmp_path / "submit-evidence.jsonl"

            service = StratumIngressService.__new__(StratumIngressService)
            service._submit_evidence_path = evidence_path

            job = self._make_daemon_job(source="synthetic")
            state = self._make_state()
            assessment = self._make_rejected_assessment(job)
            params = ["wallet1.rig01", "job-0011223344556677", "00000001", "01020304", "aabbccdd"]
            observed_at = datetime(2026, 4, 19, 11, 0, 0, tzinfo=timezone.utc)

            service._append_submit_evidence(assessment, state, "1.2.3.4:5678", params, observed_at)

            self.assertFalse(evidence_path.exists())


class LowDifficultyShareLogThrottleTests(unittest.TestCase):
    def _make_service(self, *, low_diff_share_full_log_every_n: int) -> StratumIngressService:
        tmp_path = Path(tempfile.mkdtemp())
        config = StratumIngressTests()._make_config(
            tmp_path,
            low_diff_share_full_log_every_n=low_diff_share_full_log_every_n,
        )
        return StratumIngressService(config)

    def _make_state(self):
        state = stratum_protocol.ConnectionState(session_id="sid-1", extranonce1="aabbccdd")
        state.authorized_wallet = "wallet1"
        state.authorized_worker = "rig01"
        state.current_difficulty = 1.0
        state.clean_jobs_legacy = False
        return state

    def _make_job(self):
        class _Job:
            pass

        job = _Job()
        job.source = "daemon-template"
        job.template_anchor = "anchor-1"
        job.target_context = {"bits": "1d00ffff"}
        job.preimage_context = {"source": "template-derived"}
        return job

    def _make_assessment(
        self,
        *,
        accepted: bool,
        reject_reason: str | None,
        share_hash_validation_status: str | None,
    ) -> SubmitAssessment:
        diagnostic = {
            "comparisonStage": "share-hash-compare",
            "reasonCode": reject_reason or "pool-share",
            "localComputedHash": "11" * 32,
            "shareTargetUsed": "22" * 32,
            "blockTargetUsed": "33" * 32,
            "meetsShareTarget": accepted,
            "meetsBlockTarget": False,
        }
        return SubmitAssessment(
            job_status="current",
            submit_job_id="job-1",
            cached_job=self._make_job(),
            accepted=accepted,
            reject_reason=reject_reason,
            detail="detail-text" if reject_reason is not None else None,
            duplicate_submit=False,
            target_validation_status="context-valid",
            candidate_possible=False,
            share_hash_validation_status=share_hash_validation_status,
            share_hash_valid=accepted,
            share_hash_diagnostic=diagnostic,
        )

    def _build_payload(self, service: StratumIngressService, assessment: SubmitAssessment, *, sequence: int) -> dict[str, object]:
        state = self._make_state()
        return service._build_share_event_payload(
            assessment=assessment,
            state=state,
            cached_job=assessment.cached_job,
            wallet="wallet1",
            worker="rig01",
            login="wallet1.rig01",
            observed_at=datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc),
            remote_address="127.0.0.1:1111",
            sequence=sequence,
            submit_job_id=assessment.submit_job_id,
            submit_params=["wallet1.rig01", "job-1", "00000001", "01020304", "aabbccdd"],
            accepted_submit=assessment.accepted,
            accepted_share=assessment.counts_as_accepted_share,
            share_event_candidate_possible=assessment.candidate_possible,
        )

    def test_accepted_share_still_writes_full_event(self):
        service = self._make_service(low_diff_share_full_log_every_n=10)
        payload = self._build_payload(
            service,
            self._make_assessment(
                accepted=True,
                reject_reason=None,
                share_hash_validation_status="share-hash-valid",
            ),
            sequence=1,
        )

        self.assertIn("submit", payload)
        self.assertIn("shareHashDiagnostic", payload)
        self.assertIn("targetContext", payload)
        self.assertIn("preimageContext", payload)
        self.assertNotIn("lowDifficultyShareLogSampled", payload)

    def test_non_low_difficulty_rejection_still_writes_full_event(self):
        service = self._make_service(low_diff_share_full_log_every_n=10)
        payload = self._build_payload(
            service,
            self._make_assessment(
                accepted=False,
                reject_reason="target-context-mismatch",
                share_hash_validation_status="preimage-mismatch",
            ),
            sequence=1,
        )

        self.assertIn("submit", payload)
        self.assertIn("shareHashDiagnostic", payload)
        self.assertIn("targetContext", payload)
        self.assertNotIn("lowDifficultyShareLogSampled", payload)

    def test_low_difficulty_share_respects_every_n_throttle(self):
        service = self._make_service(low_diff_share_full_log_every_n=3)
        assessment = self._make_assessment(
            accepted=False,
            reject_reason="low-difficulty-share",
            share_hash_validation_status="low-difficulty-share",
        )

        first = self._build_payload(service, assessment, sequence=1)
        second = self._build_payload(service, assessment, sequence=2)
        third = self._build_payload(service, assessment, sequence=3)

        self.assertNotIn("submit", first)
        self.assertNotIn("shareHashDiagnostic", first)
        self.assertEqual(first["rejectReason"], "low-difficulty-share")
        self.assertNotIn("submit", second)
        self.assertIn("submit", third)
        self.assertIn("shareHashDiagnostic", third)
        self.assertEqual(third["lowDifficultyShareLogSampled"], True)
        self.assertEqual(third["lowDifficultyShareSkippedSinceLastSample"], 2)

    def test_low_difficulty_share_counters_remain_accurate(self):
        service = self._make_service(low_diff_share_full_log_every_n=20)
        assessment = self._make_assessment(
            accepted=False,
            reject_reason="low-difficulty-share",
            share_hash_validation_status="low-difficulty-share",
        )

        for _ in range(3):
            service._record_submit_validation(assessment)

        self.assertEqual(service._submit_validation_counts["rejected"], 3)
        self.assertEqual(
            service._submit_validation_counts["rejectReasonCounts"]["low-difficulty-share"],
            3,
        )
        self.assertEqual(
            service._submit_validation_counts["shareHashValidationCounts"]["low-difficulty-share"],
            3,
        )

    def test_reject_evidence_clean_jobs_legacy_false_recorded(self):
        """cleanJobsLegacy=False is faithfully recorded."""
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            evidence_path = tmp_path / "submit-evidence.jsonl"

            service = StratumIngressService.__new__(StratumIngressService)
            service._submit_evidence_path = evidence_path

            job = self._make_daemon_job()
            state = self._make_state(clean_jobs_legacy=False)
            assessment = self._make_rejected_assessment(job)
            params = ["wallet1.rig01", "job-0011223344556677", "00000001", "01020304", "aabbccdd"]
            observed_at = datetime(2026, 4, 19, 11, 0, 0, tzinfo=timezone.utc)

            service._append_submit_evidence(assessment, state, "1.2.3.4:5678", params, observed_at)

            records = [json.loads(line) for line in evidence_path.read_text().splitlines() if line.strip()]
            self.assertEqual(records[0]["cleanJobsLegacy"], False)

    def test_reject_evidence_variant_matches_absent_when_not_in_diagnostic(self):
        """variantTargetMatches key is absent when diagnostic has no header80VariantTargetMatches."""
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            evidence_path = tmp_path / "submit-evidence.jsonl"

            service = StratumIngressService.__new__(StratumIngressService)
            service._submit_evidence_path = evidence_path

            job = self._make_daemon_job()
            state = self._make_state()
            assessment = SubmitAssessment(
                job_status="current",
                submit_job_id="job-0011223344556677",
                cached_job=job,
                accepted=False,
                reject_reason="preimage-missing",
                detail="header preimage is missing extranonce1",
                share_hash_validation_status="preimage-missing",
                share_hash_valid=None,
                share_hash_diagnostic={
                    "comparisonStage": "preimage-validation",
                    "reasonCode": "preimage-missing",
                },
            )
            params = ["wallet1.rig01", "job-0011223344556677", "00000001", "01020304", "aabbccdd"]
            observed_at = datetime(2026, 4, 19, 11, 0, 0, tzinfo=timezone.utc)

            service._append_submit_evidence(assessment, state, "1.2.3.4:5678", params, observed_at)

            records = [json.loads(line) for line in evidence_path.read_text().splitlines() if line.strip()]
            self.assertEqual(len(records), 1)
            self.assertNotIn("variantTargetMatches", records[0])
            self.assertEqual(records[0]["rejectReason"], "preimage-missing")

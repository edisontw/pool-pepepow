#!/usr/bin/env python3
"""Payout helper tool for PEPEPOW pool.
Handles read-only payout candidate generation and manual payment recording.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import base64
import urllib.request
import urllib.error
import subprocess
import fcntl
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def load_pool_snapshot() -> dict[str, Any]:
    paths = [
        Path(os.getenv("PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT", "")),
        Path(os.getenv("PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH", "")),
        Path("/var/lib/pepepow-pool/pool-snapshot.json"),
        Path(".runtime/systemd-smoke/pool-snapshot.json"),
        Path(".runtime/pool-snapshot.json"),
        Path("apps/api/data/mock/pool-snapshot.json"),
    ]
    for p in paths:
        if p and p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {}

def load_env_vars() -> dict[str, str]:
    paths = [
        Path(os.getenv("PEPEPOW_LIVE_STRATUM_RUNTIME_DIR", "")) / "launch.env",
        Path(".runtime/live-stratum/launch.env"),
        Path(".runtime/systemd-smoke/core.env"),
    ]
    env = {}
    for p in paths:
        if p and p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            env[k.strip()] = v.strip()
                break
            except Exception:
                pass
    env.update({k: v for k, v in os.environ.items() if isinstance(v, str)})
    return env

def summarize_rpc_params(params: list[Any]) -> list[Any]:
    summary = []
    for param in params:
        if isinstance(param, str) and re.fullmatch(r"[0-9a-fA-F]{64}", param):
            summary.append(f"{param[:12]}...{param[-8:]}")
        else:
            summary.append(param)
    return summary


def query_rpc_result(method: str, params: list[Any], timeout: float = 5) -> dict[str, Any]:
    env = load_env_vars()
    rpc_url = env.get("PEPEPOWD_RPC_URL")
    if not rpc_url:
        rpc_host = env.get("PEPEPOWD_RPC_HOST", "127.0.0.1")
        rpc_port = env.get("PEPEPOWD_RPC_PORT", "8834")
        rpc_url = f"http://{rpc_host}:{rpc_port}"
    rpc_user = env.get("PEPEPOWD_RPC_USER", "")
    rpc_password = env.get("PEPEPOWD_RPC_PASSWORD", "")
    
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "payout_helper",
        "method": method,
        "params": params,
    }).encode("utf-8")
    
    auth = base64.b64encode(f"{rpc_user}:{rpc_password}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}"
        },
        method="POST"
    )
    
    meta = {"method": method, "paramsSummary": summarize_rpc_params(params)}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            try:
                res_data = json.loads(response.read().decode("utf-8"))
            except json.JSONDecodeError as exc:
                return {**meta, "ok": False, "error": "malformed_json_response", "exceptionType": type(exc).__name__, "exceptionMessage": str(exc)}
            if not isinstance(res_data, dict):
                return {**meta, "ok": False, "error": "malformed_json_response"}
            rpc_error = res_data.get("error")
            if rpc_error:
                if isinstance(rpc_error, dict):
                    return {
                        **meta,
                        "ok": False,
                        "error": "rpc_json_error",
                        "rpcErrorCode": rpc_error.get("code"),
                        "rpcErrorMessage": rpc_error.get("message"),
                    }
                return {**meta, "ok": False, "error": "rpc_json_error", "rpcErrorMessage": str(rpc_error)}
            if res_data.get("result") is None:
                return {**meta, "ok": False, "error": "rpc_null_result"}
            return {**meta, "ok": True, "result": res_data.get("result")}
    except urllib.error.HTTPError as exc:
        return {**meta, "ok": False, "error": "http_error", "httpStatus": exc.code, "exceptionType": type(exc).__name__, "exceptionMessage": str(exc)}
    except (TimeoutError, socket.timeout) as exc:
        return {**meta, "ok": False, "error": "timeout", "exceptionType": type(exc).__name__, "exceptionMessage": str(exc)}
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        reason_type = type(reason).__name__ if reason is not None else type(exc).__name__
        reason_message = str(reason if reason is not None else exc)
        error = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "connection_failure"
        return {**meta, "ok": False, "error": error, "exceptionType": reason_type, "exceptionMessage": reason_message}
    except Exception as exc:
        return {**meta, "ok": False, "error": "exception", "exceptionType": type(exc).__name__, "exceptionMessage": str(exc)}


def query_rpc(method: str, params: list[Any], timeout: float = 5) -> Any:
    result = query_rpc_result(method, params, timeout=timeout)
    if result.get("ok"):
        return result.get("result")
    return None


_REAL_QUERY_RPC = query_rpc

READ_ONLY_WALLET_CLI_METHODS = {"getbalance", "getwalletinfo", "validateaddress"}

def query_wallet_cli(method: str, params: list[Any]) -> Any:
    """Run a configured wallet CLI read-only command and parse its result."""
    if method not in READ_ONLY_WALLET_CLI_METHODS:
        return None

    env = load_env_vars()
    cli_path = env.get("PEPEPOW_WALLET_CLI") or "/home/ubuntu/PEPEPOW-cli"
    if not cli_path or not os.path.exists(cli_path) or not os.access(cli_path, os.X_OK):
        return None

    safe_args = [cli_path, method] + [str(param) for param in params]
    try:
        proc = subprocess.run(
            safe_args,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None

    stdout = proc.stdout.strip()
    if method == "getbalance":
        try:
            return float(stdout)
        except (TypeError, ValueError):
            return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None

def wallet_readonly_call(method: str, params: list[Any]) -> Any:
    """Read wallet data through a safe read-only path.

    Prefer an explicitly configured wallet CLI because live payout tooling uses
    PEPEPOW_WALLET_CLI on MN5 and tests mock that path. Fall back to direct RPC
    only when the CLI is absent/unreadable and explicit RPC config exists.
    """
    env = load_env_vars()
    cli_configured = bool(env.get("PEPEPOW_WALLET_CLI"))
    if cli_configured:
        result = query_wallet_cli(method, params)
        if result is not None:
            return result

    rpc_configured = bool(
        env.get("PEPEPOWD_RPC_URL")
        or env.get("PEPEPOWD_RPC_USER")
        or env.get("PEPEPOWD_RPC_PASSWORD")
    )
    if rpc_configured:
        result = query_rpc(method, params)
        if result is not None:
            return result

    if not cli_configured:
        return query_wallet_cli(method, params)
    return None


def daemon_readonly_call(method: str, params: list[Any]) -> Any:
    """Read daemon chain data through direct RPC with a strict timeout."""
    result, _meta = daemon_readonly_lookup(method, params)
    return result


def daemon_readonly_lookup(method: str, params: list[Any]) -> tuple[Any, dict[str, Any]]:
    """Read daemon chain data and return compact diagnostics for failures."""
    if query_rpc is not _REAL_QUERY_RPC:
        meta = {"method": method, "paramsSummary": summarize_rpc_params(params)}
        try:
            result = query_rpc(method, params, timeout=5)
        except Exception as exc:
            return None, {**meta, "error": "exception", "exceptionType": type(exc).__name__, "exceptionMessage": str(exc)}
        if result is None:
            return None, {**meta, "error": "rpc_null_result"}
        return result, meta
    rpc_result = query_rpc_result(method, params, timeout=5)
    if rpc_result.get("ok"):
        return rpc_result.get("result"), rpc_result
    return None, rpc_result


def atomic_write_json(output_path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically using a temp file and os.replace."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(dir=output_path.parent)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(temp_path, output_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


FAILED_PAYMENT_ACTION_STATUSES = {"failed", "send_failed", "reserved"}
SUCCESS_PAYMENT_ACTION_STATUSES = {"sent", "paid", "paid_manual", "manual_payment_recorded"}
SUCCESS_PAYMENT_ACTIONS = {"manual_payment_recorded"}


def action_represents_successful_payment(action: dict[str, Any]) -> bool:
    """Return True only for payment actions that should count as paid.

    Legacy manual payment rows did not always include a status field, so a row
    with txid + candidate_id + wallet is still treated as successful unless it
    explicitly carries a failed/reserved status.
    """
    if not isinstance(action, dict):
        return False
    status = action.get("status")
    if isinstance(status, str):
        normalized = status.strip().lower()
        if normalized in FAILED_PAYMENT_ACTION_STATUSES:
            return False
        if normalized in SUCCESS_PAYMENT_ACTION_STATUSES:
            return bool(action.get("txid"))
    action_name = action.get("action")
    if isinstance(action_name, str) and action_name.strip().lower() in SUCCESS_PAYMENT_ACTIONS:
        return bool(action.get("txid"))
    return bool(action.get("txid") and action.get("candidate_id") and action.get("wallet"))


def load_paid_payment_pairs(actions_log_path: Path, candidates_path: Path | None = None) -> set[tuple[str, str]]:
    """Load successful paid candidate_id + wallet pairs from the append-only actions log."""
    paid_pairs: set[tuple[str, str]] = set()
    if actions_log_path.exists():
        try:
            with actions_log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        act = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(act, dict) or not action_represents_successful_payment(act):
                        continue
                    c_id = act.get("candidate_id")
                    wallet = act.get("wallet")
                    if c_id and wallet:
                        paid_pairs.add((str(c_id), str(wallet)))
                        source_ids = act.get("carrySourceCandidateIds")
                        if isinstance(source_ids, list):
                            for source_id in source_ids:
                                if source_id:
                                    paid_pairs.add((str(source_id), str(wallet)))
        except Exception:
            pass

    if not paid_pairs or candidates_path is None or not candidates_path.exists():
        return paid_pairs

    try:
        with candidates_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return paid_pairs
    if not isinstance(data, dict):
        return paid_pairs
    candidates = data.get("items") or data.get("candidates") or []
    if not isinstance(candidates, list):
        return paid_pairs

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        c_id = candidate.get("candidateId") or candidate.get("candidate_hash")
        payouts = candidate.get("payouts")
        if not c_id or not isinstance(payouts, list):
            continue
        for payout in payouts:
            if not isinstance(payout, dict):
                continue
            wallet = payout.get("wallet")
            if not wallet or (str(c_id), str(wallet)) not in paid_pairs:
                continue
            source_ids = payout.get("carrySourceCandidateIds")
            if source_ids is None:
                source_ids = payout.get("sourceCandidateIds")
            if not isinstance(source_ids, list):
                continue
            for source_id in source_ids:
                if source_id:
                    paid_pairs.add((str(source_id), str(wallet)))
    return paid_pairs


def payment_already_recorded(actions_log_path: Path, candidate_id: str, wallet: str) -> bool:
    """Check whether candidate_id + wallet already has a successful payment."""
    if not actions_log_path.exists():
        return False
    try:
        with actions_log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    act = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(act, dict)
                    and act.get("candidate_id") == candidate_id
                    and act.get("wallet") == wallet
                    and action_represents_successful_payment(act)
                ):
                    return True
    except Exception:
        return False
    return False


def append_payment_action(actions_log_path: Path, action: dict[str, Any]) -> None:
    actions_log_path.parent.mkdir(parents=True, exist_ok=True)
    with actions_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(action, sort_keys=True) + "\n")


def payment_actions_lock_path(actions_log_path: Path) -> Path:
    return actions_log_path.with_name(f"{actions_log_path.stem}.lock")


def _coinbase_output_summary(index: int, output: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"index": index}
    if "value" in output:
        summary["value"] = output.get("value")
    script_pub_key = output.get("scriptPubKey")
    if isinstance(script_pub_key, dict):
        summary["scriptPubKey"] = {
            k: script_pub_key.get(k)
            for k in ("type", "asm", "addresses", "hex")
            if k in script_pub_key
        }
    return summary


PEPEPOW_MINER_SPLIT_RATIO = 0.65
PEPEPOW_MASTERNODE_SPLIT_RATIO = 0.35
PEPEPOW_SPECIAL_REWARD_AMOUNT = 250.0
PEPEPOW_REWARD_MATCH_TOLERANCE = 0.00000001
DEFAULT_POOL_REWARD_ADDRESS = "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho"


def _amount_matches(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= PEPEPOW_REWARD_MATCH_TOLERANCE


def expected_pool_reward_address() -> str:
    env = load_env_vars()
    return (env.get("PEPEPOW_POOL_CORE_REWARD_ADDRESS") or DEFAULT_POOL_REWARD_ADDRESS).strip()


def coinbase_output_addresses(output: dict[str, Any]) -> list[str]:
    script_pub_key = output.get("scriptPubKey")
    if not isinstance(script_pub_key, dict):
        return []
    addresses = script_pub_key.get("addresses")
    if isinstance(addresses, list):
        return [str(address) for address in addresses if address]
    address = script_pub_key.get("address")
    if address:
        return [str(address)]
    return []


def detect_coinbase_miner_reward(vout_list: list[Any]) -> dict[str, Any]:
    spendable_outputs = []
    total_reward = 0.0
    for index, out in enumerate(vout_list):
        if not isinstance(out, dict):
            continue
        try:
            value = float(out.get("value"))
        except (ValueError, TypeError):
            continue
        total_reward += value
        spendable_outputs.append((index, out, value))

    special_index = None
    special_reward_amount = 0.0
    for index, _out, value in spendable_outputs:
        if _amount_matches(value, PEPEPOW_SPECIAL_REWARD_AMOUNT):
            special_index = index
            special_reward_amount = value
            break

    remaining_reward = total_reward - special_reward_amount
    expected_miner_reward = remaining_reward * PEPEPOW_MINER_SPLIT_RATIO
    expected_masternode_reward = remaining_reward * PEPEPOW_MASTERNODE_SPLIT_RATIO

    miner_index = None
    miner_reward_amount = None
    masternode_reward_amount = None

    for index, _out, value in spendable_outputs:
        if index == special_index:
            continue
        if miner_index is None and _amount_matches(value, expected_miner_reward):
            miner_index = index
            miner_reward_amount = value
            continue
        if masternode_reward_amount is None and _amount_matches(value, expected_masternode_reward):
            masternode_reward_amount = value

    excluded = []
    all_reward_addresses: list[str] = []
    miner_reward_addresses: list[str] = []
    miner_reward_script_pub_key = None
    for index, out, _value in spendable_outputs:
        output_addresses = coinbase_output_addresses(out)
        all_reward_addresses.extend(output_addresses)
        if index == miner_index:
            miner_reward_addresses = output_addresses
            if isinstance(out.get("scriptPubKey"), dict):
                miner_reward_script_pub_key = _coinbase_output_summary(index, out).get("scriptPubKey")
        if index != miner_index:
            excluded.append(_coinbase_output_summary(index, out))

    expected_address = expected_pool_reward_address()
    if miner_index is None or miner_reward_script_pub_key is None:
        coinbase_matches_expected_pool_wallet = None
    else:
        coinbase_matches_expected_pool_wallet = expected_address in miner_reward_addresses
    return {
        "coinbaseTotalReward": total_reward,
        "minerRewardOutputIndex": miner_index,
        "minerRewardAmount": miner_reward_amount,
        "masternodeRewardAmount": masternode_reward_amount,
        "specialRewardAmount": special_reward_amount,
        "coinbaseRewardAddresses": all_reward_addresses,
        "minerRewardAddresses": miner_reward_addresses,
        "minerRewardScriptPubKey": miner_reward_script_pub_key,
        "expectedPoolRewardAddress": expected_address,
        "coinbaseMatchesExpectedPoolWallet": coinbase_matches_expected_pool_wallet,
        "excludedCoinbaseOutputs": excluded,
        "rewardSource": "coinbase_detected_miner_split_reward",
    }


def fetch_coinbase_reward_from_daemon(
    height: Any,
    candidate_block_hash: Any = None,
    allow_height_fallback: bool = True,
) -> dict[str, Any]:
    """Fetch PEPEPOW coinbase reward accounting data for a confirmed height."""
    result: dict[str, Any] = {
        "blockHash": None,
        "resolvedBlockHash": None,
        "confirmations": None,
        "coinbaseTxid": None,
        "resolvedCoinbaseTxid": None,
        "coinbaseTotalReward": None,
        "minerRewardOutputIndex": None,
        "minerRewardAmount": None,
        "masternodeRewardAmount": None,
        "specialRewardAmount": None,
        "coinbaseRewardAddresses": [],
        "minerRewardAddresses": [],
        "minerRewardScriptPubKey": None,
        "expectedPoolRewardAddress": expected_pool_reward_address(),
        "coinbaseMatchesExpectedPoolWallet": None,
        "excludedCoinbaseOutputs": [],
        "rewardSource": "coinbase_detected_miner_split_reward",
        "coinbaseLookupStatus": "not_attempted",
        "coinbaseLookupError": None,
        "coinbaseLookupStep": None,
        "coinbaseLookupMethod": None,
        "coinbaseLookupParamsSummary": None,
        "coinbaseLookupRpcErrorCode": None,
        "coinbaseLookupRpcErrorMessage": None,
        "coinbaseLookupHttpStatus": None,
        "coinbaseLookupExceptionType": None,
        "coinbaseLookupExceptionMessage": None,
    }

    def set_lookup_failure(error: str, step: str, meta: dict[str, Any] | None = None) -> None:
        meta = meta or {}
        result["coinbaseLookupStatus"] = "error"
        result["coinbaseLookupError"] = error
        result["coinbaseLookupStep"] = step
        result["coinbaseLookupMethod"] = meta.get("method")
        result["coinbaseLookupParamsSummary"] = meta.get("paramsSummary")
        result["coinbaseLookupRpcErrorCode"] = meta.get("rpcErrorCode")
        result["coinbaseLookupRpcErrorMessage"] = meta.get("rpcErrorMessage")
        result["coinbaseLookupHttpStatus"] = meta.get("httpStatus")
        result["coinbaseLookupExceptionType"] = meta.get("exceptionType")
        result["coinbaseLookupExceptionMessage"] = meta.get("exceptionMessage")

    try:
        height_int = int(height)
    except (ValueError, TypeError):
        set_lookup_failure("invalid_height", "height")
        return result

    def valid_hash(value: Any) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    candidate_hash = valid_hash(candidate_block_hash)
    block_hash = candidate_hash
    used_candidate_hash = block_hash is not None

    if block_hash is None:
        block_hash, lookup_meta = daemon_readonly_lookup("getblockhash", [height_int])
        block_hash = valid_hash(block_hash)
    if block_hash is None:
        set_lookup_failure("getblockhash_failed", "getblockhash", locals().get("lookup_meta"))
        return result

    result["blockHash"] = block_hash
    result["resolvedBlockHash"] = block_hash
    block_data, block_lookup_meta = daemon_readonly_lookup("getblock", [block_hash, True])
    if not isinstance(block_data, dict) and used_candidate_hash and allow_height_fallback:
        fallback_block_hash, fallback_meta = daemon_readonly_lookup("getblockhash", [height_int])
        fallback_block_hash = valid_hash(fallback_block_hash)
        if fallback_block_hash and fallback_block_hash != block_hash:
            block_hash = fallback_block_hash
            result["blockHash"] = block_hash
            result["resolvedBlockHash"] = block_hash
            block_data, block_lookup_meta = daemon_readonly_lookup("getblock", [block_hash, True])
    if not isinstance(block_data, dict):
        set_lookup_failure("getblock_failed", "getblock", block_lookup_meta)
        return result

    confirmations = block_data.get("confirmations")
    if confirmations is not None:
        try:
            result["confirmations"] = int(confirmations)
        except (ValueError, TypeError):
            pass

    tx_list = block_data.get("tx")
    if not isinstance(tx_list, list) or not tx_list:
        set_lookup_failure("missing_coinbase_tx", "getblock")
        return result

    coinbase_txid = tx_list[0]
    if isinstance(coinbase_txid, dict):
        coinbase_txid = coinbase_txid.get("txid") or coinbase_txid.get("hash")
    if not isinstance(coinbase_txid, str) or not coinbase_txid:
        set_lookup_failure("invalid_coinbase_txid", "getblock")
        return result

    result["coinbaseTxid"] = coinbase_txid
    result["resolvedCoinbaseTxid"] = coinbase_txid
    coinbase_tx, tx_lookup_meta = daemon_readonly_lookup("getrawtransaction", [coinbase_txid, 1])
    if not isinstance(coinbase_tx, dict):
        set_lookup_failure("getrawtransaction_failed", "getrawtransaction", tx_lookup_meta)
        return result

    vout_list = coinbase_tx.get("vout")
    if not isinstance(vout_list, list):
        set_lookup_failure("missing_coinbase_vout", "getrawtransaction")
        return result

    result.update(detect_coinbase_miner_reward(vout_list))
    result["coinbaseLookupStatus"] = "ok"
    result["coinbaseLookupError"] = None
    return result


def fetch_block_info_from_daemon(block_hash: str) -> tuple[int | None, float | None]:
    block_data = query_rpc("getblock", [block_hash, True])
    if isinstance(block_data, dict):
        confirmations = block_data.get("confirmations")
        if confirmations is not None:
            try:
                confirmations = int(confirmations)
            except (ValueError, TypeError):
                confirmations = None
        return confirmations, None
    return None, None

def generate_payout_candidates(accepted_path: Path, rounds_path: Path, output_path: Path, carry_path: Path | None = None) -> int:
    carry_map = {}
    if carry_path and carry_path.exists():
        try:
            with carry_path.open("r", encoding="utf-8") as f:
                carry_data = json.load(f)
            if isinstance(carry_data, dict) and isinstance(carry_data.get("items"), list):
                for item in carry_data["items"]:
                    if isinstance(item, dict):
                        wallet = item.get("wallet")
                        amount_val = item.get("amount")
                        c_id = item.get("sourceCandidateId")
                        if wallet and amount_val is not None:
                            try:
                                amt = float(amount_val)
                                carry_map.setdefault(wallet, []).append({
                                    "amount": amt,
                                    "sourceCandidateId": c_id
                                })
                            except (ValueError, TypeError):
                                pass
        except Exception:
            carry_map = {}

    try:
        min_payout = float(os.getenv("PEPEPOW_MIN_PAYOUT", "100000.0"))
    except (ValueError, TypeError):
        min_payout = 100000.0

    actions_log_path = output_path.parent / "payment-actions.jsonl"
    paid_pairs = load_paid_payment_pairs(actions_log_path, output_path)

    wallet_carry_state: dict[str, dict[str, Any]] = {}
    for wallet, items in carry_map.items():
        carry_amount = 0.0
        source_ids = []
        for item in items:
            source_candidate_id = item.get("sourceCandidateId")
            if source_candidate_id and (source_candidate_id, wallet) in paid_pairs:
                continue
            try:
                carry_amount += float(item.get("amount") or 0.0)
            except (ValueError, TypeError):
                continue
            if source_candidate_id:
                source_ids.append(source_candidate_id)
        if carry_amount > 0.0 or source_ids:
            wallet_carry_state[wallet] = {
                "amount": carry_amount,
                "sourceCandidateIds": source_ids,
            }

    candidates = []
    if accepted_path.exists():
        try:
            with accepted_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                candidates = data.get("accepted_candidates", [])
        except Exception as exc:
            print(f"Warning: Failed to load accepted candidates: {exc}", file=sys.stderr)

    rounds_map = {}
    if rounds_path.exists():
        try:
            with rounds_path.open("r", encoding="utf-8") as f:
                rounds_data = json.load(f)
            if isinstance(rounds_data, dict):
                for r in rounds_data.get("rounds", []):
                    h = r.get("candidate_hash")
                    if h:
                        rounds_map[h] = r
        except Exception as exc:
            print(f"Warning: Failed to load rounds snapshot: {exc}", file=sys.stderr)

    payout_candidates = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        c_hash = c.get("candidate_hash")
        l_status = c.get("lifecycle_status")
        height = c.get("matched_height")
        explicit_block_hash = c.get("blockHash") or c.get("block_hash")
        candidate_block_hash = explicit_block_hash
        if not candidate_block_hash and isinstance(c_hash, str) and re.fullmatch(r"[0-9a-fA-F]{64}", c_hash):
            candidate_block_hash = c_hash
        block_hash = candidate_block_hash or c_hash
        
        daemon_confirmations = None
        coinbase_txid = None
        resolved_block_hash = None
        resolved_coinbase_txid = None
        coinbase_lookup_status = "not_attempted"
        coinbase_lookup_error = None
        coinbase_lookup_step = None
        coinbase_lookup_method = None
        coinbase_lookup_params_summary = None
        coinbase_lookup_rpc_error_code = None
        coinbase_lookup_rpc_error_message = None
        coinbase_lookup_http_status = None
        coinbase_lookup_exception_type = None
        coinbase_lookup_exception_message = None
        coinbase_total_reward = None
        miner_reward_output_index = None
        miner_reward_amount = None
        masternode_reward_amount = None
        special_reward_amount = None
        coinbase_reward_addresses = []
        miner_reward_addresses = []
        miner_reward_script_pub_key = None
        expected_pool_reward_addr = expected_pool_reward_address()
        coinbase_matches_expected_pool_wallet = None
        excluded_coinbase_outputs = []
        reward_source = None
        if l_status == "confirmed":
            coinbase_reward = fetch_coinbase_reward_from_daemon(
                height,
                candidate_block_hash,
                allow_height_fallback=not bool(explicit_block_hash),
            )
            daemon_confirmations = coinbase_reward.get("confirmations")
            block_hash = coinbase_reward.get("blockHash") or block_hash
            resolved_block_hash = coinbase_reward.get("resolvedBlockHash")
            coinbase_txid = coinbase_reward.get("coinbaseTxid")
            resolved_coinbase_txid = coinbase_reward.get("resolvedCoinbaseTxid")
            coinbase_lookup_status = coinbase_reward.get("coinbaseLookupStatus")
            coinbase_lookup_error = coinbase_reward.get("coinbaseLookupError")
            coinbase_lookup_step = coinbase_reward.get("coinbaseLookupStep")
            coinbase_lookup_method = coinbase_reward.get("coinbaseLookupMethod")
            coinbase_lookup_params_summary = coinbase_reward.get("coinbaseLookupParamsSummary")
            coinbase_lookup_rpc_error_code = coinbase_reward.get("coinbaseLookupRpcErrorCode")
            coinbase_lookup_rpc_error_message = coinbase_reward.get("coinbaseLookupRpcErrorMessage")
            coinbase_lookup_http_status = coinbase_reward.get("coinbaseLookupHttpStatus")
            coinbase_lookup_exception_type = coinbase_reward.get("coinbaseLookupExceptionType")
            coinbase_lookup_exception_message = coinbase_reward.get("coinbaseLookupExceptionMessage")
            coinbase_total_reward = coinbase_reward.get("coinbaseTotalReward")
            miner_reward_output_index = coinbase_reward.get("minerRewardOutputIndex")
            miner_reward_amount = coinbase_reward.get("minerRewardAmount")
            masternode_reward_amount = coinbase_reward.get("masternodeRewardAmount")
            special_reward_amount = coinbase_reward.get("specialRewardAmount")
            coinbase_reward_addresses = coinbase_reward.get("coinbaseRewardAddresses") or []
            miner_reward_addresses = coinbase_reward.get("minerRewardAddresses") or []
            miner_reward_script_pub_key = coinbase_reward.get("minerRewardScriptPubKey")
            expected_pool_reward_addr = coinbase_reward.get("expectedPoolRewardAddress")
            coinbase_matches_expected_pool_wallet = coinbase_reward.get("coinbaseMatchesExpectedPoolWallet")
            excluded_coinbase_outputs = coinbase_reward.get("excludedCoinbaseOutputs") or []
            reward_source = coinbase_reward.get("rewardSource")

        status = "blocked"
        reason = None
        total_block_reward = None
        miner_gross_reward = None
        masternode_reward = None
        dev_fee_reward = None
        gross_reward = None
        net_reward = None
        pool_fee_percent = None
        pool_fee_amount = None
        weight_mode = None
        round_share_total = None
        payouts = []

        followup_status = c.get("followup_status") or c.get("followupStatus")
        is_orphan = l_status == "orphan" or followup_status == "no-match-found"

        is_already_paid = False
        if c_hash in rounds_map:
            r_data = rounds_map[c_hash]
            shares = r_data.get("shares", {})
            if isinstance(shares, dict) and shares:
                if all((c_hash, w) in paid_pairs for w in shares):
                    is_already_paid = True
            else:
                if any(p[0] == c_hash for p in paid_pairs):
                    is_already_paid = True
        else:
            if any(p[0] == c_hash for p in paid_pairs):
                is_already_paid = True

        if is_already_paid:
            status = "blocked"
            reason = "blocked_already_paid"
        elif is_orphan:
            status = "blocked"
            reason = "orphan_block"
        elif l_status != "confirmed":
            status = "blocked"
            if l_status == "immature":
                reason = "immature_block"
            else:
                reason = f"unconfirmed_status_{l_status}"
        else:
            # Enforce validations
            # 1. Coinbase miner reward validation
            try:
                miner_reward_val = float(miner_reward_amount)
            except (ValueError, TypeError):
                miner_reward_val = 0.0

            if miner_reward_val <= 0:
                status = "blocked"
                reason = "blocked_missing_miner_reward_output"
            elif coinbase_matches_expected_pool_wallet is False:
                status = "blocked"
                reason = "blocked_coinbase_reward_mismatch"
            else:
                total_block_reward = coinbase_total_reward
                miner_gross_reward = miner_reward_val
                masternode_reward = masternode_reward_amount
                dev_fee_reward = special_reward_amount
                gross_reward = miner_gross_reward

            if not reason:
                # 2. Candidate hash validation
                if not c_hash:
                    status = "blocked"
                    reason = "missing_candidate_hash"
                # 3. Round validation
                elif c_hash not in rounds_map:
                    status = "blocked"
                    reason = "blocked_missing_round"
                else:
                    r_data = rounds_map[c_hash]
                    shares = r_data.get("shares")
                    # 4. Wallet weights / shares validation
                    if not isinstance(shares, dict) or not shares:
                        status = "blocked"
                        reason = "missing_share_data"
                    else:
                        # 5. Round weight validation
                        try:
                            total_score = float(r_data.get("total_share_score") or 0.0)
                        except (ValueError, TypeError):
                            total_score = 0.0
                        try:
                            total_count = float(r_data.get("total_share_count") or 0.0)
                        except (ValueError, TypeError):
                            total_count = 0.0

                        def sum_share_field(field_name: str) -> float:
                            field_total = 0.0
                            for share_info in shares.values():
                                if not isinstance(share_info, dict):
                                    continue
                                try:
                                    field_total += float(share_info.get(field_name) or 0.0)
                                except (ValueError, TypeError):
                                    continue
                            return field_total

                        if total_score <= 0:
                            total_score = sum_share_field("share_score")
                        if total_count <= 0:
                            total_count = sum_share_field("share_count")

                        weight_mode = "share_difficulty_sum"
                        total_weight = total_score
                        if total_weight <= 0:
                            weight_mode = "accepted_share_count"
                            total_weight = total_count

                        if total_weight <= 0:
                            status = "blocked"
                            reason = "blocked_zero_weight"
                        else:
                            # 6. Internally consistent ready state
                            status = "ready_for_manual_review"
                            round_share_total = total_weight
                            
                            pool_fee_pct = float(os.getenv("PEPEPOW_POOL_FEE_PERCENT", "1.0"))
                            pool_fee_percent = pool_fee_pct
                            pool_fee_amount = miner_gross_reward * pool_fee_pct / 100.0
                            net_reward = miner_gross_reward - pool_fee_amount

                            for wallet, share_info in shares.items():
                                if weight_mode == "share_difficulty_sum":
                                    weight = share_info.get("share_score", 0.0)
                                else:
                                    weight = share_info.get("share_count", 0.0)
                                
                                base_amount = net_reward * weight / total_weight
                                
                                carry_state = wallet_carry_state.get(wallet, {})
                                try:
                                    carry_in_amount = float(carry_state.get("amount") or 0.0)
                                except (ValueError, TypeError):
                                    carry_in_amount = 0.0
                                carry_source_ids = [
                                    source_id
                                    for source_id in carry_state.get("sourceCandidateIds", [])
                                    if source_id != c_hash and (source_id, wallet) not in paid_pairs
                                ]
                                if len(carry_source_ids) != len(carry_state.get("sourceCandidateIds", [])):
                                    carry_in_amount = 0.0
                                    for existing_items in carry_map.get(wallet, []):
                                        source_id = existing_items.get("sourceCandidateId")
                                        if source_id in carry_source_ids:
                                            try:
                                                carry_in_amount += float(existing_items.get("amount") or 0.0)
                                            except (ValueError, TypeError):
                                                pass

                                total_amount = carry_in_amount + base_amount
                                next_source_ids = list(carry_source_ids)
                                if c_hash and (c_hash, wallet) not in paid_pairs:
                                    next_source_ids.append(c_hash)
                                
                                if total_amount >= min_payout:
                                    payout_status = "pending_manual_payment"
                                    payout_amount = total_amount
                                    output_carry_in_amount = carry_in_amount
                                    output_carry_source_ids = next_source_ids
                                    output_carry_source_count = len(output_carry_source_ids)
                                    wallet_carry_state[wallet] = {
                                        "amount": 0.0,
                                        "sourceCandidateIds": [],
                                    }
                                else:
                                    payout_status = "below_threshold_carried"
                                    payout_amount = base_amount
                                    output_carry_in_amount = carry_in_amount
                                    output_carry_source_ids = carry_source_ids
                                    output_carry_source_count = len(output_carry_source_ids)
                                    wallet_carry_state[wallet] = {
                                        "amount": total_amount,
                                        "sourceCandidateIds": next_source_ids,
                                    }
                                    
                                payouts.append({
                                    "wallet": wallet,
                                    "weight": weight,
                                    "amount": payout_amount,
                                    "baseAmount": base_amount,
                                    "carryInAmount": output_carry_in_amount,
                                    "status": payout_status,
                                    "carrySourceCount": output_carry_source_count,
                                    "carrySourceCandidateIds": output_carry_source_ids
                                })

        shares_info = {}
        if c_hash in rounds_map:
            shares_info = rounds_map[c_hash].get("shares", {})

        payout_candidates.append({
            "candidate_hash": c_hash,
            "candidateId": c_hash,
            "blockHash": block_hash,
            "height": height,
            "lifecycle_status": l_status,
            "lifecycleStatus": l_status,
            "status": status,
            "reason": reason,
            "blockedReason": reason,
            "total_block_reward": total_block_reward,
            "totalBlockReward": total_block_reward,
            "masternode_reward": masternode_reward,
            "masternodeReward": masternode_reward,
            "dev_fee_reward": dev_fee_reward,
            "devFeeReward": dev_fee_reward,
            "miner_gross_reward": miner_gross_reward,
            "minerGrossReward": miner_gross_reward,
            "gross_reward": gross_reward,
            "grossReward": gross_reward,
            "net_reward": net_reward,
            "netReward": net_reward,
            "pool_fee_percent": pool_fee_percent,
            "poolFeePercent": pool_fee_percent,
            "pool_fee_amount": pool_fee_amount,
            "poolFeeAmount": pool_fee_amount,
            "weight_mode": weight_mode,
            "weightMode": weight_mode,
            "round_share_total": round_share_total,
            "roundShareTotal": round_share_total,
            "payouts": payouts,
            "shares": shares_info,
            "submit_timestamp": c.get("submit_timestamp"),
            "coinbaseTxid": coinbase_txid,
            "resolvedBlockHash": resolved_block_hash,
            "resolvedCoinbaseTxid": resolved_coinbase_txid,
            "coinbaseLookupStatus": coinbase_lookup_status,
            "coinbaseLookupError": coinbase_lookup_error,
            "coinbaseLookupStep": coinbase_lookup_step,
            "coinbaseLookupMethod": coinbase_lookup_method,
            "coinbaseLookupParamsSummary": coinbase_lookup_params_summary,
            "coinbaseLookupRpcErrorCode": coinbase_lookup_rpc_error_code,
            "coinbaseLookupRpcErrorMessage": coinbase_lookup_rpc_error_message,
            "coinbaseLookupHttpStatus": coinbase_lookup_http_status,
            "coinbaseLookupExceptionType": coinbase_lookup_exception_type,
            "coinbaseLookupExceptionMessage": coinbase_lookup_exception_message,
            "coinbaseTotalReward": coinbase_total_reward,
            "minerRewardOutputIndex": miner_reward_output_index,
            "minerRewardAmount": miner_reward_amount,
            "masternodeRewardAmount": masternode_reward_amount,
            "specialRewardAmount": special_reward_amount,
            "coinbaseRewardAddresses": coinbase_reward_addresses,
            "minerRewardAddresses": miner_reward_addresses,
            "minerRewardScriptPubKey": miner_reward_script_pub_key,
            "expectedPoolRewardAddress": expected_pool_reward_addr,
            "coinbase_matches_expected_pool_wallet": coinbase_matches_expected_pool_wallet,
            "coinbaseMatchesExpectedPoolWallet": coinbase_matches_expected_pool_wallet,
            "excludedCoinbaseOutputs": excluded_coinbase_outputs,
            "reward_source": reward_source,
            "rewardSource": reward_source
        })

    out_data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": payout_candidates
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=output_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(out_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, output_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Error: Failed to write payout candidates atomically: {exc}", file=sys.stderr)
        return 1

    return 0

def generate_payments_snapshot(
    actions_log_path: Path,
    snapshot_path: Path
) -> int:
    existing_actions = []
    if actions_log_path.exists():
        try:
            with actions_log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        act = json.loads(line)
                        if not isinstance(act, dict):
                            continue
                        existing_actions.append(act)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            print(f"Error reading payment actions log: {exc}", file=sys.stderr)
            return 1

    # Load pool snapshot to get current chain height
    pool_snap = load_pool_snapshot()
    current_height = pool_snap.get("network", {}).get("height") if isinstance(pool_snap, dict) else None

    # Load payout-candidates.json to enrich payment items with metadata if available
    candidates_map = {}
    candidates_file = snapshot_path.parent / "payout-candidates.json"
    if candidates_file.exists():
        try:
            with candidates_file.open("r", encoding="utf-8") as f:
                cand_data = json.load(f)
            if isinstance(cand_data, dict) and isinstance(cand_data.get("items"), list):
                for item in cand_data["items"]:
                    c_id = item.get("candidate_hash") or item.get("candidateId")
                    if c_id:
                        candidates_map[c_id] = item
        except Exception:
            pass

    # Load existing payments-snapshot.json to preserve fields and read existing metadata/confirmations
    existing_snapshot_items = {}
    if snapshot_path.exists():
        try:
            with snapshot_path.open("r", encoding="utf-8") as f:
                old_snap = json.load(f)
            if isinstance(old_snap, dict) and isinstance(old_snap.get("items"), list):
                for item in old_snap["items"]:
                    w = item.get("wallet")
                    txid = item.get("txid")
                    if w and txid:
                        existing_snapshot_items[(txid, w)] = item
        except Exception:
            pass

    items_by_payment_key: dict[tuple[str, str], dict[str, Any]] = {}
    for act in existing_actions:
        if not action_represents_successful_payment(act):
            continue

        txid = act.get("txid")
        w = act.get("wallet")
        c_id = act.get("candidate_id")

        # Initial default confirmations
        confirmations = 1

        # Locate existing item if available
        existing_item = existing_snapshot_items.get((txid, w)) if (txid and w) else None
        if existing_item:
            confirmations = existing_item.get("confirmations", 1)

        item = {
            "wallet": w,
            "amount": act.get("amount"),
            "paidAt": act.get("timestamp"),
            "confirmations": confirmations,
            "txid": txid
        }

        cand_meta = candidates_map.get(c_id) if c_id else None

        # Determine block height, candidate hash, block hash, status
        candidate_hash = None
        block_hash = None
        block_height = None
        status = None

        if cand_meta:
            candidate_hash = cand_meta.get("candidate_hash") or cand_meta.get("candidateId")
            block_hash = cand_meta.get("blockHash")
            block_height = cand_meta.get("height")
            status = cand_meta.get("status")
        elif existing_item:
            candidate_hash = existing_item.get("candidateHash")
            block_hash = existing_item.get("blockHash")
            block_height = existing_item.get("blockHeight")
            status = existing_item.get("status")

        # Populate metadata in item if found
        if candidate_hash is not None:
            item["candidateHash"] = candidate_hash
        if block_hash is not None:
            item["blockHash"] = block_hash
        if block_height is not None:
            item["blockHeight"] = block_height
        if status is not None:
            item["status"] = status

        # Recompute confirmations if blockHeight and currentHeight are available
        if current_height is not None and block_height is not None:
            try:
                h_val = int(block_height)
                item["confirmations"] = max(0, int(current_height) - h_val + 1)
            except (ValueError, TypeError):
                pass

        if txid and w:
            items_by_payment_key[(str(txid), str(w))] = item
        else:
            items_by_payment_key[(str(id(act)), "")] = item

    # Sort descending by paidAt
    items = list(items_by_payment_key.values())
    items.sort(key=lambda x: x.get("paidAt", ""), reverse=True)

    snapshot_data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items
    }

    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=snapshot_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(snapshot_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, snapshot_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Error writing payments snapshot atomically: {exc}", file=sys.stderr)
        return 1

    return 0

def clear_consumed_carry(candidates_path: Path, carry_path: Path, candidate_id: str, wallet: str) -> None:
    if not candidates_path.exists() or not carry_path.exists():
        return

    payout_row = None
    try:
        with candidates_path.open("r", encoding="utf-8") as f:
            cand_data = json.load(f)
        if isinstance(cand_data, dict) and isinstance(cand_data.get("items"), list):
            for item in cand_data["items"]:
                c_id = item.get("candidateId") or item.get("candidate_hash")
                if c_id == candidate_id:
                    payouts = item.get("payouts")
                    if isinstance(payouts, list):
                        for p in payouts:
                            if isinstance(p, dict) and p.get("wallet") == wallet:
                                payout_row = p
                                break
                    break
    except Exception:
        return

    if not payout_row:
        return

    carry_in = payout_row.get("carryInAmount", 0.0)
    carry_source_ids = payout_row.get("carrySourceCandidateIds")
    if not (carry_in and isinstance(carry_in, (int, float)) and carry_in > 0) or not isinstance(carry_source_ids, list) or not carry_source_ids:
        return

    try:
        with carry_path.open("r", encoding="utf-8") as f:
            carry_data = json.load(f)
        if not isinstance(carry_data, dict) or not isinstance(carry_data.get("items"), list):
            return
    except Exception:
        return

    orig_items = carry_data["items"]
    new_items = []
    for item in orig_items:
        if not isinstance(item, dict):
            continue
        w = item.get("wallet")
        src_id = item.get("sourceCandidateId")
        if w == wallet and src_id in carry_source_ids:
            continue
        new_items.append(item)

    carry_data["items"] = new_items
    carry_data["generatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        carry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=carry_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(carry_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, carry_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Warning: Failed to update carry snapshot atomically: {exc}", file=sys.stderr)

def record_payment(
    actions_log_path: Path,
    snapshot_path: Path,
    candidate_id: str,
    wallet: str,
    amount: float,
    txid: str
) -> int:
    pattern = re.compile(r"^[A-Za-z0-9]{26,128}$")

    if not pattern.match(candidate_id):
        print(f"Error: Invalid candidate_id format (must be 26-128 chars alphanumeric): {candidate_id}", file=sys.stderr)
        return 1
    if not pattern.match(wallet):
        print(f"Error: Invalid wallet address format (must be 26-128 chars alphanumeric): {wallet}", file=sys.stderr)
        return 1
    if not pattern.match(txid):
        print(f"Error: Invalid txid format (must be 26-128 chars alphanumeric): {txid}", file=sys.stderr)
        return 1
    if amount <= 0:
        print(f"Error: Amount must be positive: {amount}", file=sys.stderr)
        return 1

    existing_actions = []
    if actions_log_path.exists():
        try:
            with actions_log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        act = json.loads(line)
                        if not isinstance(act, dict):
                            continue
                        if (
                            act.get("candidate_id") == candidate_id
                            and act.get("wallet") == wallet
                            and action_represents_successful_payment(act)
                        ):
                            print(f"Error: Duplicate payment rejected. Wallet {wallet} has already been paid for candidate {candidate_id}.", file=sys.stderr)
                            return 1
                        existing_actions.append(act)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            print(f"Error reading payment actions log: {exc}", file=sys.stderr)
            return 1

    new_action = {
        "candidate_id": candidate_id,
        "wallet": wallet,
        "amount": amount,
        "txid": txid,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

    try:
        actions_log_path.parent.mkdir(parents=True, exist_ok=True)
        with actions_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(new_action) + "\n")
    except Exception as exc:
        print(f"Error writing to payment actions log: {exc}", file=sys.stderr)
        return 1

    # Clear consumed carry if any
    candidates_path = snapshot_path.parent / "payout-candidates.json"
    carry_path = snapshot_path.parent / "payout-carry-snapshot.json"
    clear_consumed_carry(candidates_path, carry_path, candidate_id, wallet)

    return generate_payments_snapshot(actions_log_path, snapshot_path)

def generate_carry_snapshot(candidates_path: Path, output_path: Path) -> int:
    items = []
    malformed = False

    if candidates_path.exists():
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                malformed = True
            else:
                cands = data.get("items")
                if cands is None:
                    cands = data.get("candidates")
                if not isinstance(cands, list):
                    malformed = True
                else:
                    seen = set()
                    for c in cands:
                        if not isinstance(c, dict):
                            malformed = True
                            break
                        c_id = c.get("candidateId") or c.get("candidate_hash")
                        height = c.get("height")
                        block_hash = c.get("blockHash") or c.get("candidate_hash")
                        
                        # Validate candidate metadata
                        if not c_id or height is None or not block_hash:
                            malformed = True
                            break
                        try:
                            height_val = int(height)
                        except (ValueError, TypeError):
                            malformed = True
                            break
                            
                        payouts = c.get("payouts")
                        if not isinstance(payouts, list):
                            malformed = True
                            break
                        
                        for p in payouts:
                            if not isinstance(p, dict):
                                malformed = True
                                break
                            wallet = p.get("wallet")
                            amount = p.get("amount")
                            status = p.get("status")
                            if not wallet or amount is None or not status:
                                malformed = True
                                break
                            try:
                                amount_val = float(amount)
                            except (ValueError, TypeError):
                                malformed = True
                                break
                                
                            if status in ("below_threshold", "below_threshold_carried"):
                                pair = (wallet, c_id)
                                if pair not in seen:
                                    seen.add(pair)
                                    items.append({
                                        "wallet": wallet,
                                        "amount": amount_val,
                                        "sourceCandidateId": c_id,
                                        "sourceBlockHeight": height_val,
                                        "sourceBlockHash": block_hash,
                                        "status": "below_threshold_carried"
                                    })
        except Exception:
            malformed = True

    if malformed:
        items = []

    # Sort items deterministically
    items.sort(key=lambda x: (x["wallet"], x["sourceCandidateId"]))

    out_data = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=output_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(out_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, output_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Error: Failed to write carry snapshot atomically: {exc}", file=sys.stderr)
        return 1

    return 0

def run_carry_audit_logic(candidates_path: Path, carry_path: Path, payments_path: Path) -> dict[str, Any]:
    issues = []
    malformed_input = False
    carry_items = []
    candidate_items = []
    payment_items = []
    duplicate_carry_count = 0
    paid_carry_still_present_count = 0
    orphan_or_blocked_carry_count = 0

    # 1. Parse carry snapshot
    if not carry_path.exists():
        issues.append(f"Carry snapshot file not found: {carry_path}")
        malformed_input = True
    else:
        try:
            with carry_path.open("r", encoding="utf-8") as f:
                carry_data = json.load(f)
            if not isinstance(carry_data, dict) or not isinstance(carry_data.get("items"), list):
                issues.append("Carry snapshot is not a valid dict or lacks items list")
                malformed_input = True
            else:
                carry_items = carry_data["items"]
        except Exception as exc:
            issues.append(f"Failed to parse carry snapshot as JSON: {exc}")
            malformed_input = True

    # 2. Parse candidates snapshot
    if not candidates_path.exists():
        issues.append(f"Candidates file not found: {candidates_path}")
        malformed_input = True
    else:
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                cand_data = json.load(f)
            if not isinstance(cand_data, dict):
                issues.append("Candidates data is not a valid dict")
                malformed_input = True
            else:
                cands = cand_data.get("items")
                if cands is None:
                    cands = cand_data.get("candidates")
                if not isinstance(cands, list):
                    issues.append("Candidates data lacks a valid items or candidates list")
                    malformed_input = True
                else:
                    candidate_items = cands
        except Exception as exc:
            issues.append(f"Failed to parse candidates data as JSON: {exc}")
            malformed_input = True

    # 3. Parse payments snapshot
    if not payments_path.exists():
        issues.append(f"Payments snapshot file not found: {payments_path}")
        malformed_input = True
    else:
        try:
            with payments_path.open("r", encoding="utf-8") as f:
                payments_data = json.load(f)
            if not isinstance(payments_data, dict) or not isinstance(payments_data.get("items"), list):
                issues.append("Payments snapshot is not a valid dict or lacks items list")
                malformed_input = True
            else:
                payment_items = payments_data["items"]
        except Exception as exc:
            issues.append(f"Failed to parse payments snapshot as JSON: {exc}")
            malformed_input = True

    # Run audit logic if inputs parsed successfully
    if not malformed_input:
        # A. Duplicate carry check
        seen_carry = set()
        for idx, item in enumerate(carry_items):
            if not isinstance(item, dict):
                issues.append(f"Carry item at index {idx} is not a dict")
                continue
            wallet = item.get("wallet")
            src_id = item.get("sourceCandidateId")
            if not wallet or not src_id:
                issues.append(f"Carry item at index {idx} is missing wallet or sourceCandidateId")
                continue
            pair = (wallet, src_id)
            if pair in seen_carry:
                duplicate_carry_count += 1
                issues.append(f"Duplicate carry item found for wallet {wallet} and candidate {src_id}")
            seen_carry.add(pair)

        # B. Paid carry still present check
        paid_pairs = set()
        for idx, item in enumerate(payment_items):
            if not isinstance(item, dict):
                continue
            wallet = item.get("wallet")
            c_id = item.get("candidateId") or item.get("candidateHash")
            if wallet and c_id:
                paid_pairs.add((wallet, c_id))

        for idx, item in enumerate(carry_items):
            if not isinstance(item, dict):
                continue
            wallet = item.get("wallet")
            src_id = item.get("sourceCandidateId")
            if wallet and src_id:
                if (wallet, src_id) in paid_pairs:
                    paid_carry_still_present_count += 1
                    issues.append(f"Carry item for wallet {wallet} and source candidate {src_id} is still present in carry snapshot but is already recorded as paid")

        # C. Carry item from blocked/orphan/immature/unconfirmed candidate check
        cand_status_map = {}
        cand_lifecycle_map = {}
        for idx, item in enumerate(candidate_items):
            if not isinstance(item, dict):
                continue
            c_id = item.get("candidateId") or item.get("candidate_hash")
            status = item.get("status")
            l_status = item.get("lifecycleStatus") or item.get("lifecycle_status")
            if c_id:
                cand_status_map[c_id] = status
                cand_lifecycle_map[c_id] = l_status

        for idx, item in enumerate(carry_items):
            if not isinstance(item, dict):
                continue
            wallet = item.get("wallet")
            src_id = item.get("sourceCandidateId")
            if wallet and src_id:
                if src_id in cand_status_map:
                    status = cand_status_map[src_id]
                    l_status = cand_lifecycle_map.get(src_id)
                    is_blocked = (status == "blocked")
                    is_not_confirmed = (l_status not in ("confirmed", None))
                    if is_blocked or is_not_confirmed:
                        orphan_or_blocked_carry_count += 1
                        issues.append(f"Carry item for wallet {wallet} originates from a blocked/orphan/immature candidate {src_id} (status: {status}, lifecycleStatus: {l_status})")

        # D. Candidate payout with carryInAmount > 0 but missing carrySourceCandidateIds check
        for idx, item in enumerate(candidate_items):
            if not isinstance(item, dict):
                continue
            c_id = item.get("candidateId") or item.get("candidate_hash")
            payouts = item.get("payouts")
            if isinstance(payouts, list):
                for p_idx, p in enumerate(payouts):
                    if not isinstance(p, dict):
                        continue
                    wallet = p.get("wallet")
                    carry_in = p.get("carryInAmount", 0.0)
                    carry_source_ids = p.get("carrySourceCandidateIds")
                    if carry_in and carry_in > 0:
                        if not isinstance(carry_source_ids, list) or not carry_source_ids:
                            issues.append(f"Candidate {c_id} payout for wallet {wallet} has carryInAmount > 0 but missing or empty carrySourceCandidateIds")

    result = {
        "status": "ok" if not issues and not malformed_input else "warning",
        "issues": issues,
        "summary": {
            "carryItems": len(carry_items),
            "candidateItems": len(candidate_items),
            "paymentItems": len(payment_items),
            "duplicateCarryItems": duplicate_carry_count,
            "paidCarryStillPresent": paid_carry_still_present_count,
            "orphanOrBlockedCarryItems": orphan_or_blocked_carry_count,
            "malformedInput": malformed_input
        }
    }
    return result

def audit_carry_consistency(candidates_path: Path, carry_path: Path, payments_path: Path) -> int:
    result = run_carry_audit_logic(candidates_path, carry_path, payments_path)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "warning" else 0

def payout_review(candidates_path: Path, carry_path: Path, payments_path: Path, as_json: bool = False) -> int:
    candidates = []
    updated_at = "unknown"
    malformed_candidates = False
    
    if candidates_path.exists():
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                updated_at = data.get("updated_at") or data.get("generatedAt") or "unknown"
                candidates = data.get("items") if "items" in data else data.get("candidates", [])
                if not isinstance(candidates, list):
                    candidates = []
                    malformed_candidates = True
            else:
                malformed_candidates = True
        except Exception:
            malformed_candidates = True
    else:
        malformed_candidates = True

    # Compute Carry Status Summary
    carry_items_count = 0
    carry_total_amount = 0.0
    wallets_with_carry = []
    
    if carry_path.exists():
        try:
            with carry_path.open("r", encoding="utf-8") as f:
                carry_data = json.load(f)
            if isinstance(carry_data, dict) and isinstance(carry_data.get("items"), list):
                items = carry_data["items"]
                carry_items_count = len(items)
                unique_wallets = set()
                for item in items:
                    if isinstance(item, dict):
                        amt = item.get("amount", 0.0)
                        try:
                            carry_total_amount += float(amt)
                        except (ValueError, TypeError):
                            pass
                        wallet = item.get("wallet")
                        if wallet:
                            unique_wallets.add(wallet)
                wallets_with_carry = sorted(list(unique_wallets))
        except Exception:
            pass

    candidate_carry_applied_amount = 0.0
    candidate_payouts_with_carry_count = 0
    
    for c in candidates:
        if isinstance(c, dict):
            payouts = c.get("payouts")
            if isinstance(payouts, list):
                for p in payouts:
                    if isinstance(p, dict):
                        carry_in = p.get("carryInAmount", 0.0)
                        if carry_in and carry_in > 0:
                            try:
                                candidate_carry_applied_amount += float(carry_in)
                                candidate_payouts_with_carry_count += 1
                            except (ValueError, TypeError):
                                pass

    carry_audit_status = "unknown"
    try:
        audit_res = run_carry_audit_logic(candidates_path, carry_path, payments_path)
        carry_audit_status = audit_res.get("status", "unknown")
    except Exception:
        pass

    payment_rows_count = 0
    if payments_path.exists():
        try:
            with payments_path.open("r", encoding="utf-8") as f:
                p_data = json.load(f)
            if isinstance(p_data, dict) and isinstance(p_data.get("items"), list):
                payment_rows_count = len(p_data["items"])
        except Exception:
            pass

    payout_review_status = "ok"
    if malformed_candidates or not carry_path.exists() or not payments_path.exists() or carry_audit_status != "ok":
        payout_review_status = "warning"

    if as_json:
        # Load pool snapshot for network height and confirmations
        pool_snap = load_pool_snapshot()
        snap_blocks = pool_snap.get("blocks", [])
        current_height = pool_snap.get("network", {}).get("height") if isinstance(pool_snap, dict) else None
        
        confirmations_map = {}
        if isinstance(snap_blocks, list):
            for sb in snap_blocks:
                if isinstance(sb, dict):
                    h_hash = sb.get("hash")
                    h_conf = sb.get("confirmations")
                    if h_hash and h_conf is not None:
                        try:
                            confirmations_map[h_hash] = int(h_conf)
                        except (ValueError, TypeError):
                            pass
                            
        json_items = []
        ready_candidates_count = 0
        blocked_candidates_count = 0
        
        for c in candidates:
            if not isinstance(c, dict):
                continue
            c_hash = c.get("candidate_hash") or c.get("candidateId")
            c_height = c.get("height")
            status = c.get("status")
            
            if status in ("eligible", "ready_for_manual_review"):
                ready_candidates_count += 1
            elif status == "blocked":
                blocked_candidates_count += 1
                
            conf = confirmations_map.get(c_hash)
            if conf is None and current_height is not None and c_height is not None:
                try:
                    conf = max(0, int(current_height) - int(c_height) + 1)
                except (ValueError, TypeError):
                    pass
            
            payouts = c.get("payouts")
            carry_applied = 0.0
            payout_count = 0
            if isinstance(payouts, list):
                payout_count = len(payouts)
                for p in payouts:
                    if isinstance(p, dict):
                        try:
                            carry_applied += float(p.get("carryInAmount", 0.0))
                        except (ValueError, TypeError):
                            pass

            net_reward = c.get("netReward") or c.get("net_reward")
            if net_reward is not None:
                try:
                    net_reward = float(net_reward)
                except (ValueError, TypeError):
                    pass
            
            json_items.append({
                "candidateId": c_hash,
                "blockHeight": c_height,
                "blockHash": c.get("blockHash") or c_hash,
                "status": status,
                "lifecycleStatus": c.get("lifecycleStatus") or c.get("lifecycle_status"),
                "confirmations": conf,
                "netReward": net_reward,
                "payoutCount": payout_count,
                "blockedReason": c.get("blockedReason") or c.get("reason"),
                "carryAppliedAmount": carry_applied
            })

        out = {
            "status": payout_review_status,
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "summary": {
                "candidateItems": len(candidates),
                "readyCandidates": ready_candidates_count,
                "blockedCandidates": blocked_candidates_count,
                "paymentRows": payment_rows_count,
                "carryItems": carry_items_count,
                "carryTotalAmount": carry_total_amount,
                "walletsWithCarry": wallets_with_carry,
                "candidatePayoutsWithCarry": candidate_payouts_with_carry_count,
                "candidateCarryAppliedAmount": candidate_carry_applied_amount,
                "carryAuditStatus": carry_audit_status
            },
            "items": json_items
        }
        print(json.dumps(out, indent=2))
        return 0

    # Print candidates review headers and details (preserving text behavior)
    print(f"Payout Candidates (Last updated: {updated_at})")
    print("="*80)
    if not candidates:
        print("No candidates found.")
    else:
        for c in candidates:
            if not isinstance(c, dict):
                continue
            h = c.get("candidate_hash") or c.get("candidateId")
            status = c.get("status")
            reason = c.get("reason") or c.get("blockedReason")
            height = c.get("height")
            lifecycle = c.get("lifecycle_status") or c.get("lifecycleStatus")
            print(f"Candidate: {h} (Height: {height}, Lifecycle: {lifecycle})")
            status_str = str(status).upper() if status else "UNKNOWN"
            reason_str = f" (Reason: {reason})" if reason else ""
            print(f"  Payout Status: {status_str}{reason_str}")
            if status in ("eligible", "ready_for_manual_review"):
                shares = c.get("shares", {})
                if isinstance(shares, dict):
                    print("  Shares breakdown:")
                    for wallet, info in shares.items():
                        if isinstance(info, dict):
                            pct = info.get("share_percent", 0.0)
                            score = info.get("share_score", 0.0)
                            cnt = info.get("share_count", 0)
                            print(f"    - {wallet}: {pct}% (Count: {cnt}, Score: {score})")
            print("-"*80)

    # Compute ready_payment_total: sum of pending_manual_payment payout amounts across all candidates
    ready_payment_total = 0.0
    for c in candidates:
        if not isinstance(c, dict):
            continue
        payouts = c.get("payouts")
        if isinstance(payouts, list):
            for p in payouts:
                if isinstance(p, dict) and p.get("status") == "pending_manual_payment":
                    try:
                        ready_payment_total += float(p.get("amount", 0.0))
                    except (ValueError, TypeError):
                        pass

    # blocked_candidates_count is computed earlier in the JSON branch; recompute for text branch
    _blocked_count = sum(1 for c in candidates if isinstance(c, dict) and c.get("status") == "blocked")

    print("Carry Status Summary")
    print("="*80)
    print(f"ready_payment_total: {ready_payment_total}")
    print(f"below_threshold_carry_total: {carry_total_amount}")
    print(f"wallet_carry_count: {len(wallets_with_carry)}")
    print(f"blocked_candidates: {_blocked_count}")
    print(f"carry_audit_status: {carry_audit_status}")
    print("="*80)
    return 0

def payout_review_check(candidates_path: Path, carry_path: Path, payments_path: Path) -> int:
    """Read-only payout review check for cron/monitoring.

    Consumes the same JSON data path as ``payout_review(..., as_json=True)``.
    Does not write any files, does not call wallet RPC, does not record payment.

    Exit codes:
        0 - ready or no-ready-candidates (status ok)
        1 - warning (malformed/missing input)
        2 - unexpected internal error
    """
    try:
        # --- Gather payout_review JSON internally (no subprocess, no text parsing) ---
        import io as _io
        buf = _io.StringIO()
        _old_stdout = sys.stdout
        sys.stdout = buf
        try:
            payout_review(candidates_path, carry_path, payments_path, as_json=True)
        finally:
            sys.stdout = _old_stdout
        raw = buf.getvalue().strip()
        if not raw:
            print("payout_review_check: warning")
            print("status: warning")
            print("carry_audit_status: warning")
            return 1
        review = json.loads(raw)
    except Exception:
        print("payout_review_check: warning")
        print("status: warning")
        print("carry_audit_status: warning")
        return 1

    try:
        summary = review.get("summary", {})
        status = review.get("status", "warning")
        ready_candidates = summary.get("readyCandidates", 0)
        blocked_candidates = summary.get("blockedCandidates", 0)
        carry_items = summary.get("carryItems", 0)
        carry_total_amount = summary.get("carryTotalAmount", 0.0)
        carry_audit_status = summary.get("carryAuditStatus", "unknown")

        if status != "ok":
            print("payout_review_check: warning")
            print("status: warning")
            print(f"carry_audit_status: {carry_audit_status}")
            return 1

        if ready_candidates > 0:
            check_label = "ready"
        else:
            check_label = "no-ready-candidates"

        print(f"payout_review_check: {check_label}")
        print(f"status: ok")
        print(f"ready_candidates: {ready_candidates}")
        print(f"blocked_candidates: {blocked_candidates}")
        print(f"carry_items: {carry_items}")
        print(f"carry_total_amount: {carry_total_amount}")
        print(f"carry_audit_status: {carry_audit_status}")
        return 0
    except Exception:
        print("payout_review_check: warning")
        print("status: warning")
        print("carry_audit_status: warning")
        return 1

def payout_wallet_dry_run(candidates_path: Path, output_path: Path) -> int:
    """Dry-run wallet payout validation and balance checking.
    Does not send funds. Does not call transaction-sending or wallet-unlock commands.
    """
    # TODO(security): Safety check - ensure we never execute real transactions.
    # We strictly enforce read-only commands (getbalance, getwalletinfo, validateaddress).
    
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Check RPC endpoint and wallet balance
    wallet_balance_read_ok = False
    wallet_available_balance = 0.0
    warnings = []
    
    # Try calling getbalance or getwalletinfo via query_rpc
    try:
        balance_res = wallet_readonly_call("getbalance", [])
        if balance_res is not None:
            wallet_available_balance = float(balance_res)
            wallet_balance_read_ok = True
        else:
            wallet_info = wallet_readonly_call("getwalletinfo", [])
            if isinstance(wallet_info, dict) and "balance" in wallet_info:
                wallet_available_balance = float(wallet_info["balance"])
                wallet_balance_read_ok = True
    except Exception:
        pass
        
    if not wallet_balance_read_ok:
        warnings.append("Wallet RPC unreachable or balance unreadable")

    pattern = re.compile(r"^[A-Za-z0-9]{26,128}$")
    
    candidates = []
    if candidates_path.exists():
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                candidates = data.get("items") or data.get("candidates") or []
        except Exception as exc:
            warnings.append(f"Failed to read candidates file: {exc}")

    if not isinstance(candidates, list):
        candidates = []
        warnings.append("Malformed candidates file structure")

    items = []
    blocked_items_count = 0
    total_ready_amount = 0.0
    
    # Validate each candidate and its payouts
    for c in candidates:
        if not isinstance(c, dict):
            blocked_items_count += 1
            continue
            
        c_id = c.get("candidateId") or c.get("candidate_hash")
        height = c.get("height")
        block_hash = c.get("blockHash") or c.get("candidate_hash")
        c_status = c.get("status")
        payouts = c.get("payouts")
        
        # Check if candidate is structurally malformed
        cand_malformed = False
        if not c_id or height is None or not block_hash or not c_status:
            cand_malformed = True
            
        try:
            height_val = int(height) if height is not None else 0
        except (ValueError, TypeError):
            cand_malformed = True
            height_val = 0
            
        if not isinstance(payouts, list):
            blocked_items_count += 1
            continue
            
        for p in payouts:
            if not isinstance(p, dict):
                blocked_items_count += 1
                continue
                
            p_status = p.get("status")
            # Only process payouts with status pending_manual_payment
            if p_status != "pending_manual_payment":
                continue
                
            wallet = p.get("wallet")
            amount = p.get("amount")
            carry_source_ids = p.get("carrySourceCandidateIds")
            if carry_source_ids is None and "sourceCandidateIds" in p:
                carry_source_ids = p.get("sourceCandidateIds")
            carry_source_count = p.get("carrySourceCount")
            if carry_source_count is None and isinstance(carry_source_ids, list):
                carry_source_count = len(carry_source_ids)
            
            payout_item = {
                "candidateId": c_id or "",
                "wallet": wallet or "",
                "amount": amount,
                "status": "ready_for_wallet_send_preview",
                "validationMode": "local",
                "rpcWouldSend": False,
                "baseAmount": p.get("baseAmount"),
                "carryInAmount": p.get("carryInAmount"),
                "carrySourceCount": carry_source_count,
                "carrySourceCandidateIds": carry_source_ids,
            }
            if "sourceCandidateIds" in p:
                payout_item["sourceCandidateIds"] = p.get("sourceCandidateIds")
            
            # 1. Structural/Metadata validation
            if cand_malformed:
                payout_item["status"] = "blocked_malformed_candidate"
                blocked_items_count += 1
                items.append(payout_item)
                continue
                
            # Pattern check for ID and hashes
            if not pattern.match(c_id) or not pattern.match(block_hash):
                payout_item["status"] = "blocked_invalid_candidate"
                blocked_items_count += 1
                items.append(payout_item)
                continue
                
            if height_val <= 0:
                payout_item["status"] = "blocked_invalid_block_height"
                blocked_items_count += 1
                items.append(payout_item)
                continue
                
            # Validate amount
            try:
                amt_val = float(amount) if amount is not None else 0.0
            except (ValueError, TypeError):
                amt_val = 0.0
            if amt_val <= 0.0:
                payout_item["status"] = "blocked_invalid_amount"
                blocked_items_count += 1
                items.append(payout_item)
                continue
                
            # Validate wallet address string presence & basic local pattern check
            if not wallet or not isinstance(wallet, str):
                payout_item["status"] = "blocked_invalid_address"
                blocked_items_count += 1
                items.append(payout_item)
                continue
                
            # 2. Address validation via RPC validateaddress if reachable
            is_valid_address = False
            validation_mode = "local"
            
            # Try validateaddress RPC call
            try:
                rpc_val = wallet_readonly_call("validateaddress", [wallet])
                if isinstance(rpc_val, dict) and "isvalid" in rpc_val:
                    is_valid_address = bool(rpc_val["isvalid"])
                    validation_mode = "rpc"
            except Exception:
                pass
                
            if validation_mode == "local":
                is_valid_address = bool(pattern.match(wallet))
                
            payout_item["validationMode"] = validation_mode
            
            if not is_valid_address:
                payout_item["status"] = "blocked_invalid_address"
                blocked_items_count += 1
                items.append(payout_item)
                continue
                
            # If all validations pass, this item is a candidate for wallet send
            total_ready_amount += amt_val
            items.append(payout_item)

    # 3. Sufficient Balance Check
    if wallet_balance_read_ok:
        insufficient_balance = total_ready_amount > wallet_available_balance
    else:
        insufficient_balance = True
        warnings.append("Insufficient balance check skipped: wallet balance unreadable")
        
    # Apply insufficient balance blocking if needed
    ready_count = 0
    for item in items:
        # Only modify the status of items that are currently "ready_for_wallet_send_preview"
        if item["status"] == "ready_for_wallet_send_preview":
            if insufficient_balance:
                item["status"] = "blocked_insufficient_balance"
                blocked_items_count += 1
            else:
                ready_count += 1

    # Add warning about balance if insufficient
    if wallet_balance_read_ok and insufficient_balance:
        warnings.append("Insufficient wallet balance for ready payouts")

    # Generate snapshot data
    out_data = {
        "generatedAt": generated_at,
        "mode": "dry_run",
        "realSendEnabled": False,
        "totalReadyAmount": total_ready_amount,
        "walletAvailableBalance": wallet_available_balance,
        "readyCount": ready_count,
        "blockedCount": blocked_items_count,
        "walletBalanceReadOk": wallet_balance_read_ok,
        "insufficientBalance": insufficient_balance,
        "item count": len(items),
        "blocked items": blocked_items_count,
        "warnings": warnings,
        "items": items
    }
    
    # Write atomically
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=output_path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(out_data, f, indent=2, sort_keys=True)
            os.replace(temp_path, output_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as exc:
        print(f"Error: Failed to write dry-run snapshot atomically: {exc}", file=sys.stderr)
        return 1

    # Output short review summary
    print("Payout Wallet Dry-Run Summary")
    print("="*80)
    print(f"dry_run_status: {'warning' if insufficient_balance or not wallet_balance_read_ok or warnings else 'success'}")
    print(f"ready_count: {ready_count}")
    print(f"blocked_count: {blocked_items_count}")
    print(f"total_ready_amount: {total_ready_amount}")
    print(f"wallet_balance_read_ok: {str(wallet_balance_read_ok).lower()}")
    print(f"wallet_available_balance: {wallet_available_balance}")
    print(f"insufficient_balance: {str(insufficient_balance).lower()}")
    print(f"artifact_path: {output_path}")
    print("="*80)
    
    return 0


def payout_wallet_send_preflight(
    candidates_path: Path,
    actions_log_path: Path,
    output_path: Path,
    candidate_id: str,
    wallet: str,
    amount: float,
) -> int:
    """Preflight one-shot wallet payout send guards without sending funds."""
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    env = load_env_vars()
    enabled_raw = env.get("PEPEPOW_ENABLE_REAL_WALLET_PAYOUT", "false")
    max_sends_raw = env.get("PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS")
    real_enabled = enabled_raw.strip().lower() == "true"
    warnings: list[str] = []
    send_would_be_allowed = False
    status = "unknown"

    try:
        max_sends: int | None = int(max_sends_raw) if max_sends_raw is not None else None
    except (TypeError, ValueError):
        max_sends = None

    def result_payload() -> dict[str, Any]:
        return {
            "generatedAt": generated_at,
            "mode": "send_preflight",
            "realWalletPayoutEnabled": real_enabled,
            "maxSends": max_sends,
            "sendWouldBeAllowed": send_would_be_allowed,
            "sendAttempted": False,
            "sendSent": False,
            "candidateId": candidate_id,
            "wallet": wallet,
            "amount": amount,
            "status": status,
            "warnings": warnings,
        }

    def finish(finish_status: str) -> int:
        nonlocal status, send_would_be_allowed
        status = finish_status
        send_would_be_allowed = status == "preflight_ok" and real_enabled and max_sends == 1
        try:
            atomic_write_json(output_path, result_payload())
        except Exception as exc:
            print(f"Error: Failed to write send-preflight result atomically: {exc}", file=sys.stderr)
            return 1
        print("Payout Wallet Send-Preflight Summary")
        print("="*80)
        print(f"preflight_status: {status}")
        print(f"real_wallet_payout_enabled: {str(real_enabled).lower()}")
        print(f"max_sends: {max_sends if max_sends is not None else 'invalid'}")
        print(f"send_would_be_allowed: {str(send_would_be_allowed).lower()}")
        print("send_attempted: false")
        print("send_sent: false")
        print(f"candidate_id: {candidate_id}")
        print(f"wallet: {wallet}")
        print(f"amount: {amount}")
        print(f"artifact_path: {output_path}")
        print("="*80)
        return 0

    if max_sends != 1:
        return finish("blocked_invalid_send_budget")

    try:
        expected_amount = float(amount)
    except (TypeError, ValueError):
        return finish("blocked_amount_mismatch")
    if expected_amount <= 0:
        return finish("blocked_amount_mismatch")

    candidates: list[Any] = []
    if candidates_path.exists():
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                loaded = data.get("items") or data.get("candidates") or []
                if isinstance(loaded, list):
                    candidates = loaded
        except Exception as exc:
            warnings.append(f"Failed to read payout candidates: {exc}")
    else:
        warnings.append("Payout candidates snapshot missing")

    matching_candidate = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        c_id = candidate.get("candidateId") or candidate.get("candidate_hash")
        if c_id == candidate_id:
            matching_candidate = candidate
            break

    if matching_candidate is None:
        return finish("blocked_candidate_not_found")

    payouts = matching_candidate.get("payouts")
    if not isinstance(payouts, list):
        return finish("blocked_wallet_not_in_candidate")

    matching_payout = None
    for payout in payouts:
        if isinstance(payout, dict) and payout.get("wallet") == wallet:
            matching_payout = payout
            break

    if matching_payout is None:
        return finish("blocked_wallet_not_in_candidate")

    if matching_payout.get("status") not in {"pending_manual_payment", "ready_for_wallet_send_preview"}:
        return finish("blocked_payout_not_ready")

    try:
        payout_amount = float(matching_payout.get("amount"))
    except (TypeError, ValueError):
        return finish("blocked_amount_mismatch")

    if abs(payout_amount - expected_amount) > 1e-8:
        return finish("blocked_amount_mismatch")

    if payment_already_recorded(actions_log_path, candidate_id, wallet):
        return finish("blocked_already_paid")

    balance_res = wallet_readonly_call("getbalance", [])
    try:
        wallet_balance = float(balance_res) if balance_res is not None else None
    except (TypeError, ValueError):
        wallet_balance = None
    if wallet_balance is None:
        return finish("blocked_wallet_balance_unreadable")
    if expected_amount > wallet_balance:
        return finish("blocked_insufficient_balance")

    address_res = wallet_readonly_call("validateaddress", [wallet])
    if not (isinstance(address_res, dict) and address_res.get("isvalid") is True):
        return finish("blocked_invalid_address")

    return finish("preflight_ok")


def payout_wallet_send_once(
    candidates_path: Path,
    actions_log_path: Path,
    payments_snapshot_path: Path,
    output_path: Path,
    candidate_id: str,
    wallet: str,
    amount: float,
) -> int:
    """Guarded one-shot wallet payout sender.
    Sends only when explicitly enabled and all candidate, duplicate, wallet, and budget guards pass.
    """
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    env = load_env_vars()
    enabled_raw = env.get("PEPEPOW_ENABLE_REAL_WALLET_PAYOUT", "false")
    max_sends_raw = env.get("PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS")
    real_enabled = enabled_raw.strip().lower() == "true"
    warnings: list[str] = []
    send_attempted = False
    send_sent = False
    txid: str | None = None
    status = "unknown"

    try:
        max_sends: int | None = int(max_sends_raw) if max_sends_raw is not None else None
    except (TypeError, ValueError):
        max_sends = None

    def result_payload() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "generatedAt": generated_at,
            "mode": "send_once",
            "realWalletPayoutEnabled": real_enabled,
            "maxSends": max_sends,
            "sendAttempted": send_attempted,
            "sendSent": send_sent,
            "candidateId": candidate_id,
            "wallet": wallet,
            "amount": amount,
            "status": status,
            "warnings": warnings,
        }
        if txid:
            payload["txid"] = txid
        return payload

    def finish(finish_status: str) -> int:
        nonlocal status
        status = finish_status
        try:
            atomic_write_json(output_path, result_payload())
        except Exception as exc:
            print(f"Error: Failed to write send-once result atomically: {exc}", file=sys.stderr)
            return 1
        print("Payout Wallet Send-Once Summary")
        print("="*80)
        print(f"send_once_status: {status}")
        print(f"real_wallet_payout_enabled: {str(real_enabled).lower()}")
        print(f"max_sends: {max_sends if max_sends is not None else 'invalid'}")
        print(f"send_attempted: {str(send_attempted).lower()}")
        print(f"send_sent: {str(send_sent).lower()}")
        print(f"candidate_id: {candidate_id}")
        print(f"wallet: {wallet}")
        print(f"amount: {amount}")
        if txid:
            print(f"txid: {txid}")
        print(f"artifact_path: {output_path}")
        print("="*80)
        return 0

    if not real_enabled:
        return finish("blocked_real_wallet_payout_disabled")

    if max_sends != 1:
        return finish("blocked_invalid_send_budget")

    try:
        expected_amount = float(amount)
    except (TypeError, ValueError):
        return finish("blocked_amount_mismatch")
    if expected_amount <= 0:
        return finish("blocked_amount_mismatch")

    candidates: list[Any] = []
    if candidates_path.exists():
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                loaded = data.get("items") or data.get("candidates") or []
                if isinstance(loaded, list):
                    candidates = loaded
        except Exception as exc:
            warnings.append(f"Failed to read payout candidates: {exc}")
    else:
        warnings.append("Payout candidates snapshot missing")

    matching_candidate = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        c_id = candidate.get("candidateId") or candidate.get("candidate_hash")
        if c_id == candidate_id:
            matching_candidate = candidate
            break

    if matching_candidate is None:
        return finish("blocked_candidate_not_found")

    payouts = matching_candidate.get("payouts")
    if not isinstance(payouts, list):
        return finish("blocked_wallet_not_in_candidate")

    matching_payout = None
    for payout in payouts:
        if isinstance(payout, dict) and payout.get("wallet") == wallet:
            matching_payout = payout
            break

    if matching_payout is None:
        return finish("blocked_wallet_not_in_candidate")

    if matching_payout.get("status") not in {"pending_manual_payment", "ready_for_wallet_send_preview"}:
        return finish("blocked_payout_not_ready")

    try:
        payout_amount = float(matching_payout.get("amount"))
    except (TypeError, ValueError):
        return finish("blocked_amount_mismatch")

    if abs(payout_amount - expected_amount) > 1e-8:
        return finish("blocked_amount_mismatch")

    if payment_already_recorded(actions_log_path, candidate_id, wallet):
        return finish("blocked_already_paid")

    balance_res = wallet_readonly_call("getbalance", [])
    try:
        wallet_balance = float(balance_res) if balance_res is not None else None
    except (TypeError, ValueError):
        wallet_balance = None
    if wallet_balance is None:
        return finish("blocked_wallet_balance_unreadable")
    if expected_amount > wallet_balance:
        return finish("blocked_insufficient_balance")

    address_res = wallet_readonly_call("validateaddress", [wallet])
    if not (isinstance(address_res, dict) and address_res.get("isvalid") is True):
        return finish("blocked_invalid_address")

    lock_path = payment_actions_lock_path(actions_log_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            if payment_already_recorded(actions_log_path, candidate_id, wallet):
                return finish("blocked_already_paid")

            locked_env = load_env_vars()
            locked_max_sends_raw = locked_env.get("PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS")
            try:
                locked_max_sends = int(locked_max_sends_raw) if locked_max_sends_raw is not None else None
            except (TypeError, ValueError):
                locked_max_sends = None
            if locked_max_sends != 1:
                return finish("blocked_budget_exceeded")

            cli_path = locked_env.get("PEPEPOW_WALLET_CLI") or "/home/ubuntu/PEPEPOW-cli"
            if not cli_path or not os.path.exists(cli_path) or not os.access(cli_path, os.X_OK):
                warnings.append("Wallet CLI unavailable or not executable")
                failed_action = {
                    "candidate_id": candidate_id,
                    "wallet": wallet,
                    "amount": expected_amount,
                    "status": "failed",
                    "error": "wallet_cli_unavailable",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                append_payment_action(actions_log_path, failed_action)
                return finish("blocked_send_failed")

            send_attempted = True
            try:
                proc = subprocess.run(
                    [cli_path, "sendtoaddress", wallet, str(expected_amount)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except Exception as exc:
                warnings.append("sendtoaddress failed")
                failed_action = {
                    "candidate_id": candidate_id,
                    "wallet": wallet,
                    "amount": expected_amount,
                    "status": "failed",
                    "error": str(exc) or "sendtoaddress_exception",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                append_payment_action(actions_log_path, failed_action)
                return finish("blocked_send_failed")

            if proc.returncode != 0:
                warnings.append("sendtoaddress failed")
                failed_action = {
                    "candidate_id": candidate_id,
                    "wallet": wallet,
                    "amount": expected_amount,
                    "status": "failed",
                    "error": "sendtoaddress_failed",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                append_payment_action(actions_log_path, failed_action)
                return finish("blocked_send_failed")

            txid = proc.stdout.strip().splitlines()[0].strip() if proc.stdout.strip() else ""
            if not re.match(r"^[A-Za-z0-9]{26,128}$", txid):
                warnings.append("sendtoaddress returned invalid txid")
                failed_action = {
                    "candidate_id": candidate_id,
                    "wallet": wallet,
                    "amount": expected_amount,
                    "status": "failed",
                    "error": "invalid_txid",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                append_payment_action(actions_log_path, failed_action)
                return finish("blocked_send_failed")

            send_sent = True
            sent_action = {
                "candidate_id": candidate_id,
                "wallet": wallet,
                "amount": expected_amount,
                "txid": txid,
                "status": "sent",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            for metadata_key in (
                "carrySourceCandidateIds",
                "carrySourceCount",
                "carryInAmount",
                "baseAmount",
                "sourceCandidateIds",
            ):
                if metadata_key in matching_payout:
                    sent_action[metadata_key] = matching_payout.get(metadata_key)
            append_payment_action(actions_log_path, sent_action)
            clear_consumed_carry(
                payments_snapshot_path.parent / "payout-candidates.json",
                payments_snapshot_path.parent / "payout-carry-snapshot.json",
                candidate_id,
                wallet,
            )
            record_rc = generate_payments_snapshot(actions_log_path, payments_snapshot_path)
            if record_rc != 0:
                warnings.append("Payment sent but payments snapshot update failed")
                return finish("sent_record_failed")
            return finish("sent_recorded")
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description="PEPEPOW Manual Payout Accounting Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_cand = subparsers.add_parser("payout-candidates", help="Generate payout candidates")
    parser_cand.add_argument("--accepted-candidates", type=str, required=True, help="Path to accepted-candidates.json")
    parser_cand.add_argument("--rounds-snapshot", type=str, required=True, help="Path to rounds-snapshot.json")
    parser_cand.add_argument("--output", type=str, required=True, help="Path to output payout-candidates.json")
    parser_cand.add_argument("--carry-snapshot", type=str, required=False, help="Path to payout-carry-snapshot.json")

    parser_rec = subparsers.add_parser("record-payment", help="Record a manual payment")
    parser_rec.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_rec.add_argument("--snapshot", type=str, required=True, help="Path to payments-snapshot.json")
    parser_rec.add_argument("--candidate-id", type=str, required=True, help="Hash of candidate block")
    parser_rec.add_argument("--wallet", type=str, required=True, help="Wallet address paid")
    parser_rec.add_argument("--amount", type=float, required=True, help="Payment amount")
    parser_rec.add_argument("--txid", type=str, required=True, help="Transaction ID (txid)")

    parser_rebuild = subparsers.add_parser("rebuild-payments-snapshot", help="Rebuild payments snapshot from actions log")
    parser_rebuild.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_rebuild.add_argument("--snapshot", type=str, required=True, help="Path to payments-snapshot.json")

    parser_refresh = subparsers.add_parser("refresh-payment-confirmations", help="Refresh payment confirmations in snapshot")
    parser_refresh.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_refresh.add_argument("--snapshot", type=str, required=True, help="Path to payments-snapshot.json")

    parser_carry = subparsers.add_parser("build-carry-snapshot", help="Build carry snapshot from payout candidates")
    parser_carry.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_carry.add_argument("--snapshot", type=str, required=True, help="Path to output payout-carry-snapshot.json")

    parser_audit = subparsers.add_parser("audit-carry-consistency", help="Audit payout carry consistency")
    parser_audit.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_audit.add_argument("--carry-snapshot", type=str, required=True, help="Path to payout-carry-snapshot.json")
    parser_audit.add_argument("--payments-snapshot", type=str, required=True, help="Path to payments-snapshot.json")

    parser_review = subparsers.add_parser("payout-review", help="Show payout candidate review with carry summary")
    parser_review.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_review.add_argument("--carry-snapshot", type=str, required=True, help="Path to payout-carry-snapshot.json")
    parser_review.add_argument("--payments-snapshot", type=str, required=True, help="Path to payments-snapshot.json")
    parser_review.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    parser_check = subparsers.add_parser("payout-review-check", help="Compact read-only payout status for cron/monitoring")
    parser_check.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_check.add_argument("--carry-snapshot", type=str, required=True, help="Path to payout-carry-snapshot.json")
    parser_check.add_argument("--payments-snapshot", type=str, required=True, help="Path to payments-snapshot.json")

    parser_dry = subparsers.add_parser("payout-wallet-dry-run", help="Dry-run wallet payout validation and balance checking")
    parser_dry.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_dry.add_argument("--output", type=str, required=True, help="Path to output payout-wallet-dry-run.json")

    parser_send_once = subparsers.add_parser("payout-wallet-send-once", help="Guarded one-shot wallet payout send")
    parser_send_once.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_send_once.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_send_once.add_argument("--payments-snapshot", type=str, required=True, help="Path to payments-snapshot.json")
    parser_send_once.add_argument("--output", type=str, required=True, help="Path to output payout-wallet-send-once-result.json")
    parser_send_once.add_argument("--candidate-id", type=str, required=True, help="Candidate id to send")
    parser_send_once.add_argument("--wallet", type=str, required=True, help="Wallet address to pay")
    parser_send_once.add_argument("--amount", type=float, required=True, help="Exact amount to pay")

    parser_preflight = subparsers.add_parser("payout-wallet-send-preflight", help="Preflight guarded wallet payout send without sending")
    parser_preflight.add_argument("--candidates", type=str, required=True, help="Path to payout-candidates.json")
    parser_preflight.add_argument("--actions-log", type=str, required=True, help="Path to payment-actions.jsonl")
    parser_preflight.add_argument("--output", type=str, required=True, help="Path to output payout-wallet-send-preflight-result.json")
    parser_preflight.add_argument("--candidate-id", type=str, required=True, help="Candidate id to preflight")
    parser_preflight.add_argument("--wallet", type=str, required=True, help="Wallet address to preflight")
    parser_preflight.add_argument("--amount", type=float, required=True, help="Exact amount to preflight")

    args = parser.parse_args()

    if args.command == "payout-candidates":
        return generate_payout_candidates(
            Path(args.accepted_candidates),
            Path(args.rounds_snapshot),
            Path(args.output),
            Path(args.carry_snapshot) if args.carry_snapshot else None
        )
    elif args.command == "record-payment":
        return record_payment(
            Path(args.actions_log),
            Path(args.snapshot),
            args.candidate_id,
            args.wallet,
            args.amount,
            args.txid
        )
    elif args.command == "rebuild-payments-snapshot":
        return generate_payments_snapshot(
            Path(args.actions_log),
            Path(args.snapshot)
        )
    elif args.command == "refresh-payment-confirmations":
        return generate_payments_snapshot(
            Path(args.actions_log),
            Path(args.snapshot)
        )
    elif args.command == "build-carry-snapshot":
        return generate_carry_snapshot(
            Path(args.candidates),
            Path(args.snapshot)
        )
    elif args.command == "audit-carry-consistency":
        return audit_carry_consistency(
            Path(args.candidates),
            Path(args.carry_snapshot),
            Path(args.payments_snapshot)
        )
    elif args.command == "payout-review":
        return payout_review(
            Path(args.candidates),
            Path(args.carry_snapshot),
            Path(args.payments_snapshot),
            as_json=args.json
        )
    elif args.command == "payout-review-check":
        return payout_review_check(
            Path(args.candidates),
            Path(args.carry_snapshot),
            Path(args.payments_snapshot)
        )
    elif args.command == "payout-wallet-dry-run":
        return payout_wallet_dry_run(
            Path(args.candidates),
            Path(args.output)
        )
    elif args.command == "payout-wallet-send-once":
        return payout_wallet_send_once(
            Path(args.candidates),
            Path(args.actions_log),
            Path(args.payments_snapshot),
            Path(args.output),
            args.candidate_id,
            args.wallet,
            args.amount,
        )
    elif args.command == "payout-wallet-send-preflight":
        return payout_wallet_send_preflight(
            Path(args.candidates),
            Path(args.actions_log),
            Path(args.output),
            args.candidate_id,
            args.wallet,
            args.amount,
        )

    return 0

if __name__ == "__main__":
    sys.exit(main())

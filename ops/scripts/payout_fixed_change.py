#!/usr/bin/env python3
"""Fail-closed PEPEPOW payout sender with fixed, wallet-owned change.

Uses the legacy Core RPC sequence:
createrawtransaction -> fundrawtransaction -> decoderawtransaction ->
createrawtransaction (replace change) -> signrawtransaction ->
decoderawtransaction -> sendrawtransaction.

The wallet still chooses the inputs and fee. No additional recipient is allowed.
"""

from __future__ import annotations

import json
import re
import subprocess
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any


_ATOM = Decimal("0.00000001")
_TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
# Legacy Core FundTransaction adds inputs with sequence max_uint32 - 1.
# Its createrawtransaction RPC only reproduces that sequence with nonzero locktime.
# Locktime 1 is already final on the live PEPEPOW chain and is preserved end-to-end.
_LEGACY_SEQUENCE = 4294967294
_COMPAT_LOCKTIME = 1


class FixedChangeError(RuntimeError):
    """No transaction was intentionally broadcast."""


def _amount(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FixedChangeError("invalid_amount") from exc
    if not result.is_finite() or result <= 0 or result != result.quantize(_ATOM):
        raise FixedChangeError("invalid_amount")
    return result


def _rpc(cli_path: str, method: str, *arguments: str) -> str:
    try:
        proc = subprocess.run(
            [cli_path, method, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        if method == "sendrawtransaction":
            # A broadcast timeout may mean the network accepted the transaction.
            raise TimeoutError("fixed_change_broadcast_ambiguous") from exc
        raise FixedChangeError("fixed_change_prepare_timeout") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        if method == "sendrawtransaction":
            # Even a CLI error after send may represent an accepted transaction.
            raise TimeoutError("fixed_change_broadcast_ambiguous")
        raise FixedChangeError(f"fixed_change_{method}_failed")
    return proc.stdout.strip()


def _json_rpc(cli_path: str, method: str, *arguments: str) -> dict[str, Any]:
    try:
        result = json.loads(_rpc(cli_path, method, *arguments))
    except (ValueError, TypeError) as exc:
        raise FixedChangeError(f"fixed_change_{method}_invalid_json") from exc
    if not isinstance(result, dict):
        raise FixedChangeError(f"fixed_change_{method}_invalid_response")
    return result


def _address_of(output: dict[str, Any]) -> str | None:
    script = output.get("scriptPubKey")
    if not isinstance(script, dict):
        return None
    addresses = script.get("addresses")
    return addresses[0] if isinstance(addresses, list) and len(addresses) == 1 and isinstance(addresses[0], str) else None


def _check_outputs(decoded: dict[str, Any], recipient: str, amount: Decimal,
                   change_address: str, expected_change: Decimal | None) -> None:
    outputs = decoded.get("vout")
    if not isinstance(outputs, list) or len(outputs) != (2 if expected_change is not None else 1):
        raise FixedChangeError("fixed_change_unexpected_outputs")
    by_address: dict[str, Decimal] = {}
    for output in outputs:
        if not isinstance(output, dict):
            raise FixedChangeError("fixed_change_unexpected_outputs")
        address = _address_of(output)
        if address not in ({recipient, change_address} if expected_change is not None else {recipient}):
            raise FixedChangeError("fixed_change_unexpected_destination")
        if address in by_address:
            raise FixedChangeError("fixed_change_duplicate_destination")
        by_address[address] = _amount(output.get("value"))
    if by_address.get(recipient) != amount:
        raise FixedChangeError("fixed_change_recipient_amount_mismatch")
    if expected_change is not None and by_address.get(change_address) != expected_change:
        raise FixedChangeError("fixed_change_change_amount_mismatch")


def send_fixed_change(cli_path: str, recipient: str, amount: str,
                      change_address: str) -> SimpleNamespace:
    """Return a subprocess-compatible success result or raise to fail closed.

    Broadcast exceptions are TimeoutError to preserve payment-intent ambiguity
    protection. No automatic sendtoaddress fallback is permitted.
    """
    payout = _amount(amount)
    if not change_address or recipient == change_address:
        raise FixedChangeError("fixed_change_invalid_destination")
    for address, require_mine in ((recipient, False), (change_address, True)):
        info = _json_rpc(cli_path, "validateaddress", address)
        if info.get("isvalid") is not True or (require_mine and info.get("ismine") is not True):
            raise FixedChangeError("fixed_change_address_not_wallet_owned_or_invalid")

    raw = _rpc(cli_path, "createrawtransaction", "[]",
               json.dumps({recipient: format(payout, "f")}, separators=(",", ":")),
               str(_COMPAT_LOCKTIME))
    funded = _json_rpc(cli_path, "fundrawtransaction", raw)
    funded_hex = funded.get("hex")
    change_pos = funded.get("changepos")
    if not isinstance(funded_hex, str) or not funded_hex or type(change_pos) is not int:
        raise FixedChangeError("fixed_change_invalid_funding")
    fee = _amount(funded.get("fee"))
    if fee > min(Decimal("100"), max(Decimal("0.01"), payout * Decimal("0.01"))):
        raise FixedChangeError("fixed_change_fee_too_high")

    decoded = _json_rpc(cli_path, "decoderawtransaction", funded_hex)
    inputs = decoded.get("vin")
    outputs = decoded.get("vout")
    if not isinstance(inputs, list) or not inputs or not isinstance(outputs, list):
        raise FixedChangeError("fixed_change_invalid_funding")
    if decoded.get("version") != 1 or decoded.get("locktime") != _COMPAT_LOCKTIME:
        raise FixedChangeError("fixed_change_unsupported_raw_transaction")

    selected = []
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get("txid"), str) or not _TXID_RE.fullmatch(item["txid"]):
            raise FixedChangeError("fixed_change_invalid_input")
        if type(item.get("vout")) is not int or item["vout"] < 0 or item.get("sequence") != _LEGACY_SEQUENCE:
            raise FixedChangeError("fixed_change_unsupported_input")
        selected.append({"txid": item["txid"], "vout": item["vout"]})
    if len({(i["txid"], i["vout"]) for i in selected}) != len(selected):
        raise FixedChangeError("fixed_change_duplicate_input")

    if change_pos == -1:
        if len(outputs) != 1:
            raise FixedChangeError("fixed_change_invalid_change_position")
        _check_outputs(decoded, recipient, payout, change_address, None)
        unsigned = funded_hex
        change_amount = None
    else:
        if len(outputs) != 2 or change_pos not in (0, 1):
            raise FixedChangeError("fixed_change_invalid_change_position")
        recipient_output = outputs[1 - change_pos]
        change_output = outputs[change_pos]
        if _address_of(recipient_output) != recipient or _address_of(change_output) in (None, recipient):
            raise FixedChangeError("fixed_change_invalid_funded_outputs")
        if _amount(recipient_output.get("value")) != payout:
            raise FixedChangeError("fixed_change_recipient_amount_mismatch")
        change_amount = _amount(change_output.get("value"))
        unsigned = _rpc(
            cli_path, "createrawtransaction",
            json.dumps(selected, separators=(",", ":")),
            json.dumps({
                recipient: format(payout, "f"),
                change_address: format(change_amount, "f"),
            }, separators=(",", ":")),
            str(_COMPAT_LOCKTIME),
        )
        rebuilt = _json_rpc(cli_path, "decoderawtransaction", unsigned)
        if rebuilt.get("version") != 1 or rebuilt.get("locktime") != _COMPAT_LOCKTIME:
            raise FixedChangeError("fixed_change_rebuilt_locktime_changed")
        if any(i.get("sequence") != _LEGACY_SEQUENCE for i in rebuilt.get("vin", [])):
            raise FixedChangeError("fixed_change_rebuilt_sequence_changed")
        if [
            (v.get("txid"), v.get("vout")) for v in rebuilt.get("vin", [])
        ] != [(v["txid"], v["vout"]) for v in selected]:
            raise FixedChangeError("fixed_change_inputs_changed")
        _check_outputs(rebuilt, recipient, payout, change_address, change_amount)

    signed = _json_rpc(cli_path, "signrawtransaction", unsigned)
    if signed.get("complete") is not True or not isinstance(signed.get("hex"), str):
        raise FixedChangeError("fixed_change_sign_incomplete")
    signed_hex = signed["hex"]
    checked = _json_rpc(cli_path, "decoderawtransaction", signed_hex)
    if checked.get("version") != 1 or checked.get("locktime") != _COMPAT_LOCKTIME:
        raise FixedChangeError("fixed_change_signed_locktime_changed")
    if any(i.get("sequence") != _LEGACY_SEQUENCE for i in checked.get("vin", [])):
        raise FixedChangeError("fixed_change_signed_sequence_changed")
    if [
        (v.get("txid"), v.get("vout")) for v in checked.get("vin", [])
    ] != [(v["txid"], v["vout"]) for v in selected]:
        raise FixedChangeError("fixed_change_signed_inputs_changed")
    _check_outputs(checked, recipient, payout, change_address, change_amount)
    expected_txid = checked.get("txid")
    if not isinstance(expected_txid, str) or not _TXID_RE.fullmatch(expected_txid):
        raise FixedChangeError("fixed_change_invalid_signed_txid")

    broadcast_txid = _rpc(cli_path, "sendrawtransaction", signed_hex).splitlines()[0].strip()
    if broadcast_txid.lower() != expected_txid.lower():
        # A different response does not prove the signed transaction was rejected.
        raise TimeoutError("fixed_change_broadcast_txid_ambiguous")
    return SimpleNamespace(returncode=0, stdout=broadcast_txid + "\n", stderr="")

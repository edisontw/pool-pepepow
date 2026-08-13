#!/usr/bin/env python3
"""Keep canonical Pure SOLO confirmations/maturity monotonic and payout-ready."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACKED_STATUSES = {"chain_match_found", "immature", "confirmed"}
CONFIRMED_AT = 100


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _snapshot_height(path: Path) -> int:
    data = _load_json_dict(path) or {}
    try:
        value = int((data.get("network") or {}).get("height") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0
    return max(0, value)


def _rpc_height() -> int:
    scripts_dir = Path(__file__).resolve().parents[2] / "apps" / "pool-core"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from daemon_rpc import DaemonRpcClient  # noqa: E402

    rpc_host = os.getenv("PEPEPOWD_RPC_HOST", "127.0.0.1")
    rpc_port = os.getenv("PEPEPOWD_RPC_PORT", "8834")
    rpc_url = os.getenv("PEPEPOWD_RPC_URL", f"http://{rpc_host}:{rpc_port}")
    rpc_user = os.getenv("PEPEPOWD_RPC_USER", "")
    rpc_password = os.getenv("PEPEPOWD_RPC_PASSWORD", "")
    timeout = max(1.0, float(os.getenv("PEPEPOWD_RPC_TIMEOUT_SECONDS", "5")))
    if not rpc_user or not rpc_password:
        return 0

    client = DaemonRpcClient(
        rpc_url=rpc_url,
        rpc_user=rpc_user,
        rpc_password=rpc_password,
        timeout_seconds=timeout,
        cache_ttl_seconds=1,
    )
    try:
        value = int(client.call("getblockcount"))
    except Exception:
        return 0
    return max(0, value)


def _numeric_confirmations(value: Any) -> int | None:
    try:
        if value is None:
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def refresh_maturity(payload: dict[str, Any], current_height: int) -> int:
    items = payload.get("accepted_candidates")
    if not isinstance(items, list) or current_height <= 0:
        return 0

    changed = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        lifecycle = str(item.get("lifecycle_status") or "")
        if lifecycle not in TRACKED_STATUSES:
            continue
        try:
            matched_height = int(item.get("matched_height"))
        except (TypeError, ValueError):
            continue
        if matched_height <= 0 or current_height < matched_height:
            continue

        computed = current_height - matched_height + 1
        existing = _numeric_confirmations(item.get("confirmations"))
        confirmations = max(computed, existing or 0)
        status = "confirmed" if confirmations >= CONFIRMED_AT else "immature"
        maturity_label = "mature" if status == "confirmed" else "immature"

        if (
            item.get("confirmations") != confirmations
            or item.get("lifecycle_status") != status
            or item.get("maturity_label") != maturity_label
        ):
            item["confirmations"] = confirmations
            item["lifecycle_status"] = status
            item["maturity_label"] = maturity_label
            changed += 1

    return changed


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-candidates", type=Path, required=True)
    parser.add_argument("--pool-snapshot", type=Path, required=True)
    args = parser.parse_args()

    payload = _load_json_dict(args.accepted_candidates)
    if not payload or not isinstance(payload.get("accepted_candidates"), list):
        print("solo-maturity-refresh: accepted candidates unavailable")
        return 0

    current_height = _snapshot_height(args.pool_snapshot)
    height_source = "pool-snapshot"
    if current_height <= 0:
        current_height = _rpc_height()
        height_source = "daemon-rpc" if current_height > 0 else "unavailable"

    if current_height <= 0:
        # Never downgrade persisted maturity when chain context is temporarily unavailable.
        print("solo-maturity-refresh: chain height unavailable; preserved existing lifecycle")
        return 0

    changed = refresh_maturity(payload, current_height)
    if changed:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_atomic(args.accepted_candidates, payload)

    print(
        "solo-maturity-refresh:"
        f" chain_height={current_height}"
        f" source={height_source}"
        f" changed={changed}"
        f" accepted_candidates={len(payload['accepted_candidates'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

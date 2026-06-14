#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${PEPEPOW_LIVE_STRATUM_RUNTIME_DIR:-${REPO_ROOT}/.runtime/live-stratum}"
LAUNCH_ENV_FILE="${RUNTIME_DIR}/launch.env"

BACKFILL_ENABLED="${PEPEPOW_OPERATOR_BACKFILL_UNATTRIBUTED_CONFIRMED:-true}"
BACKFILL_WEIGHTS_JSON="${PEPEPOW_OPERATOR_BACKFILL_WEIGHTS_JSON:-}"
BACKFILL_REASON="${PEPEPOW_OPERATOR_BACKFILL_REASON:-operator_approved_unattributed_confirmed_rewards}"
BACKFILL_MIN_HEIGHT="${PEPEPOW_OPERATOR_BACKFILL_MIN_HEIGHT:-}"
BACKFILL_MAX_HEIGHT="${PEPEPOW_OPERATOR_BACKFILL_MAX_HEIGHT:-}"

if [[ -z "${BACKFILL_WEIGHTS_JSON}" ]]; then
  echo "missing PEPEPOW_OPERATOR_BACKFILL_WEIGHTS_JSON" >&2
  exit 2
fi

mkdir -p "${RUNTIME_DIR}"
touch "${LAUNCH_ENV_FILE}"
chmod 600 "${LAUNCH_ENV_FILE}"

python3 - "${LAUNCH_ENV_FILE}" "${BACKFILL_ENABLED}" "${BACKFILL_WEIGHTS_JSON}" "${BACKFILL_REASON}" "${BACKFILL_MIN_HEIGHT}" "${BACKFILL_MAX_HEIGHT}" <<'PY'
import json
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
enabled, weights_json, reason, min_height, max_height = sys.argv[2:]

try:
    weights = json.loads(weights_json)
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid PEPEPOW_OPERATOR_BACKFILL_WEIGHTS_JSON: {exc}")
if not isinstance(weights, dict) or not weights:
    raise SystemExit("PEPEPOW_OPERATOR_BACKFILL_WEIGHTS_JSON must be a non-empty JSON object")
for wallet, weight in weights.items():
    if not isinstance(wallet, str) or not wallet:
        raise SystemExit("weighted backfill wallet keys must be non-empty strings")
    try:
        weight_value = float(weight)
    except (TypeError, ValueError):
        raise SystemExit(f"invalid weight for {wallet}")
    if weight_value <= 0:
        raise SystemExit(f"weight must be positive for {wallet}")

updates = {
    "PEPEPOW_OPERATOR_BACKFILL_UNATTRIBUTED_CONFIRMED": enabled,
    "PEPEPOW_OPERATOR_BACKFILL_WEIGHTS_JSON": weights_json,
    "PEPEPOW_OPERATOR_BACKFILL_REASON": reason,
    "PEPEPOW_OPERATOR_BACKFILL_MIN_HEIGHT": min_height,
    "PEPEPOW_OPERATOR_BACKFILL_MAX_HEIGHT": max_height,
}

lines = []
if path.exists():
    lines = path.read_text(encoding="utf-8").splitlines()

skip = set(updates)
out = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in skip:
        continue
    out.append(line)

for key, value in updates.items():
    out.append(f"{key}={shlex.quote(str(value))}")

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"updated: {path}")
print("weighted_backfill_env: persisted")
PY

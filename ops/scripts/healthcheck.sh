#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8080/api/health}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:3000/}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-pepepow-pool-frontend.service}"

echo "Checking API: ${API_URL}"
API_PAYLOAD="$(curl --fail --silent --show-error "${API_URL}")"
echo "${API_PAYLOAD}"

python3 -c '
import json
import sys

payload = json.loads(sys.argv[1])
print(
    "API status:",
    payload.get("status"),
    "source=" + str(payload.get("snapshotSource")),
    "degraded=" + str(payload.get("degraded")),
    "stale=" + str(payload.get("stale")),
    "chainState=" + str(payload.get("chainState")),
    "activityMode=" + str(payload.get("activityMode")),
    "activityDataStatus=" + str(payload.get("activityDataStatus")),
)
' "${API_PAYLOAD}"

if command -v systemctl >/dev/null 2>&1 \
  && ! systemctl list-unit-files --type=service --no-pager --no-legend "${FRONTEND_SERVICE}" | grep -q "^${FRONTEND_SERVICE}[[:space:]]"; then
  echo "Skipping frontend: ${FRONTEND_SERVICE} is not installed in this deployment"
else
  echo "Checking frontend: ${FRONTEND_URL}"
  curl --fail --silent --show-error --head "${FRONTEND_URL}"
fi

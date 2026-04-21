#!/usr/bin/env bash
set -euo pipefail

FRONTEND_SERVICE="${FRONTEND_SERVICE:-pepepow-pool-frontend.service}"

systemctl daemon-reload
systemctl restart pepepow-pool-core.service
systemctl restart pepepow-pool-api.service

if systemctl list-unit-files --type=service --no-pager --no-legend "${FRONTEND_SERVICE}" | grep -q "^${FRONTEND_SERVICE}[[:space:]]"; then
  systemctl restart "${FRONTEND_SERVICE}"
  echo "Restarted pepepow-pool-core.service, pepepow-pool-api.service, and ${FRONTEND_SERVICE}"
else
  echo "Restarted pepepow-pool-core.service and pepepow-pool-api.service"
  echo "Skipped frontend: ${FRONTEND_SERVICE} is not installed in this deployment"
fi

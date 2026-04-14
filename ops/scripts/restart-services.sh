#!/usr/bin/env bash
set -euo pipefail

systemctl daemon-reload
systemctl restart pepepow-pool-core.service
systemctl restart pepepow-pool-api.service
systemctl restart pepepow-pool-frontend.service

echo "Restarted pepepow-pool-core.service, pepepow-pool-api.service, and pepepow-pool-frontend.service"

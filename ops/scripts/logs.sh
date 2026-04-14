#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-pepepow-pool-api.service}"

journalctl -u "${SERVICE}" -n 100 -f

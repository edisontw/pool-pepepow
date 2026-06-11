#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== repository =="
git status --short || true

echo
echo "== service active states =="
for svc in \
  pepepow-pool-stratum.service \
  pepepow-pool-api.service \
  pepepow-pool-core.service \
  pepepow-pool-frontend.service \
  nginx.service
 do
  state="$(systemctl is-active "$svc" 2>/dev/null || true)"
  if [ -z "$state" ]; then
    state="unknown"
  fi
  printf '%-34s %s\n' "$svc" "$state"
done

echo
echo "== local api health =="
if command -v curl >/dev/null 2>&1; then
  if command -v jq >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null | jq . || echo "api health unavailable"
  else
    curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null || echo "api health unavailable"
  fi
else
  echo "curl unavailable"
fi

echo
echo "== stratum drill status =="
if [ -x ./ops/scripts/live-stratum.sh ]; then
  ./ops/scripts/live-stratum.sh drill-status || true
else
  echo "live-stratum.sh unavailable or not executable"
fi

echo
echo "== recent runtime files, names only =="
if [ -d .runtime/live-stratum ]; then
  find .runtime/live-stratum -maxdepth 1 \
    \( -name '*.json' -o -name '*.jsonl' \) \
    -printf '%TY-%Tm-%Td %TH:%TM %10s %p\n' 2>/dev/null \
    | sort \
    | tail -n 30 || true
else
  echo ".runtime/live-stratum not found"
fi

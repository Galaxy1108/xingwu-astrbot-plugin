#!/usr/bin/env bash
# One-shot verification for M1. Usage: ./scripts/verify.sh [--with-e2e]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-$ROOT/../AstrBot/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

echo "== 1/4 backend pytest =="
"$PY" -m pytest -q

echo "== 2/4 frontend unit tests =="
if [[ -d web/node_modules ]]; then
  (cd web && npm run test --silent)
else
  echo "skip: web/node_modules missing (run npm install)"
fi

echo "== 3/4 frontend build =="
if [[ -d web/node_modules ]]; then
  (cd web && npm run build --silent)
else
  echo "skip: web/node_modules missing"
fi

echo "== 4/4 API acceptance (needs dev server on :6180) =="
if curl -sf -m 2 http://127.0.0.1:6180/healthz >/dev/null 2>&1; then
  "$PY" tests/e2e/api_acceptance.py --base-url http://127.0.0.1:6180
else
  echo "skip: dev server not running (scripts/dev_server.py --data-dir devdata --port 6180)"
fi

if [[ "${1:-}" == "--with-e2e" ]]; then
  echo "== E2E (Playwright) =="
  if [[ -d tests/e2e/node_modules ]]; then
    (cd tests/e2e && npx playwright test)
  else
    echo "skip: tests/e2e/node_modules missing (npm install there first)"
  fi
fi

echo "ALL CHECKS DONE"

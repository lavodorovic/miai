#!/usr/bin/env bash
# Stop anything holding port 8501 (Streamlit), refresh synthetic data + DuckDB, run tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Stopping Streamlit on :8501 (if any)"
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti :8501 2>/dev/null || true)"
  if [[ -n "${PIDS}" ]]; then
    kill -TERM ${PIDS} 2>/dev/null || true
    sleep 1
    PIDS2="$(lsof -ti :8501 2>/dev/null || true)"
    if [[ -n "${PIDS2}" ]]; then
      kill -KILL ${PIDS2} 2>/dev/null || true
    fi
  fi
fi
pkill -f "streamlit run.*app/main.py" 2>/dev/null || true
sleep 1

echo "==> Generating synthetic data"
PYTHONPATH="$ROOT/scripts:$ROOT" python3 scripts/generate_synthetic_audit_log.py

echo "==> Loading DuckDB"
PYTHONPATH="$ROOT/scripts:$ROOT" python3 scripts/db_setup.py

echo "==> Running pytest"
PYTHONPATH="$ROOT/scripts:$ROOT" python3 -m pytest tests/ -q

echo "==> OK — data refreshed and tests passed."

bash "${ROOT}/scripts/start_streamlit.sh"

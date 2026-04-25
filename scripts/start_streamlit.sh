#!/usr/bin/env bash
# Free port 8501 and start the Relio dashboard (for local testing).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Stopping anything on :8501"
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

LOG="${ROOT}/data/streamlit.log"
mkdir -p "${ROOT}/data"
echo "==> Starting Streamlit → ${LOG}"
nohup env PYTHONPATH="${ROOT}/scripts:${ROOT}" streamlit run app/main.py \
  --server.headless true \
  --browser.gatherUsageStats false \
  >>"${LOG}" 2>&1 &
echo $! >"${ROOT}/data/streamlit.pid"
sleep 2
echo "Open: http://localhost:8501"

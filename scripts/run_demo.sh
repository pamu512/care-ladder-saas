#!/usr/bin/env bash
# Start Care Ladder FastAPI for the OpenCV Agentic Vision judge demo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/uvicorn" ]]; then
  UVICORN="$ROOT/.venv/bin/uvicorn"
elif command -v uvicorn >/dev/null 2>&1; then
  UVICORN="uvicorn"
else
  echo "error: uvicorn not found; run: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 1
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "Care Ladder demo API: http://${HOST}:${PORT}"
echo "  POST /demo/run  {\"fixture\":\"no_movement_silence\"}"
echo "  GET  /incidents/{id}  — incident timeline"
echo "  UI:   http://${HOST}:${PORT}/ui/  — caregiver console (demo fixtures)"
echo "  Docs: http://${HOST}:${PORT}/docs"
echo "Reserved phones only (NPA-555-01XX); emergency fail-closed; stub dialer / speaker simulator."

exec "$UVICORN" care_ladder.api.app:app --host "$HOST" --port "$PORT"

#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Agent Bridge — start development server
# ─────────────────────────────────────────────────────────────
# Usage:
#   ./run-server.sh              # headless (SSE only, port 8765)
#   ./run-server.sh --tui        # server + TUI
#   ./run-server.sh --port 9000  # custom port
#   ./run-server.sh --db /tmp/my.db  # custom db path
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="${SCRIPT_DIR}/.venv"
DB_PATH="${SCRIPT_DIR}/bridge-dev.db"
PORT=8765
MODE="--headless"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tui)    MODE="" ; shift ;;
    --port)   PORT="$2"; shift 2 ;;
    --db)     DB_PATH="$2"; shift 2 ;;
    *)        echo "Unknown: $1"; exit 1 ;;
  esac
done

if [ ! -f "$VENV/bin/python" ]; then
  echo "❌ No .venv found. Run: uv sync --all-extras"
  exit 1
fi

echo "🚀 Starting Agent Bridge (port=$PORT db=$DB_PATH mode=${MODE:-default})"
exec "$VENV/bin/python" -m agent_bridge start $MODE --port "$PORT" --db-path "$DB_PATH"

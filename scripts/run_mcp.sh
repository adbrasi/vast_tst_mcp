#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VAST_AI_MCP_VENV:-$ROOT_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$VENV_DIR"
  "$PIP_BIN" install -e "$ROOT_DIR"
fi

exec "$PYTHON_BIN" -m vast_ai_mcp "$@"

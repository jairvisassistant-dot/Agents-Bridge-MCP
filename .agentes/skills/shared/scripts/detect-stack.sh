#!/bin/bash
# detect-stack.sh — Detecta el stack tecnológico del proyecto
# Uso: source detect-stack.sh
# Salida: STACK_TYPE, STACK_BUILD_CMD, STACK_TEST_CMD, STACK_LINT_CMD, STACK_FRAMEWORK
#   STACK_TYPE: "python" | "node" | "rust" | "go" | "unknown"
#   STACK_BUILD_CMD: comando para verificar build
#   STACK_TEST_CMD: comando para ejecutar tests
#   STACK_LINT_CMD: comando para linter (o cadena vacía)
#   STACK_FRAMEWORK: descripción legible del framework

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/init-report.sh"

STACK_TYPE="unknown"
STACK_BUILD_CMD="echo 'No build step defined for this stack'"
STACK_TEST_CMD="echo 'No test command defined for this stack'"
STACK_LINT_CMD=""
STACK_FRAMEWORK="desconocido"

# Python (pyproject.toml, setup.py, requirements.txt)
if [ -f "$PROJECT_ROOT/pyproject.toml" ] || [ -f "$PROJECT_ROOT/setup.py" ] || [ -f "$PROJECT_ROOT/setup.cfg" ]; then
  STACK_TYPE="python"
  STACK_FRAMEWORK="Python"
  STACK_BUILD_CMD="python3 -m compileall src/ 2>&1 | tail -30"
  STACK_TEST_CMD="uv run pytest 2>&1 | tail -30"
  # ruff > mypy > flake8 — probar en orden
  if uv run ruff --version &>/dev/null; then
    STACK_LINT_CMD="uv run ruff check src/ 2>&1 | tail -30"
  elif uv run mypy --version &>/dev/null; then
    STACK_LINT_CMD="uv run mypy src/ 2>&1 | tail -30"
  elif uv run flake8 --version &>/dev/null; then
    STACK_LINT_CMD="uv run flake8 src/ 2>&1 | tail -30"
  fi
  # Detectar framework específico
  if grep -q 'django' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null; then
    STACK_FRAMEWORK="Python / Django"
  elif grep -q 'fastapi\|starlette' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null; then
    STACK_FRAMEWORK="Python / FastAPI"
  elif grep -q 'textual' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null; then
    STACK_FRAMEWORK="Python / Textual TUI"
  elif grep -q 'mcp' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null; then
    STACK_FRAMEWORK="Python / MCP"
  fi

# Node.js (package.json)
elif [ -f "$PROJECT_ROOT/package.json" ]; then
  STACK_TYPE="node"
  STACK_BUILD_CMD="npm run build 2>&1 | tail -30"
  STACK_TEST_CMD="npm test 2>&1 | tail -30"
  STACK_LINT_CMD="npm run lint 2>&1 | tail -30"
  # Detectar framework
  if grep -q '"next"' "$PROJECT_ROOT/package.json" 2>/dev/null; then
    STACK_FRAMEWORK="Next.js"
  elif grep -q '"react"' "$PROJECT_ROOT/package.json" 2>/dev/null; then
    STACK_FRAMEWORK="React"
  elif grep -q '"vue"' "$PROJECT_ROOT/package.json" 2>/dev/null; then
    STACK_FRAMEWORK="Vue"
  elif grep -q '"svelte"' "$PROJECT_ROOT/package.json" 2>/dev/null; then
    STACK_FRAMEWORK="Svelte"
  else
    STACK_FRAMEWORK="Node.js"
  fi

# Rust (Cargo.toml)
elif [ -f "$PROJECT_ROOT/Cargo.toml" ]; then
  STACK_TYPE="rust"
  STACK_FRAMEWORK="Rust"
  STACK_BUILD_CMD="cargo build 2>&1 | tail -30"
  STACK_TEST_CMD="cargo test 2>&1 | tail -30"
  STACK_LINT_CMD="cargo clippy 2>&1 | tail -30"

# Go (go.mod)
elif [ -f "$PROJECT_ROOT/go.mod" ]; then
  STACK_TYPE="go"
  STACK_FRAMEWORK="Go"
  STACK_BUILD_CMD="go build ./... 2>&1 | tail -30"
  STACK_TEST_CMD="go test ./... 2>&1 | tail -30"
  STACK_LINT_CMD=""
fi

export STACK_TYPE STACK_BUILD_CMD STACK_TEST_CMD STACK_LINT_CMD STACK_FRAMEWORK

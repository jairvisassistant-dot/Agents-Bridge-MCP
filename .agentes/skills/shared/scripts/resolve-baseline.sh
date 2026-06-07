#!/bin/bash
# resolve-baseline.sh — Resuelve baseline del proyecto + detecta stack
# Uso: source resolve-baseline.sh
# Salida: BASELINE_HASH, BASELINE_SOURCE, DIFF_MODE, COMMITS_SINCE,
#         WORKTREE_STATE, BRANCH, STACK_TYPE, STACK_BUILD_CMD,
#         STACK_TEST_CMD, STACK_LINT_CMD, STACK_FRAMEWORK

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/init-report.sh"

# Intentar leer baseline_info.txt
BASELINE_HASH=""
BASELINE_SOURCE=""
if [ -f "$AUDITS_DIR/baseline_info.txt" ]; then
  BASELINE_HASH=$(grep BASELINE_COMMIT "$AUDITS_DIR/baseline_info.txt" 2>/dev/null | cut -d'=' -f2)
  BASELINE_SOURCE="baseline_info.txt"
fi

# Fallback: buscar en auditorías previas
if [ -z "$BASELINE_HASH" ]; then
  BASELINE_HASH=$(git log --oneline --all 2>/dev/null | grep -i "audit\|baseline" | head -1 | awk '{print $1}') || true
  BASELINE_SOURCE="heurística git (audit|baseline)"
fi

# Fallback: HEAD
if [ -z "$BASELINE_HASH" ]; then
  BASELINE_HASH=$(git rev-parse HEAD)
  BASELINE_SOURCE="HEAD actual"
fi

# Detectar modo de comparación
WORKTREE_STATE=$( [ -n "$(git status --short 2>/dev/null)" ] && echo "modificado" || echo "limpio" )

if [ -z "$BASELINE_HASH" ] || [ "$BASELINE_HASH" = "HEAD" ]; then
  DIFF_MODE="repo actual completo (sin baseline formal)"
  COMMITS_SINCE=0
else
  COMMITS_SINCE=$(git log --oneline "$BASELINE_HASH"..HEAD 2>/dev/null | wc -l)
  if [ "$WORKTREE_STATE" = "modificado" ]; then
    DIFF_MODE="$BASELINE_HASH..HEAD + working tree modificado"
  else
    DIFF_MODE="$BASELINE_HASH..HEAD"
  fi
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Detectar stack (ahora integrado)
source "$SCRIPT_DIR/detect-stack.sh"

export BASELINE_HASH BASELINE_SOURCE DIFF_MODE COMMITS_SINCE WORKTREE_STATE BRANCH
export STACK_TYPE STACK_BUILD_CMD STACK_TEST_CMD STACK_LINT_CMD STACK_FRAMEWORK

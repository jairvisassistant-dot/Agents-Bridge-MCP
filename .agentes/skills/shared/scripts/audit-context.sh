#!/bin/bash
# audit-context.sh — Genera índice único del proyecto (stack-agnostic)
# Uso: bash audit-context.sh
# Salida: .opencode/audit-context.json (contexto compartido entre skills)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/init-report.sh"

CONTEXT_FILE="$PROJECT_ROOT/.opencode/audit-context.json"
mkdir -p "$PROJECT_ROOT/.opencode"

# Resolver baseline + stack
source "$SCRIPT_DIR/resolve-baseline.sh"
source "$SCRIPT_DIR/detect-stack.sh"

# Contar archivos fuente (genérico por extensiones del stack)
TOTAL_SRC_FILES=0
SRC_EXTENSIONS=""

case "$STACK_TYPE" in
  python)
    SRC_EXTENSIONS="*.py"
    TOTAL_SRC_FILES=0
    # Solo buscar en directorios que existen (evita error de find con pipefail)
    for _dir in "$PROJECT_ROOT/src" "$PROJECT_ROOT/app"; do
      [ -d "$_dir" ] && TOTAL_SRC_FILES=$((TOTAL_SRC_FILES + $(find "$_dir" -name "*.py" 2>/dev/null | wc -l)))
    done
    if [ "$TOTAL_SRC_FILES" -eq 0 ]; then
      TOTAL_SRC_FILES=$(find "$PROJECT_ROOT" -maxdepth 4 -name "*.py" -not -path "*/.venv/*" -not -path "*/__pycache__/*" -not -path "*/.git/*" 2>/dev/null | wc -l)
    fi
    TEST_COUNT=0
    [ -d "$PROJECT_ROOT/tests" ] && TEST_COUNT=$(find "$PROJECT_ROOT/tests" -name "*.py" 2>/dev/null | wc -l)
    ;;
  node)
    SRC_EXTENSIONS="*.ts *.tsx *.js *.jsx"
    TOTAL_SRC_FILES=0
    for _dir in "$PROJECT_ROOT/src" "$PROJECT_ROOT/app" "$PROJECT_ROOT/components"; do
      [ -d "$_dir" ] && TOTAL_SRC_FILES=$((TOTAL_SRC_FILES + $(find "$_dir" -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" 2>/dev/null | wc -l)))
    done
    TEST_COUNT=0
    [ -d "$PROJECT_ROOT/tests" ] && TEST_COUNT=$(find "$PROJECT_ROOT/tests" -maxdepth 3 \( -name "*.test.*" -o -name "*.spec.*" \) 2>/dev/null | wc -l)
    ;;
  rust)
    SRC_EXTENSIONS="*.rs"
    TOTAL_SRC_FILES=0
    [ -d "$PROJECT_ROOT/src" ] && TOTAL_SRC_FILES=$(find "$PROJECT_ROOT/src" -name "*.rs" 2>/dev/null | wc -l)
    TEST_COUNT=$(grep -c '#\[test\]' "$PROJECT_ROOT/src"/*.rs 2>/dev/null || echo "0")
    ;;
  go)
    SRC_EXTENSIONS="*.go"
    TOTAL_SRC_FILES=$(find "$PROJECT_ROOT" -name "*.go" -not -path "*/.git/*" -maxdepth 5 2>/dev/null | wc -l)
    TEST_COUNT=$(find "$PROJECT_ROOT" -name "*_test.go" -maxdepth 5 2>/dev/null | wc -l)
    ;;
  *)
    TOTAL_SRC_FILES=0
    for _dir in "$PROJECT_ROOT/src" "$PROJECT_ROOT/app"; do
      [ -d "$_dir" ] && TOTAL_SRC_FILES=$((TOTAL_SRC_FILES + $(find "$_dir" -type f \( -name "*.py" -o -name "*.ts" -o -name "*.rs" -o -name "*.go" \) 2>/dev/null | wc -l)))
    done
    TEST_COUNT=0
    ;;
esac

# Obtener dependencias según stack
PROD_DEPS=0
DEV_DEPS=0
STACK_DEPS="{}"

case "$STACK_TYPE" in
  python)
    if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
      PROD_DEPS=$(grep -c '^\s\+"' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null || echo "0")
      # Intentar obtener versiones de paquetes instalados
      if command -v uv &>/dev/null; then
        STACK_DEPS=$(uv run python3 -c "
import importlib.metadata, json
deps = {}
for pkg in ['mcp', 'aiosqlite', 'textual', 'httpx', 'pydantic']:
    try:
        deps[pkg] = importlib.metadata.version(pkg)
    except:
        pass
print(json.dumps(deps))
" 2>/dev/null || echo "{}")
      fi
    fi
    ;;
  node)
    if [ -f "$PROJECT_ROOT/package.json" ]; then
      PROD_DEPS=$(node -e "const p=require('$PROJECT_ROOT/package.json'); console.log(Object.keys(p.dependencies||{}).length)" 2>/dev/null || echo "0")
      DEV_DEPS=$(node -e "const p=require('$PROJECT_ROOT/package.json'); console.log(Object.keys(p.devDependencies||{}).length)" 2>/dev/null || echo "0")
    fi
    ;;
esac

# Working tree diff (lista de archivos modificados)
MODIFIED_FILES_JSON=$(git diff --name-only 2>/dev/null | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")

# Generar JSON genérico
cat > "$CONTEXT_FILE" << CONTEXT_EOF
{
  "meta": {
    "generated_at": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
    "project_root": "$PROJECT_ROOT",
    "stack_type": "$STACK_TYPE",
    "framework": "$STACK_FRAMEWORK"
  },
  "baseline": {
    "hash": "$BASELINE_HASH",
    "source": "$BASELINE_SOURCE",
    "branch": "$BRANCH",
    "worktree": "$WORKTREE_STATE",
    "commits_since": $COMMITS_SINCE,
    "diff_mode": "$DIFF_MODE",
    "modified_files": $MODIFIED_FILES_JSON
  },
  "project": {
    "framework": "$STACK_FRAMEWORK",
    "total_source_files": $TOTAL_SRC_FILES,
    "test_files": $TEST_COUNT,
    "src_extensions": "$SRC_EXTENSIONS"
  },
  "dependencies": {
    "prod_count": $PROD_DEPS,
    "dev_count": $DEV_DEPS,
    "details": $STACK_DEPS
  }
}
CONTEXT_EOF

echo "✅ Contexto guardado en: $CONTEXT_FILE (stack: $STACK_TYPE / $STACK_FRAMEWORK)"

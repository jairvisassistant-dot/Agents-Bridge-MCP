#!/bin/bash
# consolidate.sh — Compila reporte consolidado desde 3 JSONs de hallazgos
# Uso: consolidate.sh --code <json> --arch <json> --prod <json> [--output <name>]
# Salida: audit_consolidated_TIMESTAMP.md + .json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/init-report.sh"
source "$SCRIPT_DIR/resolve-baseline.sh"

CODE_JSON=""
ARCH_JSON=""
PROD_JSON=""
OUTPUT_NAME=""
VERIFY_JSON=""

while [ $# -gt 0 ]; do
  case "$1" in
    --code) CODE_JSON="$2"; shift 2 ;;
    --arch) ARCH_JSON="$2"; shift 2 ;;
    --prod) PROD_JSON="$2"; shift 2 ;;
    --output) OUTPUT_NAME="$2"; shift 2 ;;
    --verify) VERIFY_JSON="$2"; shift 2 ;;
    *) echo "Error: argumento desconocido: $1"; exit 1 ;;
  esac
done

TIMESTAMP=$(date +'%Y%m%d_%H%M')
DATE_HUMAN=$(date +'%Y-%m-%d %H:%M')
OUTPUT_MD="${OUTPUT_NAME:-$AUDITS_DIR/audit_consolidated_$TIMESTAMP.md}"
OUTPUT_JSON="${OUTPUT_NAME:-$AUDITS_DIR/audit_consolidated_$TIMESTAMP.json}"

# Leer JSONs (con defaults si no existen)
code_total=0; code_crit=0; code_high=0; code_med=0; code_low=0
arch_total=0; arch_crit=0; arch_high=0; arch_med=0; arch_low=0
prod_total=0; prod_crit=0; prod_high=0; prod_med=0; prod_low=0

_read_json_field() {
  local file="$1" field="$2" default="${3:-0}"
  if ! [ -f "$file" ]; then echo "$default"; return; fi
  if command -v jq &>/dev/null; then
    jq -r "$field // $default" "$file" 2>/dev/null || echo "$default"
  else
    # Usar script Python temporal para evitar problemas de quoting
    python3 - "$file" "$field" "$default" << 'PYEOF'
import json, sys
file = sys.argv[1]
field = sys.argv[2]
default = sys.argv[3]
try:
    data = json.load(open(file))
    # Evaluar field path como expresiones anidadas
    parts = field.strip(".").split(".")
    val = data
    for p in parts:
        if p == "": continue
        if isinstance(val, dict):
            val = val.get(p, None)
        else:
            val = None
        if val is None:
            break
    print(val if val is not None else default)
except Exception:
    print(default)
PYEOF
  fi
}

read_stats() {
  local file="$1"
  local prefix="$2"
  if [ -f "$file" ]; then
    eval "${prefix}_total=\$(_read_json_field \"$file\" '.stats.total' 0)"
    eval "${prefix}_crit=\$(_read_json_field \"$file\" '.stats.crit' 0)"
    eval "${prefix}_high=\$(_read_json_field \"$file\" '.stats.high' 0)"
    eval "${prefix}_med=\$(_read_json_field \"$file\" '.stats.med' 0)"
    eval "${prefix}_low=\$(_read_json_field \"$file\" '.stats.low' 0)"
  fi
}

read_stats "$CODE_JSON" "code"
read_stats "$ARCH_JSON" "arch"
read_stats "$PROD_JSON" "prod"

TOTAL=$((code_total + arch_total + prod_total))
CRIT=$((code_crit + arch_crit + prod_crit))
HIGH=$((code_high + arch_high + prod_high))
MED=$((code_med + arch_med + prod_med))
LOW=$((code_low + arch_low + prod_low))

# Generar consolidated JSON
cat > "$OUTPUT_JSON" << JSON_EOF
{
  "meta": {
    "type": "consolidated",
    "date": "$DATE_HUMAN",
    "baseline": "$BASELINE_HASH",
    "pipeline": "code → architecture → product"
  },
  "summary": {
    "total": $TOTAL,
    "crit": $CRIT,
    "high": $HIGH,
    "med": $MED,
    "low": $LOW,
    "by_skill": {
      "code": { "total": $code_total, "crit": $code_crit, "high": $code_high, "med": $code_med, "low": $code_low },
      "architecture": { "total": $arch_total, "crit": $arch_crit, "high": $arch_high, "med": $arch_med, "low": $arch_low },
      "product": { "total": $prod_total, "crit": $prod_crit, "high": $prod_high, "med": $prod_med, "low": $prod_low }
    }
  }
}
JSON_EOF

# Generar consolidated markdown
TEMPLATE="$SCRIPT_DIR/../templates/consolidated_template.md"
if [ -f "$TEMPLATE" ]; then
  cp "$TEMPLATE" "$OUTPUT_MD"
else
  cat > "$OUTPUT_MD" << MD_EOF
# Auditoría Consolidada — $DATE_HUMAN
MD_EOF
fi

# ── Reemplazar TODOS los placeholders del template ─────────────

# Fecha y baseline
sed -i "s/{{DATE}}/$DATE_HUMAN/g" "$OUTPUT_MD"
sed -i "s/{{BASELINE_HASH}}/$BASELINE_HASH/g" "$OUTPUT_MD"

# Totales
sed -i "s/{{TOTAL}}/$TOTAL/g" "$OUTPUT_MD"
sed -i "s/{{CRIT_COUNT}}/$CRIT/g" "$OUTPUT_MD"
sed -i "s/{{HIGH_COUNT}}/$HIGH/g" "$OUTPUT_MD"
sed -i "s/{{MED_COUNT}}/$MED/g" "$OUTPUT_MD"
sed -i "s/{{LOW_COUNT}}/$LOW/g" "$OUTPUT_MD"

# Backward compat: placeholders sin _COUNT (template viejo)
sed -i "s/{{CRIT}}/$CRIT/g" "$OUTPUT_MD"
sed -i "s/{{HIGH}}/$HIGH/g" "$OUTPUT_MD"
sed -i "s/{{MED}}/$MED/g" "$OUTPUT_MD"
sed -i "s/{{LOW}}/$LOW/g" "$OUTPUT_MD"

# Por skill (CODE, ARCH, PROD)
for prefix in code arch prod; do
  PREFIX_UPPER=$(echo "$prefix" | tr '[:lower:]' '[:upper:]')
  eval "total=\${${prefix}_total:-0}"
  eval "crit=\${${prefix}_crit:-0}"
  eval "high=\${${prefix}_high:-0}"
  eval "med=\${${prefix}_med:-0}"
  eval "low=\${${prefix}_low:-0}"
  sed -i "s/{{${PREFIX_UPPER}_TOTAL}}/$total/g" "$OUTPUT_MD"
  sed -i "s/{{${PREFIX_UPPER}_CRIT}}/$crit/g" "$OUTPUT_MD"
  sed -i "s/{{${PREFIX_UPPER}_HIGH}}/$high/g" "$OUTPUT_MD"
  sed -i "s/{{${PREFIX_UPPER}_MED}}/$med/g" "$OUTPUT_MD"
  sed -i "s/{{${PREFIX_UPPER}_LOW}}/$low/g" "$OUTPUT_MD"
done

# Build / test / lint status (leer de audit-context.json si existe)
BUILD_STATUS="—"
TEST_STATUS="—"
if [ -f "$PROJECT_ROOT/.opencode/audit-context.json" ]; then
  BUILD_STATUS=$(_read_json_field "$PROJECT_ROOT/.opencode/audit-context.json" '.build.build_status' "—")
  TEST_STATUS=$(_read_json_field "$PROJECT_ROOT/.opencode/audit-context.json" '.build.test_status' "—")
fi
sed -i "s/{{BUILD_STATUS}}/$BUILD_STATUS/g" "$OUTPUT_MD"
sed -i "s/{{TEST_STATUS}}/$TEST_STATUS/g" "$OUTPUT_MD"

# Reportes fuente (extraer nombres de archivo de los JSON de entrada)
CODE_REPORT="—"; ARCH_REPORT="—"; PROD_REPORT="—"
[ -n "$CODE_JSON" ] && CODE_REPORT=$(basename "${CODE_JSON%.json}.md" 2>/dev/null || echo "—")
[ -n "$ARCH_JSON" ] && ARCH_REPORT=$(basename "${ARCH_JSON%.json}.md" 2>/dev/null || echo "—")
[ -n "$PROD_JSON" ] && PROD_REPORT=$(basename "${PROD_JSON%.json}.md" 2>/dev/null || echo "—")
sed -i "s/{{CODE_REPORT}}/$CODE_REPORT/g" "$OUTPUT_MD"
sed -i "s/{{ARCH_REPORT}}/$ARCH_REPORT/g" "$OUTPUT_MD"
sed -i "s/{{PROD_REPORT}}/$PROD_REPORT/g" "$OUTPUT_MD"

# Limpiar cualquier placeholder remanente
sed -i 's/{{[^}]*}}//g' "$OUTPUT_MD"

# ── Agregar sección de verificación (si existe) ────────────────
if [ -n "$VERIFY_JSON" ] && [ -f "$VERIFY_JSON" ]; then
  VERIFY_RATE=$(_read_json_field "$VERIFY_JSON" '.summary.pass_rate' "—")
  VERIFY_SAMPLE=$(_read_json_field "$VERIFY_JSON" '.summary.sample_size' 0)
  VERIFY_TOTAL=$(_read_json_field "$VERIFY_JSON" '.summary.total_findings' 0)
  cat >> "$OUTPUT_MD" << VERIFY_EOF

---

## Verificación Post-Auditoría

- **Hallazgos verificados:** $VERIFY_SAMPLE de $VERIFY_TOTAL
- **Tasa de verificación:** $VERIFY_RATE

Generado por: \`verify-findings.sh\`
VERIFY_EOF
fi

echo "✅ Consolidado guardado en: $OUTPUT_MD"
echo "✅ JSON consolidado en: $OUTPUT_JSON"

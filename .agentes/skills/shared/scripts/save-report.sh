#!/bin/bash
# save-report.sh — Guarda reporte de auditoría en .md + .json
# Uso: save-report.sh --type code|architecture|product|consolidated|verification [--json findings.json]
# Salida: Escribe .md + .json en AUDITS_DIR

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/init-report.sh"

# Parse args
TYPE=""
FINDINGS_JSON=""

while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="$2"; shift 2 ;;
    --json) FINDINGS_JSON="$2"; shift 2 ;;
    *) echo "Error: argumento desconocido: $1"; exit 1 ;;
  esac
done

if [ -z "$TYPE" ]; then
  echo "Error: --type es obligatorio (code|architecture|product|consolidated|verification)"
  exit 1
fi

TIMESTAMP=$(date +'%Y%m%d_%H%M')
DATE_HUMAN=$(date +'%Y-%m-%d %H:%M')
REPORT_MD="$AUDITS_DIR/audit_${TYPE}_${TIMESTAMP}.md"
REPORT_JSON="$AUDITS_DIR/audit_${TYPE}_${TIMESTAMP}.json"

# Generar .md desde template si existe
TEMPLATE_DIR="$SCRIPT_DIR/../../software-${TYPE}-auditor/templates"
if [ "$TYPE" = "consolidated" ]; then
  TEMPLATE_DIR="$SCRIPT_DIR/../templates"
elif [ "$TYPE" = "verification" ]; then
  TEMPLATE_DIR="$SCRIPT_DIR/../../software-audit-verifier/templates"
fi

# Resolver baseline para placeholders (si no está ya cargado)
BASELINE_HASH="${BASELINE_HASH:-$(git rev-parse HEAD 2>/dev/null || echo 'unknown')}"

if [ -f "$TEMPLATE_DIR/report_template.md" ]; then
  cp "$TEMPLATE_DIR/report_template.md" "$REPORT_MD"

  # Reemplazar TODOS los placeholders conocidos con su valor o default
  sed -i "s/{{DATE}}/$DATE_HUMAN/g" "$REPORT_MD"
  sed -i "s/{{BASELINE_HASH}}/$BASELINE_HASH/g" "$REPORT_MD"
  sed -i "s/{{TIMESTAMP}}/$TIMESTAMP/g" "$REPORT_MD"
  sed -i "s/{{TYPE}}/$TYPE/g" "$REPORT_MD"

  # Placeholders numéricos (default 0)
  for placeholder in TOTAL CRIT_COUNT HIGH_COUNT MED_COUNT LOW_COUNT; do
    sed -i "s/{{$placeholder}}/0/g" "$REPORT_MD"
  done

  # Placeholders por skill (default 0)
  for skill in CODE ARCH PROD; do
    for severity in TOTAL CRIT HIGH MED LOW; do
      sed -i "s/{{${skill}_${severity}}}/0/g" "$REPORT_MD"
    done
  done

  # Placeholders de texto (default "—")
  for placeholder in BUILD_STATUS TEST_STATUS CODE_REPORT ARCH_REPORT PROD_REPORT VERDICT; do
    sed -i "s/{{$placeholder}}/—/g" "$REPORT_MD"
  done

  # Limpiar cualquier {{...}} que haya quedado
  sed -i 's/{{[^}]*}}//g' "$REPORT_MD"

  echo "✅ Template base copiado a: $REPORT_MD"
else
  echo "# Auditoría de ${TYPE} — ${DATE_HUMAN}" > "$REPORT_MD"
  echo "⚠️ Sin template — reporte generado desde cero"
fi

# Si hay JSON de hallazgos, copiarlo
if [ -n "$FINDINGS_JSON" ] && [ -f "$FINDINGS_JSON" ]; then
  cp "$FINDINGS_JSON" "$REPORT_JSON"
  echo "✅ Hallazgos JSON guardados en: $REPORT_JSON"
else
  echo "{}" > "$REPORT_JSON"
  echo "ℹ️ JSON vacío creado en: $REPORT_JSON"
fi

echo "✅ Reporte guardado: $REPORT_MD"
echo "output_file=$REPORT_MD"

#!/bin/bash
# verify-findings.sh — Verifica una muestra de hallazgos contra el código real
# Uso: verify-findings.sh --code <json> --arch <json> --prod <json> [--sample N]
# Salida: audit_verification_TIMESTAMP.md + .json en AUDITS_DIR

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/init-report.sh"

CODE_JSON=""; ARCH_JSON=""; PROD_JSON=""; SAMPLE_SIZE=3
while [ $# -gt 0 ]; do
  case "$1" in
    --code) CODE_JSON="$2"; shift 2 ;;
    --arch) ARCH_JSON="$2"; shift 2 ;;
    --prod) PROD_JSON="$2"; shift 2 ;;
    --sample) SAMPLE_SIZE="$2"; shift 2 ;;
    *) echo "Error: $1"; exit 1 ;;
  esac
done

TIMESTAMP=$(date +'%Y%m%d_%H%M')
DATE_HUMAN=$(date +'%Y-%m-%d %H:%M')
OUTPUT_MD="$AUDITS_DIR/audit_verification_$TIMESTAMP.md"
OUTPUT_JSON="$AUDITS_DIR/audit_verification_$TIMESTAMP.json"

_read_findings() { local f="$1"; [ ! -f "$f" ] && return
  if command -v jq &>/dev/null; then jq -c '.findings[]' "$f" 2>/dev/null || true
  else python3 - "$f" 2>/dev/null << 'PYEOF' || true
import json,sys
with open(sys.argv[1]) as f:
    for finding in json.load(f).get("findings",[]):
        print(json.dumps(finding,ensure_ascii=False))
PYEOF
  fi
}

ALL_FINDINGS=$(_read_findings "$CODE_JSON")
ALL_FINDINGS="$ALL_FINDINGS"$'\n'$(_read_findings "$ARCH_JSON")
ALL_FINDINGS="$ALL_FINDINGS"$'\n'$(_read_findings "$PROD_JSON")
TOTAL_FINDINGS=$(echo "$ALL_FINDINGS" | grep -c '[^[:space:]]' 2>/dev/null || echo "0")

# Sample: prioritize by severity
SAMPLE_JSON=$(
echo "$ALL_FINDINGS" | python3 -c "
import json, sys
findings = [json.loads(l) for l in sys.stdin if l.strip()]
severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
findings.sort(key=lambda f: (severity_order.get(f.get('severity','INFO'), 99), f.get('id','')))
for f in findings[:${SAMPLE_SIZE}]:
    print(json.dumps(f, ensure_ascii=False))
" 2>/dev/null || echo "")
SAMPLE_COUNT=$(echo "$SAMPLE_JSON" | grep -c '[^[:space:]]' 2>/dev/null || echo "0")

# Build temp JSON for verified results
VERIFIED_FILE=$(mktemp /tmp/verify_results_XXXXXX.json)
echo '{"verified":[]}' > "$VERIFIED_FILE"
PASS_COUNT=0; FILE_OK_COUNT=0; GLOBAL_COUNT=0; FAIL_COUNT=0; LINE_FAIL_COUNT=0

while IFS= read -r finding_line; do
  [ -z "$(echo "$finding_line" | tr -d '[:space:]')" ] && continue
  file=$(echo "$finding_line" | python3 -c "import json,sys;print(json.load(sys.stdin).get('file',''))" 2>/dev/null || echo "")
  line=$(echo "$finding_line" | python3 -c "import json,sys;print(json.load(sys.stdin).get('line',0) or 0)" 2>/dev/null || echo "0")
  id=$(echo "$finding_line" | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
  sev=$(echo "$finding_line" | python3 -c "import json,sys;print(json.load(sys.stdin).get('severity',''))" 2>/dev/null || echo "")

  status=""; detail=""
  if [ -z "$file" ] || [ "${file:0:1}" = "(" ]; then
    status="global"; GLOBAL_COUNT=$((GLOBAL_COUNT + 1))
  else
    full_path="$PROJECT_ROOT/$file"
    if [ ! -f "$full_path" ] && [ ! -d "$full_path" ]; then
      status="file_not_found"; detail="File not found: $file"
      FAIL_COUNT=$((FAIL_COUNT + 1))
    elif [ "$line" -gt 0 ] 2>/dev/null; then
      total_lines=$(wc -l < "$full_path" 2>/dev/null || echo "0")
      if [ "$line" -le "$total_lines" ] 2>/dev/null; then
        status="verified"; PASS_COUNT=$((PASS_COUNT + 1))
      else
        status="line_out_of_range"
        detail="Line $line exceeds $total_lines"
        LINE_FAIL_COUNT=$((LINE_FAIL_COUNT + 1))
      fi
    else
      status="file_verified"; FILE_OK_COUNT=$((FILE_OK_COUNT + 1))
    fi
  fi
  python3 -c "
import json
with open('$VERIFIED_FILE') as f:
    data = json.load(f)
data['verified'].append({'id':'$id','severity':'$sev','file':'$file','line':$line,'status':'$status','detail':'$detail'})
with open('$VERIFIED_FILE','w') as f:
    json.dump(data, f, ensure_ascii=False)
" 2>/dev/null
done <<< "$(echo "$SAMPLE_JSON")"

OK_COUNT=$((PASS_COUNT + FILE_OK_COUNT + GLOBAL_COUNT))
PASS_RATE=0; [ "$SAMPLE_COUNT" -gt 0 ] 2>/dev/null && PASS_RATE=$((OK_COUNT * 100 / SAMPLE_COUNT))

# Read back results
VERIFIED_DATA=$(cat "$VERIFIED_FILE")
rm -f "$VERIFIED_FILE"

# Generate JSON output
python3 -c "
import json
data = json.loads('''$VERIFIED_DATA''')
meta = {'type':'verification','date':'$DATE_HUMAN','pipeline':'code → architecture → product → verification'}
summary = {
    'total_findings': $TOTAL_FINDINGS,
    'sample_size': $SAMPLE_COUNT,
    'verified_ok': $PASS_COUNT,
    'file_exists_ok': $FILE_OK_COUNT,
    'global_scope': $GLOBAL_COUNT,
    'file_not_found': $FAIL_COUNT,
    'line_out_of_range': $LINE_FAIL_COUNT,
    'pass_rate': f'{int($PASS_RATE)}%'
}
output = {'meta': meta, 'summary': summary, 'verified': data['verified']}
with open('$OUTPUT_JSON', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print('✅ JSON saved')
"

# Generate MD output
python3 -c "
import json
with open('$OUTPUT_JSON') as f:
    data = json.load(f)
s = data['summary']
lines = []
lines.append('# Verificación de Hallazgos — $DATE_HUMAN')
lines.append('')
lines.append('## Resumen')
lines.append('')
lines.append(f\"- **Total hallazgos en pipeline:** {s['total_findings']}\")
lines.append(f\"- **Muestra verificada:** {s['sample_size']}\")
lines.append(f\"- **Tasa de verificación:** {s['pass_rate']}\")
lines.append('')
lines.append('## Resultados')
lines.append('')
lines.append('| Estado | Cantidad |')
lines.append('|--------|----------|')
lines.append(f\"| ✅ Línea verificada | {s['verified_ok']} |\")
lines.append(f\"| 📁 Archivo existe | {s['file_exists_ok']} |\")
lines.append(f\"| 🌐 Scope general | {s['global_scope']} |\")
lines.append(f\"| ❌ Archivo no encontrado | {s['file_not_found']} |\")
lines.append(f\"| ⚠️ Línea fuera de rango | {s['line_out_of_range']} |\")
lines.append('')
lines.append('## Detalle por hallazgo')
lines.append('')
lines.append('| ID | Severidad | Archivo | Línea | Estado |')
lines.append('|----|-----------|---------|-------|--------|')
icons = {'verified': '✅', 'file_verified': '📁', 'global': '🌐', 'file_not_found': '❌', 'line_out_of_range': '⚠️'}
for v in data['verified']:
    icon = icons.get(v.get('status',''), '⚠️')
    ln = v.get('line', '-')
    if ln == 0: ln = '-'
    lines.append(f\"| {v['id']} | {v['severity']} | \`{v['file']}\` | {ln} | {icon} {v['status']} |\")
lines.append('')
lines.append('## Recomendación')
lines.append('')
lines.append('- **Archivos no encontrados:** Revisar si el hallazgo referencia una ruta que ya no existe.')
lines.append('- **Líneas fuera de rango:** El hallazgo puede estar desactualizado.')
lines.append('- **Tasa < 100%:** Considerar re-auditar las áreas no verificables.')
with open('$OUTPUT_MD', 'w') as f:
    f.write('\\n'.join(lines))
print('✅ MD saved')
"

echo "output_file=$OUTPUT_MD"

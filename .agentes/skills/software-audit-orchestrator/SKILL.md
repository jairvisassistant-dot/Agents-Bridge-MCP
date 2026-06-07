---
name: software-audit-orchestrator
description: >
  Orquestador de auditorías. Ejecuta el pipeline completo:
  código → arquitectura → producto → reporte consolidado.
  Gestiona el PASO 0 una sola vez, aprende de auditorías previas,
  y persiste hallazgos para trazabilidad cross-session.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.3"
---

## When to Use

- "auditar completa", "auditar todo", "ejecutar pipeline completo"
- Necesidad de reporte consolidado multi-dominio
- Pre-deploy check que cubra todas las dimensiones
- El usuario no especifica qué tipo de auditoría → pipeline completo

## Qué NO hace

```
NO audita código → software-code-auditor
NO audita arquitectura → software-architecture-auditor
NO audita producto → software-product-auditor
NO verifica fixes → software-audit-verifier
```

**Única responsabilidad: pipeline, contexto, consolidación, aprendizaje continuo.**

## Aprendizaje Continuo — Protocolo de Memoria

El orquestador utiliza Engram (memoria persistente) para:
- Recordar hallazgos de auditorías anteriores
- Detectar progreso o regresión entre sesiones
- Evitar repetir falsos positivos ya documentados
- Ajustar prioridades de hallazgos basado en cambios reales del código

### Convención de topic_keys

| Artículo | topic_key |
|----------|-----------|
| Últimos hallazgos de código | `audits/latest/code` |
| Últimos hallazgos de arquitectura | `audits/latest/architecture` |
| Últimos hallazgos de producto | `audits/latest/product` |
| Consolidado + veredicto | `audits/latest/consolidated` |
| Baseline usado | `audits/latest/baseline` |

### Reglas de persistencia

- Cada hallazgo individual se guarda con `mem_save` usando `topic_key` fijo (se reemplaza siempre)
- El consolidado completo se guarda con `capture_prompt: false` (es un artifact, no una decisión humana)
- Al iniciar una auditoría nueva, se ejecuta `mem_search` con los topic_keys anteriores
- Hallazgos previos que ya no aparecen en el diff actual se marcan como "posiblemente corregidos"

## Metodología — Pipeline de 7 Fases

### FASE 00 — Contexto Histórico (Aprendizaje Continuo)
**Antes de cualquier otra operación**, buscar memoria de auditorías previas:

```python
# Pseudocódigo — ejecutar con las herramientas de memoria disponibles
mem_search(query: "audits/latest/*", project: "{project}")
```

Si existen hallazgos previos:
1. Leer el consolidado anterior para entender el estado previo
2. Contrastar los hallazgos CRITICAL/HIGH anteriores contra el diff actual
3. Si un archivo mencionado en un hallazgo previo aparece en `git diff --name-only`, el hallazgo PUEDE estar corregido o necesita re-evaluación
4. Pasar al sub-agente de FASE 1 la advertencia: "Hallazgos previos detectados en {archivos cambiados} — verificar si persisten"

### FASE 0A — PASO 0 (Shared Baseline + Trazabilidad + Stack Detection)
Ejecutar (único source):
```bash
source .agentes/skills/shared/scripts/resolve-baseline.sh
```
Esto genera variables: `BASELINE_HASH`, `DIFF_MODE`, `WORKTREE_STATE`, `BRANCH`,
`STACK_TYPE`, `STACK_BUILD_CMD`, `STACK_TEST_CMD`, `STACK_LINT_CMD`, `STACK_FRAMEWORK`.

> `resolve-baseline.sh` ahora incluye `detect-stack.sh` automáticamente.

### FASE 0B — Build + Tests (OBLIGATORIO, stack-agnostic)
Ejecutar los comandos correspondientes al stack detectado en FASE 0A:
```bash
bash -c "$STACK_BUILD_CMD"; BUILD_EXIT=$?
bash -c "$STACK_TEST_CMD"; TEST_EXIT=$?
if [ -n "$STACK_LINT_CMD" ]; then
  bash -c "$STACK_LINT_CMD"; LINT_EXIT=$?
else
  LINT_EXIT=""
  echo "ℹ️  No hay linter configurado para este stack"
fi
```
Si `BUILD_EXIT != 0` → pipeline se detiene con hallazgo CRIT.
Si `TEST_EXIT != 0` → hallazgo HIGH registrado en consolidado.

> **Stack auto-detectado:** `$STACK_TYPE` / `$STACK_FRAMEWORK`
> **Build:** `$STACK_BUILD_CMD`
> **Test:** `$STACK_TEST_CMD`
> **Lint:** `${STACK_LINT_CMD:-no configurado}`

### FASE 0C — Indexado Único
Ejecutar: `bash .agentes/skills/shared/scripts/audit-context.sh`
Genera `.opencode/audit-context.json` con estructura del proyecto (stack-agnostic: source files, deps, working tree diff).

### FASE 1 — Auditoría de Código
Delegar a sub-agente con prompt compacto que referencia la metodología:
1. Proveer `.opencode/audit-context.json` como contexto
2. Indicar: "Seguí la metodología de **código** en `.agentes/skills/shared/audit-methodology-reference.md`"
3. Incluir hallazgos previos de `audits/audit_code_*.json` si existen
4. Incluir hallazgos de FASE 00 si se detectaron previos en los mismos archivos
5. El sub-agente escribe en `audits/audit_code_*.md` y `audits/audit_code_*.json`
Al finalizar: leer `audits/audit_code_*.json` para extraer hallazgos.

### FASE 2 — Auditoría de Arquitectura
Delegar a sub-agente con prompt compacto:
1. Proveer contexto + hallazgos de FASE 1 (`audits/audit_code_*.json`)
2. Indicar: "Seguí la metodología de **arquitectura** en `.agentes/skills/shared/audit-methodology-reference.md`"
3. Incluir artefactos previos de `audits/audit_architecture_*.md` si existen
4. Contrastar hallazgos de código que condicionen decisiones arquitecturales
5. El sub-agente escribe en `audits/audit_architecture_*.md` y `audits/audit_architecture_*.json`
Al finalizar: leer `audits/audit_architecture_*.json`.

### FASE 3 — Auditoría de Producto
Delegar a sub-agente con prompt compacto:
1. Proveer contexto + hallazgos de FASE 1 y FASE 2
2. Indicar: "Seguí la metodología de **producto** en `.agentes/skills/shared/audit-methodology-reference.md`"
3. Contrastar promesas de `README.md` y `AGENT-BRIDGE-SPEC.md` contra comportamiento real
4. Hallazgos con causa raíz en código/arquitectura → registrar como "Hallazgo referido"
5. El sub-agente escribe en `audits/audit_product_*.md` y `audits/audit_product_*.json`
Al finalizar: leer `audits/audit_product_*.json`.

### FASE 4 — Reporte Consolidado
Ejecutar:
```bash
.agentes/skills/shared/scripts/consolidate.sh \
  --code audits/audit_code_*.json \
  --arch audits/audit_architecture_*.json \
  --prod audits/audit_product_*.json
```
Input: 3 JSONs de hallazgos. Output: consolidated .md + .json.
Opcional: agregar `--verify audits/audit_verification_*.json` para incluir verificación.

### FASE 5 — Verificación de Hallazgos (POST-CONSOLIDACIÓN)
Ejecutar:
```bash
bash .agentes/skills/shared/scripts/verify-findings.sh \
  --code audits/audit_code_*.json \
  --arch audits/audit_architecture_*.json \
  --prod audits/audit_product_*.json \
  --sample 3
```
Esto selecciona una muestra estratificada (priorizando CRITICAL/HIGH) y verifica:
- Que el archivo citado en cada hallazgo exista
- Que la línea citada esté dentro del rango del archivo
- Reporta tasa de aciertos y falsos positivos estructurales

La verificación se guarda en `audits/audit_verification_*.md` (humano) y `audits/audit_verification_*.json` (estructurado).

### FASE 6 — Archivo y Persistencia (Aprendizaje Continuo)

Al finalizar el pipeline, **persistir los hallazgos en memoria para la próxima auditoría**:

1. **Guardar consolidado en Engram:**
   ```
   mem_save(
     title="Auditoría consolidada — {project} — {date}",
     type="architecture",
     topic_key="audits/latest/consolidated",
     content="**What**: Auditoría consolidada completada\n**Why**: Pipeline estándar\n**Where**: audits/audit_consolidated_*.md\n**Learned**: {top 3 hallazgos del consolidado}",
     capture_prompt=false
   )
   ```

2. **Guardar baseline usado:**
   ```
   mem_save(
     title="Baseline de auditoría — {project} — {hash}",
     type="config",
     topic_key="audits/latest/baseline",
     content="**What**: Baseline: {hash} / {diff_mode}\n**Where**: branch {branch}, worktree {worktree_state}",
     capture_prompt=false
   )
   ```

3. **Detectar progreso vs auditoría anterior:**
   - Si `mem_search(query: "audits/latest/code")` encuentra hallazgos previos
   - Y el diff actual (`git diff --name-only baseline_hash`) incluye los archivos de esos hallazgos
   - Agregar nota al consolidado: "⚠️ N hallazgos previos están en archivos modificados — posiblemente corregidos"

4. **Generar reporte de progreso:**
   ```
   Comparar:
   - Total hallazgos anterior vs actual (↓ mejora, ↑ regresión)
   - CRITICAL anterior vs actual
   - Archivos reincidentes (mismo archivo, distinto hallazgo = nueva deuda)
   ```

## Input Contract

| Contexto | Generado por |
|---|---|
| Hallazgos previos (Engram) | FASE 00 (búsqueda) |
| Baseline, diff, worktree, stack | FASE 0A (resolve-baseline.sh) |
| Build/test/lint status | FASE 0B |
| Proyecto indexado | FASE 0C (audit-context.sh) |
| Hallazgos code | FASE 1 |
| Hallazgos arch | FASE 2 |
| Hallazgos prod | FASE 3 |

## Output Contract

`audits/audit_consolidated_YYYYMMDD_HHMM.md` (+ .json)

Generado vía: `.agentes/skills/shared/scripts/consolidate.sh`

Hallazgos persistentes en Engram (topic_key: `audits/latest/*`) para trazabilidad cross-session.

---
name: software-audit-verifier
description: >
  Verificación post-auditoría. Compara estado actual contra baseline para validar
  si hallazgos previos fueron corregidos, siguen abiertos o introdujeron regresiones.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "2.2"
---

## When to Use

- Después de implementar cambios basados en auditoría previa
- "verificar cambios", "validar fixes", "seguimiento de auditoría"
- Verificación de regresiones tras cambios
- Comparación: auditoría previa → respuesta desarrollador → estado actual

## Input Contract

| Contexto | Fuente |
|---|---|
| Baseline + diff | `.opencode/audit-context.json` |
| Hallazgos previos | `Otros/Info_Auditorias/audit_*_latest.json` |
| Respuesta del desarrollador | `Otros/Info_Auditorias/Respuesta-audit_*.md` |
| Reporte consolidado | `Otros/Info_Auditorias/audit_consolidated_*.json` |
| Modo ejecución | `pipeline` (post-FASE 4) o `standalone` |

## Output Contract

`Otros/Info_Auditorias/verification_YYYYMMDD_HHMM.md` (+ .json)

## Methodology

### PASO 0 — Verificación documental del framework
Si el fix toca: layouts, metadata, routing, i18n, proxy/middleware, file conventions → contrastar contra docs de Next.js instalada (`node_modules/next/dist/docs/`).

### PASO 1 — Resolver baseline real
Buscar el baseline más reciente en este orden:
1. `baseline_info.txt`
2. Último `audit_consolidated_*.json` → `meta.baseline`
3. Último `audit_*.md` → commit auditado
4. `HEAD` como snapshot lógico

### PASO 2 — Mapear hallazgos previos
Para cada hallazgo en audit_consolidated:
- Estado esperado (según respuesta del desarrollador)
- Commit/archivos que deberían haber cambiado
- Severidad original

### PASO 3 — Verificar cada hallazgo
Para cada hallazgo, determinar estado real:

| Estado | Significado |
|---|---|
| ✅ RESUELTO | El cambio está aplicado, evidencia verificada |
| ⚠️ PARCIAL | Solo parte del fix está aplicado |
| ❌ PERSISTENTE | El código no cambió o el fix no funciona |
| 🔄 REGRESIÓN | Se intentó fixear pero introdujo otro problema |
| ⏸️ DIFERIDO | Deuda aceptada documentada |
| ❓ NO VERIFICABLE | No se puede verificar sin build/test/runtime |

### PASO 4 — Buscar regresiones
Si el fix tocó archivos, verificar que:
- No haya nuevos imports rotos
- No se hayan eliminado funcionalidades existentes
- No se hayan introducido nuevos hallazgos de las 8 categorías

### PASO 5 — Generar reporte
Tabla: hallazgo original | respuesta desarrollador | estado real | evidencia

## Red Lines

```
NO es una auditoría nueva — no buscar issues no relacionados con hallazgos previos
NO marcar RESUELTO un fix cosmético si la causa raíz sigue abierta
Toda conclusión debe tener evidencia verificable (diff, grep, lectura actual)
Si el fix toca convenciones del framework, contrastar contra docs versionadas
```

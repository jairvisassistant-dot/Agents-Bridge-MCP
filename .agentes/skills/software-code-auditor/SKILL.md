---
name: software-code-auditor
description: >
  Auditoría línea por línea de código fuente: bugs, vulnerabilidades de seguridad,
  deuda técnica y calidad.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.3"
---

## When to Use

- Usuario pide "auditar" o "revisar" el código
- Solicitud de "revisar seguridad" o "buscar vulnerabilidades"
- Evaluación de "calidad del código" o "deuda técnica"
- Revisión de bugs, inconsistencias o código muerto
- Verificación pre-deploy de un feature o refactor

## Exclusiones (NO auditar)

```
node_modules/ → excluir | .next/ → excluir | .env.local → excluir
scripts/migrate*.ts → exclude (script one-time)
public/ → solo verificar robots.txt y tamaño de imágenes
```

## Input Contract

| Contexto | Fuente |
|---|---|
| Baseline + diff mode + working tree | `.opencode/audit-context.json` (generado por shared/scripts/audit-context.sh en FASE 0) |
| Artefactos previos | `Otros/Info_Auditorias/*.md` (leer los más recientes) |
| Hallazgos de otras skills | No aplica — es FASE 1 del pipeline |
| Modo ejecución | `pipeline` (vía orquestador) o `standalone` |

## Output Contract

Al finalizar, escribir en `Otros/Info_Auditorias/`:
- `audit_code_YYYYMMDD_HHMM.md` — Reporte legible para humanos
- `audit_code_YYYYMMDD_HHMM.json` — Hallazgos estructurados (schema en REFERENCE.md)

Ambos archivos se generan vía: `shared/scripts/save-report.sh --type code`

## Methodology

### PASO 0 — Mapa del proyecto
Leer `.opencode/audit-context.json`. Mapear exports, páginas, data files, i18n keys.

### PASO 1 — Lecciones Aprendidas
Leer `LECCIONES_APRENDIDAS.md`. Contrastar contra `Otros/Info_Auditorias/`. Ver REFERENCE.md para checklist detallado.

### PASO 2 — Código Muerto
Para cada archivo en `components/`, `data/`, `lib/`, `hooks/`, `types/`: listar exports → grep en todo el proyecto. Sin importador = código muerto.

### PASO 3 — Auditoría i18n Bidireccional
3A: Claves en código pero no en JSONs. 3B: Claves en JSONs sin uso. 3C: Asimetría entre es.json y en.json.

### PASO 4 — Consistencia del Grafo de Imports
Verificar imports de archivos refactorizados recientemente. Especial atención a `types/index.ts`, `data/`, `lib/`.

### PASO 5 — Consistencia de Datos Entre Archivos
FAQ vs catálogo (tamaños, precios). Contacto solo en `SITE_CONFIG`. `presentationOrder` por línea (1,2,3).

### PASO 6 — Schemas Zod y Localización
Para cada schema Zod: ¿mensajes hardcodeados? ¿usado en cliente multi-idioma? → bug de localización.

Ver REFERENCE.md para reglas detalladas de cada paso y las 8 categorías de auditoría.

## Red Lines

```
NO aprobaciones genéricas | NO ignorar errores de tipos
NO sugerir cambios cosméticos antes de bugs CRITICAL
NO crear código productivo — solo identificar problemas
NO auditar node_modules, .next, .env.local
NO commit automático del reporte
```

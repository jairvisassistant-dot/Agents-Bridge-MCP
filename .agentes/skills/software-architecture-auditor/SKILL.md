---
name: software-architecture-auditor
description: >
  Auditoría de arquitectura, performance y stack tecnológico de aplicaciones Next.js.
  Evalúa decisiones de diseño, tamaño de bundle, estrategia de rendering y deuda
  técnica arquitectural.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.3"
---

## When to Use

- Solicitud de "auditar arquitectura" o "revisar el stack"
- Análisis de "performance" o "bundle size"
- Evaluación de "estrategia de rendering" (SSR, SSG, ISR, CSR)
- Revisión de decisiones técnicas (Next.js vs otro framework, CMS elegido, etc.)
- Evaluación de deuda técnica a nivel arquitectural
- Solicitud de "quick wins" o "roadmap de mejoras"

## Exclusiones (NO auditar)

```
node_modules/ → excluir | .next/ → excluir | .env.local → excluir
scripts/migrate*.ts → exclude | sanity/schemas → excluir
LECCIONES_APRENDIDAS.md → solo leer para contexto
```

## Input Contract

| Contexto | Fuente |
|---|---|
| Baseline + diff + worktree | `.opencode/audit-context.json` |
| Hallazgos de FASE 1 | `Otros/Info_Auditorias/audit_code_*.json` (el más reciente) |
| Artefactos previos | `Otros/Info_Auditorias/audit_architecture_*.md` |
| Modo ejecución | `pipeline` (vía orquestador) o `standalone` |

Usar `HALLAZGOS_CODE` para contrastar si hallazgos de código condicionan decisiones arquitecturales (ej: NEXT-01 sobre "use client" innecesario → impacto en bundle que arch auditor debe medir).

## Output Contract

Al finalizar, escribir en `Otros/Info_Auditorias/`:
- `audit_architecture_YYYYMMDD_HHMM.md` — Reporte legible para humanos
- `audit_architecture_YYYYMMDD_HHMM.json` — Hallazgos estructurados (schema en REFERENCE.md)

Ambos vía: `shared/scripts/save-report.sh --type architecture`

## Methodology

### PASO 1 — Inventario Tecnológico
Leer `package.json`. Evaluar cada dependencia: versión, alternativas, justificación de uso.

### PASO 2 — Estrategia de Rendering
Mapear cada ruta: SSR / ISR / SSG / CSR. Evaluar `dynamic`, `revalidate`, `force-static`. Ver REFERENCE.md para checklist completo.

### PASO 3 — Server Components vs Client Components
Clasificar cada componente: RSC / CC necesario / CC innecesario. Verificar `m` (no `motion`) y `dict` como prop.

### PASO 4 — Bundle y JavaScript
4A: Dependencias pesadas y alternativas. 4B: Code splitting. 4C: Top 5 imports más pesados.

### PASO 5 — Data Fetching
Sanity (queries, revalidate, CDN), i18n (React.cache, claves huérfanas), datos estáticos.

### PASO 6 — Imágenes y Media
next/image, priority, sizes, WebP/AVIF, quality, archivos >500KB.

### PASO 7 — SEO y Metadata
generateMetadata, sitemap, JSON-LD, robots.txt, canonical, lang.

### PASO 8 — Arquitectura i18n
app/[lang]/, DictionaryProvider, alternativas (next-intl, next-i18next), LanguageSwitcher.

### PASO 9 — Accesibilidad Estructural
Jerarquía headings, tab-focus, keyboard support, graceful degradation, WCAG AA.

### PASO 10 — Estructura del Proyecto
Separación components/ui/sections/layout, organización lib/, data/, Sanity Studio.

Ver REFERENCE.md para checklists detallados de cada paso y formato de hallazgo.

## Red Lines

```
NO repetir hallazgos de código (seguridad, a11y técnica, bugs)
NO sugerir cambios cosméticos sin resolver issues CRIT/HIGH
NO commit automático del reporte
```

---
name: software-product-auditor
description: >
  Auditoría de calidad de producto digital: identidad visual, UX, contenido,
  responsive design, microinteracciones, credibilidad y privacidad legal.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.1"
---

## When to Use

- Solicitud de "auditar producto" o "revisar UX / UI"
- Evaluación de identidad visual o diferenciación de marca
- Análisis de contenido, propuesta de valor o tono
- Revisión de responsive design o experiencia móvil
- Evaluación de microinteracciones y propósito de animaciones
- Análisis de credibilidad, confianza o transparencia
- Revisión de privacidad legal, consentimiento o ética

## Exclusiones (NO auditar)

```
node_modules/ → excluir | .next/ → excluir | .env.local → excluir
scripts/migrate*.ts → exclude | sanity/schemas → excluir
```

**Áreas delegadas a otras skills (NO duplicar):**
- Seguridad técnica (API keys, XSS, Zod) → code-auditor
- Accesibilidad WCAG (contraste, keyboard, labels) → code-auditor
- SEO técnico (sitemap, robots, metadata, schema) → architecture-auditor
- Bundle / performance / rendering → architecture-auditor
- Bugs de código, imports rotos, TypeScript → code-auditor
- Código muerto y deuda técnica → code-auditor
- Estrategia i18n → architecture-auditor

## Input Contract

| Contexto | Fuente |
|---|---|
| Baseline + diff + worktree | `.opencode/audit-context.json` |
| Hallazgos de FASE 1 | `Otros/Info_Auditorias/audit_code_*.json` |
| Hallazgos de FASE 2 | `Otros/Info_Auditorias/audit_architecture_*.json` |
| Artefactos previos | `Otros/Info_Auditorias/audit_product_*.md` |
| Modo ejecución | `pipeline` (vía orquestador) o `standalone` |

Usar hallazgos previos para: contrastar si bugs de código o decisiones arquitecturales explican problemas de producto. Hallazgos de producto con causa raíz en código/arquitectura → registrar como "Hallazgo referido".

## Output Contract

Al finalizar, escribir en `Otros/Info_Auditorias/`:
- `audit_product_YYYYMMDD_HHMM.md` — Reporte legible
- `audit_product_YYYYMMDD_HHMM.json` — Hallazgos estructurados

Ambos vía: `shared/scripts/save-report.sh --type product`

## Methodology

### PASO 1 — Identidad Visual y Diferenciación de Marca
Evaluar hero/first fold, paleta de color, tipografía, cards, consistencia global. Ver REFERENCE.md para checklist completo.

### PASO 2 — UX, Flujo de Navegación y Conversión
CTA principal, menú, user journey, formularios, patrones anti-UX. Ver REFERENCE.md.

### PASO 3 — Contenido, Propuesta de Valor y Tono
Propuesta de valor, calidad del contenido, tono, veracidad, repetición. Ver REFERENCE.md.

### PASO 4 — Responsive Design y Experiencia Móvil
Hero en móvil, menú móvil, cards/grids, formularios, touch targets. Ver REFERENCE.md.

### PASO 5 — Microinteracciones, Animaciones y Propósito
Propósito de cada animación, performance, prefers-reduced-motion, scroll-jacking.

### PASO 6 — Credibilidad, Confianza y Transparencia
Quién está detrás, contacto, pruebas sociales, señales de legalidad, autenticidad.

### PASO 7 — Privacidad Legal, Consentimiento y Ética
Cookies, privacidad, términos, transparencia IA, sesgos. Ver REFERENCE.md.

## Red Lines

```
NO duplicar hallazgos de seguridad, a11y técnica o SEO técnico cubiertos por otras skills
NO profundizar en código para diagnosticar problema de producto — solo identificar síntoma visible
NO sugerir soluciones de implementación detallada que correspondan a skills de diseño visual
NO dar aprobaciones genéricas ("se ve bien") sin checklist aplicada
NO ignorar contenido factualmente incorrecto o desactualizado
```

# Auditoría de Código — {{DATE}}

## Metadatos
- **Tipo:** Código
- **Fecha:** {{DATE}}
- **Baseline / Snapshot:** {{BASELINE_HASH}}
- **Fuente del baseline:** {{BASELINE_SOURCE}}
- **Modo de comparación:** {{DIFF_MODE}}
- **Artefactos previos leídos:** {{ARTEFACTS_READ}}
- **Auditor:** software-code-auditor v1.3
- **Commits desde baseline:** {{COMMITS_COUNT}}

## Estado Pre-Auditoría
- Baseline o snapshot: {{BASELINE_HASH}}
- Working tree al iniciar: {{WORKTREE_STATE}}
- Archivos en scope: {{FILES_COUNT}}
- Dependencias totales: {{DEPS_COUNT}}

## Commits Realizados Desde Baseline
{{COMMITS_LIST}}

## Hallazgos Detallados

<!-- Formato de cada hallazgo:
[SEVERIDAD] ID-REGLA — Archivo:línea
Síntoma: qué ve el usuario o qué falla
Causa raíz: por qué ocurrió
Solución: cambio exacto a hacer
-->

## Resumen Ejecutivo
- **Total hallazgos:** {{TOTAL}}
- 🔴 **Críticos:** {{CRIT_COUNT}}
- 🟠 **Altos:** {{HIGH_COUNT}}
- 🟡 **Medios:** {{MED_COUNT}}
- 🟢 **Bajos/Info:** {{LOW_COUNT}}

## Resumen por Categoría
- 🟥 Seguridad (SEC): {{SEC_COUNT}}
- 🟠 Bugs (BUG): {{BUG_COUNT}}
- 🔵 Next.js (NEXT): {{NEXT_COUNT}}
- 🟡 TypeScript (TS): {{TS_COUNT}}
- 🟢 Rendimiento (PERF): {{PERF_COUNT}}
- 🔷 Accesibilidad (A11Y): {{A11Y_COUNT}}
- 🟣 Deuda Técnica (DT): {{DT_COUNT}}
- 🩷 UX y Contenido (UX): {{UX_COUNT}}

## Top 5 Issues (por impacto en usuario)
1. ...
2. ...
3. ...
4. ...
5. ...

## Archivos Sin Hallazgos

## Riesgos no validados por ejecución

## Archivo de Referencia
Este informe fue generado desde el estado auditado. Para comparar con auditorías futuras, verificar el baseline en `Otros/Info_Auditorias/`.

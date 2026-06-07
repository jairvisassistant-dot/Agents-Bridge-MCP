# Auditoría de Arquitectura — {{DATE}}

## Metadatos
- **Tipo:** Arquitectura
- **Fecha:** {{DATE}}
- **Baseline / Snapshot:** {{BASELINE_HASH}}
- **Fuente del baseline:** {{BASELINE_SOURCE}}
- **Modo de comparación:** {{DIFF_MODE}}
- **Artefactos previos leídos:** {{ARTEFACTS_READ}}
- **Auditor:** software-architecture-auditor v1.3
- **Versión Next.js:** {{NEXT_VERSION}}
- **Commits desde baseline:** {{COMMITS_COUNT}}

## Estado Pre-Auditoría
- Baseline o snapshot: {{BASELINE_HASH}}
- Working tree al iniciar: {{WORKTREE_STATE}}
- Archivos en scope: {{FILES_COUNT}}
- Dependencias totales: {{DEPS_COUNT}}

## Commits Realizados Desde Baseline
{{COMMITS_LIST}}

## Hallazgos Detallados

<!-- Formato:
[TIPO] Área → Descripción
Estado actual: ...
Problema: ...
Alternativa: ...
Impacto: Alto/Medio/Bajo | Esfuerzo: Alto/Medio/Bajo
-->

## Resumen Ejecutivo
- **Total hallazgos:** {{TOTAL}}
- 🔴 **Críticos:** {{CRIT_COUNT}}
- 🟠 **Altos:** {{HIGH_COUNT}}
- 🟡 **Medios:** {{MED_COUNT}}
- 🟢 **Bajos/Info:** {{LOW_COUNT}}

## Quick Wins (Top 5)
1. ...
2. ...
3. ...
4. ...
5. ...

## Roadmap de Mejoras
### Fase 1 (inmediato, <1 día)
### Fase 2 (corto plazo, <1 semana)
### Fase 3 (largo plazo, >1 semana)

## Preguntas de Seguimiento Respondidas
1. ¿Quick wins aplicados?
2. ¿Deuda técnica grew/shrunk?
3. ¿Métricas performance improved?
4. ¿Patrones correctos se mantienen?
5. ¿Nuevos hallazgos críticos?
6. ¿Fricción operativa?

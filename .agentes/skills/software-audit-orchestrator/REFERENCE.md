# software-audit-orchestrator — Material de Referencia

> Formato del reporte consolidado y detalles del pipeline.

---

## Formato del Reporte Consolidado

```markdown
# Auditoría Consolidada — {{DATE}}

## Metadatos
- **Tipo:** Consolidado (orquestador)
- **Fecha:** {{DATE}}
- **Baseline / Snapshot:** {{HASH}}
- **Pipeline ejecutado:** code → architecture → product
- **Auditorías incluidas:**
  - software-code-auditor v1.3 → `audit_code_*.md`
  - software-architecture-auditor v1.3 → `audit_architecture_*.md`
  - software-product-auditor v1.1 → `audit_product_*.md`
- **Auditor:** software-audit-orchestrator v1.1

## Resumen Global
- Total hallazgos combinados: {{TOTAL}}
- 🔴 Críticos: {{CRIT}}
- 🟠 Altos: {{HIGH}}
- 🟡 Medios: {{MED}}
- 🟢 Bajos/Info: {{LOW}}

## Matriz Consolidada por Severidad
| Skill | 🔴 CRIT | 🟠 HIGH | 🟡 MED | 🟢 LOW | Total |
|---|---|---|---|---|---|
| Código | N | N | N | N | N |
| Arquitectura | N | N | N | N | N |
| Producto | N | N | N | N | N |
| **Total** | **N** | **N** | **N** | **N** | **N** |

## Top 10 Issues Globales
1. [SEV] [SKILL] [ID] — Descripción

## Dependencias Cross-Skill
| Hallazgo A | Hallazgo B | Relación |
|---|---|---|

## Roadmap Unificado Recomendado
### Fase 1 (Inmediato, <1 día)
### Fase 2 (Corto plazo, <1 semana)
### Fase 3 (Largo plazo, >1 semana)

## Áreas No Cubiertas

## Recomendación Final
```

El JSON consolidado permite generar la matriz automáticamente sin parsear markdown.

## Ejecución del Pipeline

```
FASE 0A: shared/scripts/resolve-baseline.sh
FASE 0B: shared/scripts/audit-context.sh
FASE 0C: npm run build && npm test && npm run lint
FASE 1:  Cargar software-code-auditor + .opencode/audit-files.json
FASE 2:  Cargar software-architecture-auditor
FASE 3:  Cargar software-product-auditor
FASE 4:  shared/scripts/consolidate.sh
```

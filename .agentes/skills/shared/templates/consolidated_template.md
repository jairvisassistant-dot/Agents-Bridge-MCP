# Auditoría Consolidada — {{DATE}}

## Metadatos
- **Tipo:** Consolidado
- **Fecha:** {{DATE}}
- **Baseline / Snapshot:** {{BASELINE_HASH}}
- **Pipeline ejecutado:** code → architecture → product
- **Build status:** {{BUILD_STATUS}}
- **Test status:** {{TEST_STATUS}}
- **Auditorías incluidas:**
  - software-code-auditor v1.3 → {{CODE_REPORT}}
  - software-architecture-auditor v1.3 → {{ARCH_REPORT}}
  - software-product-auditor v1.1 → {{PROD_REPORT}}
- **Auditor:** software-audit-orchestrator v1.1

## Resumen Global
- **Total hallazgos combinados:** {{TOTAL}}
- 🔴 **Críticos:** {{CRIT_COUNT}}
- 🟠 **Altos:** {{HIGH_COUNT}}
- 🟡 **Medios:** {{MED_COUNT}}
- 🟢 **Bajos/Info:** {{LOW_COUNT}}

## Matriz Consolidada por Severidad
| Skill | 🔴 CRIT | 🟠 HIGH | 🟡 MED | 🟢 LOW | Total |
|---|---|---|---|---|---|
| Código | {{CODE_CRIT}} | {{CODE_HIGH}} | {{CODE_MED}} | {{CODE_LOW}} | {{CODE_TOTAL}} |
| Arquitectura | {{ARCH_CRIT}} | {{ARCH_HIGH}} | {{ARCH_MED}} | {{ARCH_LOW}} | {{ARCH_TOTAL}} |
| Producto | {{PROD_CRIT}} | {{PROD_HIGH}} | {{PROD_MED}} | {{PROD_LOW}} | {{PROD_TOTAL}} |
| **Total** | **{{CRIT_COUNT}}** | **{{HIGH_COUNT}}** | **{{MED_COUNT}}** | **{{LOW_COUNT}}** | **{{TOTAL}}** |

## Top 10 Issues Globales
1. ...
2. ...

## Dependencias Cross-Skill
| Hallazgo A | Hallazgo B | Relación |
|---|---|---|

## Roadmap Unificado
### Fase 1 (Inmediato, <1 día)
### Fase 2 (Corto plazo, <1 semana)
### Fase 3 (Largo plazo, >1 semana)

## Áreas No Cubiertas

## Recomendación Final

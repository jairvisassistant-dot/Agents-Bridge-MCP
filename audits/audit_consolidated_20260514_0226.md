# Auditoría Consolidada — 2026-05-14 02:26

## Metadatos
- **Baseline:** `7179d78b1f66d46b88520a8aff80491c82c2e21d`
- **Pipeline:** código → arquitectura → producto
- **Build:** OK
- **Tests:** 119 passed / 1 failed
- **Lint:** no configurado
- **Veredicto de integridad:** **FAILED**

## Resumen global
- **Total hallazgos:** 50
- **CRITICAL:** 5
- **HIGH:** 15
- **MEDIUM:** 16
- **LOW:** 10
- **INFO:** 4

## Matriz por auditoría
| Área | CRIT | HIGH | MED | LOW | INFO | Total |
|---|---:|---:|---:|---:|---:|---:|
| Código | 1 | 6 | 5 | 4 | 2 | 18 |
| Arquitectura | 2 | 4 | 6 | 3 | 2 | 17 |
| Producto | 2 | 5 | 5 | 3 | 0 | 15 |
| **Total** | **5** | **15** | **16** | **10** | **4** | **50** |

## Top issues globales
1. **CODE-01** — El modo dry-run comparte una conexión SQLite entre threads y rompe thread-safety.
2. **ARCH-01** — La state machine es decorativa: no gobierna las transiciones reales en DB.
3. **ARCH-02** — El patrón open/close por query impide atomicidad transaccional real entre writes relacionados.
4. **PROD-01** — `--ui-only` promete conexión a un server existente, pero en realidad crea otro proceso independiente.
5. **PROD-02** — La documentación promete chat “en tiempo real”, pero el sistema usa polling cada 5s.

## Dependencias cross-skill
- **CODE-06/07 ↔ ARCH-02**: los updates no atómicos en review son una consecuencia del diseño transaccional actual.
- **CODE-08/09 ↔ ARCH-10**: el maintenance loop sin lifecycle claro es tanto bug de implementación como deuda arquitectural.
- **CODE-10 ↔ PROD-05**: la desincronización request/response en TUI pasa de bug interno a pérdida visible de confianza del operador.
- **ARCH-04 ↔ PROD-07**: el rol mutable por heartbeat rompe la promesa de permisos confiables del producto.
- **ARCH-06 ↔ PROD-01/02**: la topología real y el startup SSE refuerzan la brecha entre documentación y comportamiento.

## Verificación de integridad
La **integridad del código NO queda validada**.

Motivos:
- hay **5 hallazgos críticos**,
- existe **1 test fallando** en integración stdio,
- hay problemas de **atomicidad, permisos, concurrencia y veracidad documental**,
- el modelo operativo que se le vende al usuario **no coincide** con el comportamiento real.

## Recomendación final
No tratar este estado como “production-ready”.

Orden recomendado:
1. corregir **concurrencia/transacciones**,
2. cerrar **escalación de privilegios**,
3. arreglar **JSON malformado / respuestas inseguras**,
4. reparar **test de integración stdio**,
5. alinear **README + SPEC + CLI** con el sistema real.

## Archivos fuente del consolidado
- `audits/audit_code_20260514_0210.json`
- `audits/audit_architecture_20260514_1452.json`
- `audits/audit_product_20260514_0724.json`

# Auditoría — Metodología de Referencia

Este documento centraliza las metodologías de las 3 auditorías (código, arquitectura, producto).
El orquestador referencia este archivo para delegar trabajo a sub-agentes con prompts compactos.

---

## Auditoría de Código (software-code-auditor)

**Objetivo:** Bugs, seguridad, async correctness, race conditions, SQL injection, calidad.

### Checklist

- [ ] **Async/Await**: llamadas bloqueantes sin await, `anyio.to_thread.run_sync` correcto, IO sin timeout, `create_task` sin manejo de excepciones
- [ ] **SQL Injection**: queries parametrizadas con `?` (no concatenación), sin interpolación de input de usuario en SQL, sin fugas de información en errores
- [ ] **Race Conditions** (cada tool handler que modifica estado): transacciones atómicas (`BEGIN IMMEDIATE`), TOCTOU entre SELECT y UPDATE, `rowcount` verificado en `execute_write`, serialización entre agentes concurrentes
- [ ] **Manejo de Errores**: toda tool devuelve error estructurado, try/except específicos, timeouts en operaciones de red, comportamiento con DB bloqueada o agente desconectado
- [ ] **Type Hints**: funciones públicas con type hints, tipos coinciden con schema SQL, Optional/None manejados correctamente
- [ ] **Cobertura de Tests**: caso feliz por tool handler, validaciones cubiertas, tests de concurrencia con asyncio.gather, edge cases

### Severidades
| Severidad | Significado |
|-----------|-------------|
| CRITICAL | Bug en producción, pérdida de datos, security breach |
| HIGH | Race condition, deadlock, fuga de recursos |
| MEDIUM | Mala práctica, falta de test, código inconsistente |
| LOW | Style, type hint faltante, log incompleto |
| INFO | Observación, mejora sugerida |

---

## Auditoría de Arquitectura (software-architecture-auditor)

**Objetivo:** Diseño del sistema, permisos, concurrencia, protocolo MCP, persistencia.

### Checklist

- [ ] **Inventario Tecnológico**: cada dependencia evaluada (versión, alternativas, justificación)
- [ ] **Diseño del Protocolo MCP**: convención `dominio.accion`, inputSchema con tipos y required, errores como TextContent estructurado (no excepciones), tools que deberían ser Resources, transporte SSE vs stdio
- [ ] **State Machine**: todos los estados cubiertos, transiciones inválidas con error claro, estados huérfanos, seguridad concurrente de transiciones
- [ ] **Modelo de Permisos**: rol correcto por tool, fallback a default seguro, validación de rol en cada llamada, riesgo de privilege escalation
- [ ] **Concurrencia y Aislamiento**: SQLite WAL + BEGIN IMMEDIATE, deadlocks potenciales, maintenance loop compitiendo con tools, riesgo de starvation, atomicidad en reassign
- [ ] **Persistencia y Schema**: migraciones forward, índices para queries críticas, campos/columnas obsoletas, soporte para evolución (skills custom, múltiples planes)
- [ ] **Testing Arquitectural**: integración MCP real, cobertura de permisos, migraciones, estrés y concurrencia

### Severidades
| Severidad | Significado |
|-----------|-------------|
| CRITICAL | Vulnerabilidad arquitectural, pérdida de datos, violación de aislamiento |
| HIGH | Race condition no cubierta, permiso incorrecto, transición inválida |
| MEDIUM | Mala práctica de diseño, falta de test arquitectural |
| LOW | Convención menor, naming, documentación |
| INFO | Observación, mejora sugerida |

### Red Lines
NO repetir hallazgos de código | NO cambios cosméticos sin resolver CRIT/HIGH

---

## Auditoría de Producto (software-product-auditor)

**Objetivo:** UX, credibilidad, documentación, brecha entre promesa y comportamiento real.

### Checklist

- [ ] **Propuesta de valor y claridad**: README explica el problema, instalación/onboarding sin fricción, consistencia entre promesa y comportamiento real
- [ ] **UX de CLI y onboarding**: comandos claros, mensajes de error y éxito, flujo instalación → primer uso
- [ ] **UX de TUI/Interfaz**: status bar, feedback visual, discoverability, reconexión, indicadores de estado
- [ ] **Credibilidad y confianza**: documentación vs comportamiento real, warnings para operaciones riesgosas, estado inconsistente
- [ ] **Contenido y tono**: README, ayuda y copy con tono consistente, troubleshooting, FAQ

### Severidades
| Severidad | Significado |
|-----------|-------------|
| CRITICAL | Brecha documentación/comportamiento que engaña al usuario |
| HIGH | Funcionalidad documentada que no existe o no funciona como se describe |
| MEDIUM | UX deficiente, falta de feedback, documentación incompleta |
| LOW | Inconsistencia cosmética, copy mejorable |

### Red Lines
NO duplicar bugs técnicos salvo que impacten experiencia o confianza
NO profundizar en implementación — solo identificar síntomas visibles

---

## Formato de Hallazgo (TODAS las auditorías)

```json
{
  "id": "CODE-01",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW|INFO",
  "file": "src/agent_bridge/...",
  "line": 42,
  "title": "Título descriptivo",
  "description": "Descripción detallada del hallazgo",
  "impact": "Impacto potencial",
  "recommendation": "Qué hacer para corregirlo"
}
```

Los hallazgos se escriben en `audits/` como `.md` (humano) + `.json` (estructurado).

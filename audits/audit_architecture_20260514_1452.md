# Auditoría de Arquitectura — Agent-Bridge MCP Broker

**Fecha**: 2026-05-14 14:52
**Baseline**: `7179d78b1f66d46b88520a8aff80491c82c2e21d`
**Stack**: Python 3.12 / MCP 1.6+ / aiosqlite 0.20+ / Textual 1.0+ / httpx 0.28+
**Build**: OK
**Tests**: 119 passed / 1 failed (BrokenPipe en integración stdio)

---

## Resumen

| Severidad | Cantidad |
|-----------|----------|
| CRITICAL  | 2        |
| HIGH      | 4        |
| MEDIUM    | 6        |
| LOW       | 3        |
| INFO      | 2        |
| **Total** | **17**   |

---

## ARCH-01 — CRITICAL — State machine no protege escrituras en DB

**Archivo**: `src/agent_bridge/state/state_machine.py` (línea 1-113)
**Archivo**: `src/agent_bridge/tools/tasks.py` (líneas 183-217, 231-264)
**Archivo**: `src/agent_bridge/tools/review.py` (líneas 131-157, 188-214)

**Descripción**: `state_machine.py` define transiciones válidas con mapas `PLAN_TRANSITIONS`, `TASK_TRANSITIONS`, `REVIEW_TRANSITIONS` y expone funciones `validate_*_transition()`. Sin embargo, estas validaciones NO se ejecutan en el camino crítico de escritura. Ejemplos:

1. `_claim_task` (tasks.py:183): el guardia de concurrencia es `WHERE status = 'pending'`. Si alguien pasa un status inválido (imposible por SQL), el UPDATE falla por rowcount=0 y el handler llama a `validate_task_transition` SOLO para generar el mensaje de error — no para prevenir la escritura.

2. `_approve_review` (review.py:131): el UPDATE atomico usa `WHERE status = 'review'`. La validación `validate_task_transition` se llama DESPUÉS de detectar rowcount=0, solo para dar un mensaje informativo al cliente.

3. `_submit_work` (tasks.py:231): el WHERE usa `status IN ('in_progress', 'changes_requested')` — hardcodeado, no derivado de la state machine.

4. `plan.create` (planner.py:111): inserta directamente con status `tasks_ready`, saltándose toda la máquina de estados `idle → planning → tasks_ready`.

**Impacto**: La state machine es una capa de documentación sin enforcement real. Cambiar las transiciones en `state_machine.py` NO afecta el comportamiento del sistema. Cualquier modificación requiere cambiar BOTH el mapa de transiciones Y los WHERE clauses en cada tool handler — un coupling oculto.

**Recomendación**: Centralizar la lógica de transición: que el handler llame a `validate_task_transition(current, target)` ANTES de ejecutar el `execute_write`, y que los WHERE clauses se deriven del mapa de transiciones automáticamente. Idealmente, mover las validaciones a un middleware en `handle_call_tool` o a un método `db.transition_task(task_id, target)` que valide y ejecute en una sola operación atómica.

---

## ARCH-02 — CRITICAL — Sin conexiones compartidas ni pooling SQLite

**Archivo**: `src/agent_bridge/state/database.py` (líneas 196-234)

**Descripción**: Cada llamada a `_execute`, `_execute_write`, `_execute_one` abre una NUEVA conexión SQLite (`self._connect()`), ejecuta SQL, hace `conn.commit()` y cierra. Patrón open-close-per-call. `with_transaction` es la ÚNICA operación que retiene una conexión para múltiples queries.

Esto significa:
- Cada tool call abre 3-7 conexiones independientes (una por `execute_write` + posibles `execute_one` de verificación).
- `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000` se ejecutan en CADA conexión.
- No hay un pool de conexiones ni reutilización de statements preparados.
- `with_transaction` y `execute_write` operan en conexiones DIFERENTES, por lo que no hay atomicidad entre ellos. Los hallazgos CODE-06/07 (updates no atómicos) son una consecuencia directa.

**Impacto**: Overhead innecesario (~3ms por conexión en SQLite). Imposibilidad de tener transacciones reales entre múltiples writes. El patrón open-close elimina el propósito de WAL mode, que beneficia conexiones persistentes.

**Recomendación**: Mantener una sola conexión SQLite con WAL para todo el ciclo de vida del servidor, usando `anyio.Lock` para serializar writes. Alternativamente, implementar un pool de 2-3 conexiones reutilizables. Establecer `PRAGMA` solo al inicio (no por conexión).

---

## ARCH-03 — HIGH — Sin BEGIN IMMEDIATE en writes individuales

**Archivo**: `src/agent_bridge/state/database.py` (líneas 150-165, 220-234)

**Descripción**: `_execute_write` abre conexión, ejecuta UPDATE/INSERT, hace `conn.commit()`. No hay `BEGIN IMMEDIATE` explícito. SQLite usa `BEGIN DEFERRED` por defecto, que puede escalar a write lock solo al llegar al statement de escritura. En WAL mode con múltiples threads de `anyio.to_thread`, dos writes concurrentes pueden progresar en paralelo hasta que SQLite serializa internamente. El `busy_timeout=5000` fuerza a SQLite a reintentar hasta 5s antes de dar `SQLITE_BUSY`.

`with_transaction` SÍ usa `BEGIN IMMEDIATE` explícito (database.py:288), creando una asimetría arquitectónica: `with_transaction` es seguro para concurrencia, `execute_write` no lo es.

**Impacto**: Bajo alta concurrencia (múltiples agents llamando tools simultáneamente), los writes individuales pueden fallar con `SQLITE_BUSY` después del timeout de 5s, causando errores 500 al cliente. La ventana de contención existe aunque la probabilidad es baja para 2-3 agents.

**Recomendación**: Usar `BEGIN IMMEDIATE` en TODOS los writes (tanto `execute_write` como `with_transaction`). Si la conexión es por-call (ARCH-02), no hay contención real porque cada llamada tiene su propia conexión — pero si se migra a conexión compartida (como debería), `BEGIN IMMEDIATE` es obligatorio.

---

## ARCH-04 — HIGH — Modelo de permisos depende de estado mutable en DB

**Archivo**: `src/agent_bridge/server.py` (líneas 44-89)
**Archivo**: `src/agent_bridge/config.py` (líneas 115-128)

**Descripción**: La resolución de roles sigue: (1) `bridge.json` → (2) SQLite `agents.role` → (3) `default`. El paso (2) consulta el rol que fue establecido por `agent.heartbeat` o `agent.set_status`. Esto significa que el permiso de un agente puede CAMBIAR en runtime si otro agente (o el mismo) modifica su rol vía `agent.heartbeat`.

Además, `_check_permission` se ejecuta UNA VEZ al inicio de `handle_call_tool`, pero los handlers internos (como `handle_agent_tool`) reciben `config` y `db` y podrían ignorar la verificación. No hay un decorador o middleware que fuerce la verificación por tool.

`agent.whoami` no es publica en `_check_permission` (server.py:57), requiere autenticación para ver el propio rol.

**Impacto**: Posible privilege escalation si un agente cambia su rol a `architect` vía heartbeat. El fallback a `default` es seguro (chat-only). Pero no hay inmutabilidad del rol: `agent.heartbeat` puede sobrescribir el rol con `role_hint`.

**Recomendación**: Congelar el rol después del primer heartbeat si el agente ya existe en DB, o solo permitir cambios vía `bridge.json`. Separar permisos en un módulo inmutable que cargue roles solo desde `bridge.json` al startup.

---

## ARCH-05 — HIGH — Tool dispatch secuencial sin aislamiento

**Archivo**: `src/agent_bridge/server.py` (líneas 232-251)

**Descripción**: `handle_call_tool` itera handlers en orden fijo: plan → task → review → chat → agents → skills. El primer handler que devuelve `not None` gana. Esto es frágil: si dos handlers registran tools con el mismo nombre (ej: un custom tool `chat.spam` agregado en el futuro), solo gana el primero. Además, si `handle_plan_tool` lanza una excepción (no capturada por su try interno), los handlers subsiguientes NO se ejecutan para esa tool call.

**Impacto**: Dificulta la extensión con tools custom. Un error en un handler de plan puede dejar sin respuesta a una tool name no encontrada.

**Recomendación**: Usar un `dict[str, Callable]` de dispatch en lugar de cadena lineal. Cada handler registra su set de tools en un mapa central. La estructura de "dominio.handler" del naming permite fácil extracción del dominio para routing.

---

## ARCH-06 — HIGH — init_db() ejecutado por cada conexión SSE sin lock distribuido

**Archivo**: `src/agent_bridge/main.py` (líneas 103-104)
**Archivo**: `src/agent_bridge/state/database.py` (líneas 167-193)

**Descripción**: Cada conexión SSE llama a `await init_db()` → `db.initialize()` → `_initialize()`. Esta función ejecuta `SCHEMA_SQL` completo (incluyendo `CREATE TABLE IF NOT EXISTS`) y verifica `schema_version`. Si el server tiene múltiples workers de uvicorn (o se inician procesos separados), dos pueden detectar `schema_version=0` simultáneamente y ambas ejecutar migraciones.

Con `CREATE TABLE IF NOT EXISTS` no hay riesgo, pero `ALTER TABLE ADD COLUMN` en migraciones NO es idempotente. Aunque usando workers=1 por defecto (uvicorn default), cualquier restart rápido con conexiones concurrentes puede trigger el bug CODE-02.

**Impacto**: La segunda conexión SSE en un startup rápido falla con "duplicate column" si hay migraciones ALTER TABLE activas.

**Recomendación**: Mover migraciones a un paso separado del startup, antes de aceptar conexiones. Usar `INSERT OR IGNORE INTO _meta (key, value) VALUES ('schema_version', ?)` como lock de migración, o un archivo `.schema_version` en disco. O mejor: usar `aiosqlite` en modo singleton global con migración async en `lifespan` de Starlette.

---

## ARCH-07 — MEDIUM — Modelos Pydantic no se usan en runtime

**Archivo**: `src/agent_bridge/state/models.py` (líneas 1-120)

**Descripción**: Los modelos `Plan`, `Task`, `Review`, `Agent`, `Message`, `Thread` con validación Pydantic están definidos pero NUNCA se instancian en ningún tool handler. Toda la data viaja como `dict` desde SQLite `Row` directamente a `json.dumps()` en las respuestas. Los modelos sirven exclusivamente como documentación del schema.

`Skill` es el único modelo usado en `config.py` (línea 113: `Skill(**s)`), y `PlanStatus`, `TaskStatus`, etc. se usan como type aliases en `state_machine.py`.

**Impacto**: Cero validación de datos en runtime. Si un campo `description` se escribe como `None` en DB, el JSON de respuesta puede contener `null` donde el cliente espera un string. No hay serialización consistente (fechas, enums, etc.).

**Recomendación**: Usar `model_validate` de Pydantic en los handlers de lectura (`task.get`, `plan.get`, `chat.read`), y `model_dump(mode='json')` para serialización consistente. Esto eliminaría los bugs CODE-03/04/05/11 (JSON injection) porque Pydantic escapa strings automáticamente.

---

## ARCH-08 — MEDIUM — plan.create salta la máquina de estados

**Archivo**: `src/agent_bridge/tools/planner.py` (línea 112)

**Descripción**: `_create_plan` inserta el plan directamente con `status='tasks_ready'`, saltándose las transiciones definidas: `idle → planning → tasks_ready`. No hay ninguna verificación de que el plan deba pasar por esos estados. La state machine las define (state_machine.py:47-48) pero `plan.create` las ignora por completo.

**Impacto**: La state machine de planes es incoherente. Un plan recién creado aparece como "tasks_ready" sin haber pasado por "planning". La métrica "cuántos planes están en planning" siempre es 0.

**Recomendación**: Insertar con `status='idle'` y requerir `plan.update(plan_id, status='planning')` como paso explícito, o renombrar el estado inicial de `plan.create` a algo como `draft`. Sincronizar el modelo de estados con la implementación real.

---

## ARCH-09 — MEDIUM — Plan state machine permite transiciones imposibles

**Archivo**: `src/agent_bridge/state/state_machine.py` (líneas 46-52)

**Descripción**: El mapa `PLAN_TRANSITIONS` define:
- `idle → planning, tasks_ready` (pero tasks_ready desde idle no es válido en la práctica)
- `planning → tasks_ready, idle`
- `tasks_ready → in_progress, idle`
- `in_progress → completed, idle`
- `completed → set()` (terminal)

No hay una herramienta `plan.complete` — solo `plan.update(status='completed')`. Si un architect escribe `plan.update(plan_id, status='completed')`, la validación de `plan.update` llama a `validate_plan_transition(current, 'completed')` que requiere `current == 'in_progress'`. Cualquier otro estado actual rechaza la transición.

Pero la transición `idle → tasks_ready` es válida en el mapa aunque `plan.create` usa ese mismo salto. La transición `tasks_ready → idle` permite volver atrás desde tasks_ready sin pasar por planning.

**Impacto**: El mapa permite transiciones que no tienen sentido de negocio (`idle → tasks_ready` directo) pero la implementación real (plan.create) ya lo hace, así que el mapa es correcto para la implementación actual — el problema es al revés: la implementación bypassa todo el modelo.

**Recomendación**: Revisar los estados de plan para reflejar el flujo real. Si `plan.create` crea en `tasks_ready`, eliminar `idle` y `planning` del modelo, o implementar el flujo completo.

---

## ARCH-10 — MEDIUM — Maintenance loop no cancelable y singleton inconsistente

**Archivo**: `src/agent_bridge/server.py` (líneas 154-170, 276-285)

**Descripción**: `_maintenance_loop` se inicia vía `asyncio.create_task` dentro de la coroutine `init()`. Características:

1. **No cancelable en shutdown**: `create_task` no guarda el task handle. No se cancela en el cierre de la conexión SSE/stdio. Si el proceso termina, la tarea se aborta. En SSE con múltiples conexiones, cada `init_db()` inicia OTRO maintenance loop, creando duplicados compitiendo por los mismos recursos.

2. **Mezcla asyncio/anyio**: usa `asyncio.sleep()` y `asyncio.CancelledError` (CODE-08/09). El proyecto entra por `anyio.run()` como entry point (main.py:922, 688, 712). En backends no-asyncio (Trio), `asyncio.sleep()` no funciona.

3. **Singleton inconsistente**: El primer SSE connection o stdio handler corre la única conexión DB (si usa ARCH-02 corregido), pero el maintenance loop se crea por cada llamada a `init()`. Si el server recibe 3 conexiones SSE y sobrevive (no es el caso porque cada conexión llama a `init_db` que es la misma función), habría 3 loops.

**Impacto**: Tarea huérfana en shutdown. Múltiples maintenance loops compitiendo. Posibles reassignments duplicados o race conditions en el auto-resolve de threads.

**Recomendación**: Usar un `anyio.CancelScope` almacenado como atributo del server o un módulo global. Iniciar el maintenance loop UNA SOLA VEZ, en un `lifespan` de Starlette. Cancelarlo explícitamente en shutdown. Usar `anyio.sleep()`.

---

## ARCH-11 — MEDIUM — agent.set_status sin ownership check

**Archivo**: `src/agent_bridge/tools/agents.py` (líneas 186-209)

**Descripción**: `agent.set_status` acepta `agent_id` y `status` y actualiza sin verificar que el caller sea el propietario del agent_id. Cualquier agente autenticado puede cambiar el estado de cualquier otro agente. Un architect malicioso (o bug) podría marcar al developer como "offline", triggerando el stale reassignment de todas sus tareas.

**Impacto**: Un agente puede sabotear el estado de otro, forzando reassignment de tareas y pérdida de contexto. No hay control de acceso granular por recurso (solo por tool name).

**Recomendación**: Extraer `_agent_id` de los args (inyectado en server.py:216) y verificar que coincida con el `agent_id` solicitado. Solo permitir `agent.set_status` sobre uno mismo. Si se necesita administración remota, crear `admin.set_agent_status` con rol "admin" separado.

---

## ARCH-12 — MEDIUM — INSERT OR REPLACE en heartbeat puede perder historial

**Archivo**: `src/agent_bridge/tools/agents.py` (líneas 117-123)

**Descripción**: `agent.heartbeat` usa `INSERT OR REPLACE INTO agents` que sobreescribe toda la fila si el `agent_id` ya existe. Esto incluye `connected_since` — aunque el SQL usa `COALESCE` para preservarlo, cualquier otro campo se reemplaza completamente. `role` se pisa con el valor resuelto, `metadata` se pierde (vuelve a `'{}'`).

**Impacto**: Si un administrador agrega metadata a un agente en DB directamente (o vía una futura tool), el próximo heartbeat del agente la borra. No hay merge de campos.

**Recomendación**: Usar `INSERT ... ON CONFLICT(agent_id) DO UPDATE SET status=excluded.status, last_seen=excluded.last_seen` para actualizar solo campos de presencia sin tocar `role` ni `metadata`.

---

## ARCH-13 — LOW — Tool `hello` rompe convención de naming

**Archivo**: `src/agent_bridge/server.py` (líneas 24-28)

**Descripción**: Todas las tools siguen `domain.action` (`plan.create`, `task.claim`, `chat.send`, `agent.heartbeat`, `review.approve`, `skill.list`). `hello` es la única sin dominio. No tiene `inputSchema` útil ni parámetros.

**Impacto**: Menor — inconsistencia cosmética. Si un cliente implementa routing por dominio, `hello` no tiene dominio para rutear.

**Recomendación**: Renombrar a `bridge.health` o `system.ping`. Dejar `hello` como alias para compatibilidad.

---

## ARCH-14 — LOW — inputSchema sin `additionalProperties: false`

**Archivo**: Todos los tool definitions en `src/agent_bridge/tools/*.py`

**Descripción**: Ningún `inputSchema` define `"additionalProperties": false`. El MCP spec permite que los clients envíen propiedades extra no declaradas en el schema. Los handlers las ignoran silenciosamente (acceden solo a `args.get("campo_conocido")`).

Actualmente no hay riesgo porque las propiedades extra se ignoran. Pero si en el futuro una propiedad nueva se agrega al schema pero un cliente antiguo envía una propiedad con typo, el typo se ignora sin warning.

**Impacto**: Depuración difícil de errores de naming en parámetros.

**Recomendación**: Agregar `"additionalProperties": false` a todos los `inputSchema`. Considerar un middleware que logee propiedades no esperadas.

---

## ARCH-15 — LOW — Falta modelo de Resources MCP

**Archivo**: `src/agent_bridge/server.py` (línea 199) y todos los tool handlers

**Descripción**: El servidor implementa `list_tools()` y `call_tool()` pero NO implementa `list_resources()`, `read_resource()`, ni `subscribe_resource()`. Datos como `task.list`, `plan.list`, `chat.read` devuelven listas/entidades que serían más naturales como MCP Resources con soporte de suscripción/pub-sub.

La TUI (chat_tui.py) implementa polling cada 5s con `chat.read` pasando `since=rowid` — esto es un patrón de resource subscription implementado manualmente sobre tools.

**Impacto**: La TUI hace polling constante cada 5s, incluso cuando no hay cambios. Mayor latencia y tráfico comparado con notificaciones push vía resources. No hay subscription mechanism accesible a otros clients MCP.

**Recomendación**: Modelar `chat.read` como un Resource con URI `agent-bridge://messages/{since}` y soporte de suscripción. Similar para `task.list` → `agent-bridge://tasks/{status}`. El polling de la TUI se reemplazaría por una suscripción.

---

## ARCH-16 — INFO — request._send es API privada de Starlette

**Archivo**: `src/agent_bridge/main.py` (línea 106)

**Descripción**: `sse.connect_sse(request.scope, request.receive, request._send)` usa `request._send`, un atributo privado de Starlette. No forma parte de la API pública y puede romperse en upgrades de Starlette (que es dependencia indirecta vía `mcp[cli]`).

**Impacto**: Riesgo de rotura en upgrades de Starlette. Ya identificado como CODE-15 en auditoría de código.

**Recomendación**: Monitorear si MCP SDK expone una forma de acceder al `send` channel. Verificar compatibilidad en CI contra múltiples versiones de Starlette.

---

## ARCH-17 — INFO — Todas las respuestas usan TextContent sin tipos MCP alternativos

**Archivo**: Todos los tool handlers

**Descripción**: El 100% de las respuestas son `list[types.TextContent]`. No se usan `ImageContent`, `EmbeddedResource`, `AudioContent`, ni ningún otro tipo MCP. Esto es correcto para un broker de chat/planificación, pero limita:

- No se pueden adjuntar diffs como `EmbeddedResource` con URI a un sistema de archivos
- No se pueden enviar imágenes de diagramas de arquitectura
- No hay contenido embebido navegable

**Impacto**: Para el caso de uso actual (texto estructurado JSON) es suficiente. Pero limita extensibilidad futura.

**Recomendación**: Documentar como decisión arquitectónica consciente. Para diffs grandes, considerar `EmbeddedResource` apuntando a un file:// URI o blob storage.

---

## Resumen de hallazgos código ↔ arquitectura

| Código     | Arquitectura | Relación |
|------------|-------------|----------|
| CODE-01    | ARCH-02     | Causa: conexión compartida es síntoma de no-pooling |
| CODE-02    | ARCH-06     | Causa: init_db() sin lock es diseño inseguro |
| CODE-06/07 | ARCH-02     | Síntoma: writes separados sin transacción compartida |
| CODE-08/09 | ARCH-10     | Causa directa: maintenence loop mal diseñado |
| CODE-10    | —           | Bug de cliente TUI, no arquitectural |
| CODE-03/04/05/11 | ARCH-07 | Se resuelven usando modelos Pydantic en runtime |

# 🔍 Informe de Auditoría — Agents-Bridge-MCP v1

> **Fecha:** 2026-06-06  
> **Alcance:** Código fuente completo (`src/`, `tests/`, `extensions/vscode/`)  
> **Líneas analizadas:** ~5,200 (backend Python) + ~300 (extensión VS Code)

---

## Resumen Ejecutivo

Proyecto: **Agent Bridge** — Broker MCP para colaboración multi-agente (Claude Code + OpenCode + Humano).

**Stack:** Python 3.12+ · MCP SDK · SQLite + WAL · Textual (TUI) · Starlette/Uvicorn (SSE)

**Total de hallazgos:** 20 — 2 críticos, 5 altos, 7 medios, 6 bajos.

---

## 🔴 CRÍTICOS

### 1. Modo `--dry-run` completamente roto

**Archivo:** `src/agent_bridge/state/database.py` (líneas 194-200, 295-323)

**Causa raíz:** En modo dry-run, `_connect()` crea una conexión `:memory:` **nueva en cada llamada**. Esto significa que:

- `_initialize()` escribe el schema en la conexión A
- `_execute()`, `_execute_write()`, `with_transaction()` obtienen la conexión B (vacía)
- Cualquier operación de lectura/escritura subsecuente falla con "no such table"

Además, `with_transaction()` (línea 295) **ignora completamente `_dry_run`**: no loggea, no skipea, ejecuta realmente contra una `:memory:` sin tablas.

**Impacto:** El modo dry-run es inservible. Cualquier comando o herramienta que use `--dry-run` y ejecute operaciones transaccionales falla silenciosamente o crashea.

```python
# database.py:194 — fresh connection cada vez en dry-run
if self._dry_run:
    conn = sqlite3.connect(":memory:")  # ← NUEVA cada llamada
    ...
    return conn

# database.py:295 — ignora dry_run completamente
async def with_transaction(self, func):
    def _run():
        conn = self._connect()  # ← conexión fresca sin tablas
        conn.execute("BEGIN IMMEDIATE")
        result = func(conn)     # ← falla: no such table
```

---

### 2. Búsqueda frágil con `INSTR` en arrays JSON

**Archivo:** `src/agent_bridge/tools/chat.py` (línea 625)

**Causa raíz:** `INSTR` hace búsqueda de subcadena sobre la representación JSON del array de participantes. Un nombre corto puede dar falso positivo contra uno largo.

```python
# chat.py:621-628
rows = await db.execute(
    """SELECT * FROM threads
       WHERE status = 'open'
         AND participants != '[]'
         AND INSTR(participants, ?) > 0   # ← búsqueda de subcadena
         AND (current_turn IS NULL OR current_turn = ?)
       ORDER BY last_activity_at DESC""",
    (json.dumps(agent_name), agent_name),
)
```

**Ejemplo:** Si `agent_name = "arq"`, `json.dumps("arq")` → `'"arq"'`. `INSTR` busca `"arq"` dentro de `["arquitecto", ...]` → **falso positivo**.

**Impacto:** Un agente puede recibir threads que no son para él. Difícil de debuggear porque el error es intermitente y depende de los nombres.

---

## 🟡 ALTOS

### 3. `task.claim` permite asignar cualquier rol como assignee

**Archivo:** `src/agent_bridge/tools/tasks.py` (línea 169)

**Causa raíz:** El parámetro `agent` lo provee el caller y no se valida contra el rol inyectado por el servidor (`_agent_role`).

```python
async def _claim_task(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    agent = args.get("agent", "developer")  # ← del input, no del servidor
    ...
```

Un developer puede llamar `task.claim(task_id="...", agent="architect")` y la tarea queda asignada al arquitecto en la DB.

**Impacto:** Datos inconsistentes en la columna `assignee`. Aunque el permission layer bloquea tools que no corresponden al rol, el dato en la DB queda incorrecto, generando confusión en la UI de kanban y en los reportes.

---

### 4. `agent.set_status` permite cambiar estado de OTRO agente

**Archivo:** `src/agent_bridge/tools/agents.py` (líneas 276-293)

**Causa raíz:** No verifica que el `agent_id` del input coincida con el `_agent_id` inyectado por el servidor.

```python
async def _set_status(db: Database, args: dict) -> list[types.TextContent]:
    agent_id = args.get("agent_id")   # ← del input
    status = args.get("status")
    ...
    await db.execute(
        "UPDATE agents SET status = ? WHERE agent_id = ?",
        (status, agent_id),            # ← actualiza cualquier agente
    )
```

**Impacto:** Un agente puede marcar a otro como `offline` o cambiar su estado arbitrariamente. Viola la especificación que dice "El propio agente" para esta tool.

---

### 5. `review.start` crea revisiones duplicadas

**Archivo:** `src/agent_bridge/tools/review.py` (líneas 100-104)

**Causa raíz:** No verifica si ya existe una revisión activa (`status = 'in_review'`) para la misma tarea antes de insertar.

```python
review_id = str(uuid.uuid4())
await db.execute(
    "INSERT INTO reviews (id, task_id, status) VALUES (?, ?, 'in_review')",
    (review_id, task_id),  # ← inserta siempre, sin check de duplicado
)
```

**Impacto:** Múltiples revisiones activas para la misma tarea. `review.approve` y `review.request_changes` actualizan la última (ORDER BY created_at DESC LIMIT 1), dejando las anteriores huérfanas sin resolver.

---

### 6. Background maintenance loop fire-and-forget irrecuperable

**Archivo:** `src/agent_bridge/server.py` (líneas 301-316)

**Causa raíz:** El task de mantenimiento se lanza con `asyncio.create_task` sin manejo de cancelación ni reinicio.

```python
asyncio.get_running_loop().create_task(_wrapper())  # ← fire-and-forget
```

- Si el loop crashea, **no se reinicia nunca**
- El `_maintenance_scope` global es singleton y jamás se cancela ni reemplaza
- No hay forma de reiniciar el loop sin reiniciar todo el servidor

**Impacto:** Si el maintenance loop muere, los agentes stale no se limpian, los threads no se resuelven automáticamente y el sistema degrada silenciosamente.

---

### 7. `chat.read` marca como leído inconsistentemente con target filter

**Archivo:** `src/agent_bridge/tools/chat.py` (líneas 563-566)

**Causa raíz:** Cuando hay filtro `target`, marca TODOS los mensajes devueltos como leídos. Sin filtro, no marca ninguno.

```python
if target:
    message_ids = [m["id"] for m in messages]
    for mid in message_ids:
        await db.mark_message_read(mid)  # ← uno por uno en loop
```

**Problemas:**
- Comportamiento inconsistente entre llamadas con y sin filtro
- Marca mensajes uno por uno en vez de un solo `UPDATE ... WHERE id IN (...)`
- Si el target está offline y otro agente lee sus mensajes, los marca como leídos para el target

---

## 🟠 MEDIOS

### 8. `plan.create` bypasses la máquina de estados

**Archivo:** `src/agent_bridge/tools/planner.py` (línea 108)

```python
await db.execute(
    "INSERT INTO plans (id, title, description, status) VALUES (?, ?, ?, 'tasks_ready')",
    (plan_id, title, description),
)
```

El plan se crea directamente en `tasks_ready`, saltándose la transición `idle → planning → tasks_ready` definida en la máquina de estados.

**Impacto:** El estado `planning` es inalcanzable desde el código. Ningún agente ni UI puede expresar que un plan está en borrador.

---

### 9. `with_transaction` no respeta `dry_run`

**Archivo:** `src/agent_bridge/state/database.py` (línea 295)

Confirmación del punto 1 con impacto específico: `with_transaction` es el único método de escritura que no checkea `_dry_run`. Operaciones como `record_pong()`, `resolve_thread_atomic()` y el envío de mensajes con turn-taking se ejecutan realmente contra una conexión `:memory:` que no tiene las tablas.

---

### 10. `bridge.db` / `bridge.db-shm` / `bridge.db-wal` no están en `.gitignore`

**Archivo:** `.gitignore` (línea 21)

Los archivos de base de datos SQLite existen en el working tree y no están gitignoreados:

```bash
$ ls -la bridge.db*
-rw-r--r-- bridge.db
-rw-r--r-- bridge.db-shm
-rw-r--r-- bridge.db-wal
```

**Riesgos:**
- Bases de datos SQLite commiteadas pueden corromperse con accesos concurrentes
- Exposición de datos de sesiones de prueba
- Conflictos de merge frecuentes por cambios en WAL/SHM

---

### 11. `_approve_review` y `_request_changes` con código muerto

**Archivo:** `src/agent_bridge/tools/review.py` (líneas 140-152, 206-218)

```python
if affected == 0:
    row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return error
    try:
        validate_task_transition(row["status"], "approved")  # ← si pasa, raisea
    except TransitionError as e:
        return json.dumps({"error": str(e)})
    return error_msg  # ← solo alcanzable si validate NO raisea
```

Si `validate_task_transition` pasa, el UPDATE debería haber funcionado porque el único status válido es `review`. No hay escenario donde validate pase y UPDATE falle. El flujo después del `try/except` es dead code.

---

### 12. `_format_time` puede crashear con `astimezone()` en datetimes naive

**Archivo:** `src/agent_bridge/ui/chat_tui.py` (líneas 499-510), duplicado en `tui_bridge.py` (línea 227)

```python
dt = datetime.fromisoformat(iso_str)
if dt.tzinfo is not None:
    dt = dt.astimezone()  # ← ValueError si dt es naive
```

Si otro proceso escribe timestamps naive en la DB (sin timezone), `fromisoformat` lo acepta, pero `astimezone()` raisea `ValueError`. El `except ValueError` lo captura, pero la función devuelve `iso_str[:5]` en vez del timestamp formateado.

---

### 13. `thread_get_pending` semántica ambigua con `current_turn IS NULL`

**Archivo:** `src/agent_bridge/tools/chat.py` (líneas 621-628)

```sql
AND (current_turn IS NULL OR current_turn = ?)
```

Cuando `current_turn IS NULL`, el thread se devuelve como pendiente. Pero si el thread tiene `current_turn IS NULL` y **ya tiene mensajes** (el path non-participant no asigna turno), se muestra como pendiente igual. No hay forma de distinguir "thread recién creado sin actividad" de "thread con actividad pero sin turno asignado".

---

### 14. `move_task` en TUI valida fuera de transacción

**Archivo:** `src/agent_bridge/ui/tui_bridge.py` (líneas 60-89)

```python
if not can_transition("task", current, new_status):
    return False

updated = await self._db.execute_write(
    "UPDATE tasks SET status = ? WHERE id = ? AND status = ?",
    (new_status, task_id, current),  # ← check de concurrencia correcto
)
return updated > 0
```

La validación con `can_transition` ocurre FUERA del `execute_write`. Entre validación y UPDATE, otro proceso puede cambiar el status. El UPDATE optimista (WHERE current_status) es correcto, pero el mensaje de error devuelve `False` sin distinguir entre "transición inválida" y "concurrencia".

---

## 🔵 BAJOS

### 15. `plan.get` no devuelve tasks asociadas

**Archivo:** `src/agent_bridge/tools/planner.py` (líneas 121-135)

`plan.get` solo devuelve `plan_id`, `title`, `status`. No incluye las tasks del plan ni su descripción. Los agentes y la UI tienen que hacer una segunda llamada `task.list(plan_id=...)`.

---

### 16. `chat_tui.py` — Timeout duro de 30s en MCPClient

**Archivo:** `src/agent_bridge/ui/chat_tui.py` (línea 210)

```python
response_bytes = await asyncio.wait_for(self._process.stdout.readline(), timeout=30)
```

Si el servidor tarda más de 30s (operaciones pesadas, maintenance loop con muchos datos), el mensaje se pierde y el cliente inicia reconexión innecesaria. No hay configuración ni backoff para este timeout.

---

### 17. Skills JSON cargados a nivel de módulo sin hot-reload

**Archivo:** `src/agent_bridge/config.py` (línea 177)

```python
BUILTIN_SKILLS = _load_builtin_skills()
```

Se cargan al importar el módulo. Si alguien edita un skill JSON mientras el servidor corre, los cambios no se reflejan hasta reiniciar el proceso.

---

### 18. Config paths frágiles y no documentados

**Archivo:** `src/agent_bridge/config.py` (líneas 13-16)

```python
CONFIG_PATHS = [
    Path.cwd() / "bridge.json",
    Path.home() / ".config" / "agent-bridge" / "bridge.json",
    Path.home() / ".agent-bridge.json",
]
```

- Relativo a `cwd`: si el usuario corre `agent-bridge` desde otro directorio, la configuración no se encuentra
- `~/.agent-bridge.json` no está documentado en el README ni en la spec
- No hay soporte para `AGENT_BRIDGE_CONFIG` env var para override

---

### 19. `TaskItem` muestra UUID completo — ilegible en terminal

**Archivo:** `src/agent_bridge/ui/kanban_board.py` (línea 75)

```python
lines = [f"{icon} #{task_id} {title}", ...]
```

`task_id` es un UUID de 36 caracteres. Ocupa la mitad del ancho de la terminal (~40 chars para "🔧 #550e8400-e29b-41d4-a716-446655440000 Feature X"). El layout de la TUI se rompe fácilmente con títulos largos.

---

### 20. No hay migración inversa (rollback)

**Archivo:** `src/agent_bridge/state/database.py` (línea 111)

`_run_migrations` solo migra hacia adelante (version check + apply). Si alguien downgradea el paquete, el schema queda en una versión más nueva que el código espera. No hay `_run_reverse_migrations`.

---

## 📊 Flujo Integrado — Puntos de Ruptura

Diagrama del ciclo completo con bugs señalados:

```
plan.create ──→ tasks_ready ✓
     │
task.create ──→ pending ✓
     │
task.claim ───→ in_progress ⚠️ [bug #3: assignee forzable]
     │
task.submit_work ──→ review ✓
     │
review.start ──→ in_review ⚠️ [bug #5: duplicados]
     │
review.approve ─→ approved ⚠️ [bug #11: código muerto]
```

**Puntos donde el flujo se rompe:**

1. **Modo dry-run** (bug #1): Cualquier operación con transacción crashea inmediatamente.
2. **Maintenance loop muerto** (bug #6): Tasks `in_progress` de agentes caídos nunca se reasignan. Sistema degrada silenciosamente.
3. **Developer malicioso/confundido** (bug #3): Asignaciones inconsistentes que sobreviven en la DB.
4. **Doble review.start** (bug #5): Dos revisiones activas, la primera invisible, la segunda mutable.
5. **Thread con nombres ambigüos** (bug #2): Notificaciones cruzadas entre agentes.
6. **Extension VS Code falla en cadena** (bug #6 indirecto): Si el server SSE muere, el polling de la extensión no tiene reconexión elegante (ver `extension.ts` línea 187: `setInterval` sin check de conectividad).

---

## 🎯 Prioridad de Corrección Recomendada

| # | Bug | Prioridad | Dificultad | Archivo |
|---|-----|-----------|------------|---------|
| 1 | Modo `--dry-run` roto | 🔴 Crítica | Baja | `database.py` |
| 2 | `INSTR` en JSON arrays | 🔴 Crítica | Baja | `chat.py` |
| 3 | `task.claim` sin validar `agent` | 🟡 Alta | Baja | `tasks.py` |
| 4 | `agent.set_status` sin ownership check | 🟡 Alta | Baja | `agents.py` |
| 5 | `review.start` duplicados | 🟡 Alta | Baja | `review.py` |
| 6 | Maintenance loop irrecuperable | 🟡 Alta | Media | `server.py` |
| 7 | `chat.read` marca como leído inconsistente | 🟡 Alta | Baja | `chat.py` |
| 8 | `plan.create` bypass state machine | 🟠 Media | Baja | `planner.py` |
| 9 | `with_transaction` ignora dry-run | 🟠 Media | Baja | `database.py` |
| 10 | `.gitignore` sin bridge.db | 🟠 Media | Mínima | `.gitignore` |
| 11 | Código muerto en approve/request_changes | 🟠 Media | Baja | `review.py` |
| 12 | `_format_time` naive crash | 🟠 Media | Baja | `chat_tui.py` |
| 13 | Semántica ambigua en `thread_get_pending` | 🟠 Media | Media | `chat.py` |
| 14 | Validación fuera de transacción en TUI | 🟠 Media | Baja | `tui_bridge.py` |
| 15 | `plan.get` sin tasks | 🔵 Baja | Baja | `planner.py` |
| 16 | Timeout duro 30s en MCPClient | 🔵 Baja | Baja | `chat_tui.py` |
| 17 | Skills sin hot-reload | 🔵 Baja | Media | `config.py` |
| 18 | Config paths frágiles | 🔵 Baja | Baja | `config.py` |
| 19 | UUID completo en TaskItem | 🔵 Baja | Mínima | `kanban_board.py` |
| 20 | Sin migración inversa | 🔵 Baja | Media | `database.py` |

---

## 🧩 Análisis de Completitud por Funcionalidad

### Leyenda

| Símbolo | Significado |
|---------|-------------|
| ✅ | Completa — el flujo principal funciona y cumple su propósito |
| ⚠️ | Incompleta — el flujo principal funciona pero faltan features especificadas |
| ❌ | Ausente — la funcionalidad está especificada pero no implementada |
| 🐛 | Rota — el flujo tiene bugs que impiden su correcto funcionamiento |

---

### 1. 🎯 Máquina de Estados — `state_machine.py`

**Propósito:** Validar todas las transiciones de estado para planes, tareas, revisiones y threads.

**Cobertura:**

| Entidad | Estados definidos | Transiciones cubiertas |
|---------|------------------|----------------------|
| Plan | 5 (`idle`, `planning`, `tasks_ready`, `in_progress`, `completed`) | 5/5 posibles |
| Task | 5 (`pending`, `in_progress`, `review`, `approved`, `changes_requested`) | 5/5 posibles |
| Review | 4 (`pending`, `in_review`, `approved`, `changes_requested`) | 4/4 posibles |
| Thread | 2 (`open`, `resolved`) | 2/2 posibles |

**Resultado: ✅ Completa**

Todas las transiciones definidas en los modelos tienen su correspondiente validación. Cada literal de estado aparece en el mapa de transiciones (verificado por tests). La función `can_transition()` da soporte a la UI para mostrar destinos válidos.

**Problema detectado:** Aunque la máquina de estados es completa, `plan.create` (en `planner.py:108`) y `review.start` (en `review.py:92`) NO la usan. Usan checks manuales en su lugar.

---

### 2. 🗄️ Capa de Base de Datos — `database.py`

**Propósito:** Persistencia SQLite con WAL, migraciones, transacciones atómicas, export/import, dry-run.

**Operaciones soportadas:**

| Operación | Implementada | Funciona |
|-----------|-------------|----------|
| Schema + migraciones v1→v6 | ✅ | ✅ |
| Transacciones atómicas (`with_transaction`) | ✅ | ✅ |
| Export/Import de planes | ✅ | ✅ |
| Detección y reasignación de agentes stale | ✅ | ✅ |
| Ping/Pong | ✅ | ✅ |
| Notificaciones del sistema | ✅ | ✅ |
| Marcado de mensajes como leídos | ✅ | ✅ |
| Resolución atómica de threads | ✅ | ✅ |
| **Modo dry-run** | ✅ | 🐛 **ROTO** |
| Migraciones inversas | ❌ | N/A |

**Resultado: ⚠️ Incompleta**

La base de datos es funcional y robusta para operación normal. El modo dry-run está roto (bug #1), y `with_transaction` no respeta la bandera dry_run (bug #9). No hay migraciones inversas.

**Flujo cruzado:** Todas las tools reciben `db: Database`. Export → Import funciona como roundtrip completo. Las notificaciones del sistema (`send_system_notification`, `notify_chat`) son usadas desde tools de review, tasks y agents para eventos del sistema.

---

### 3. 🖥️ Servidor MCP — `server.py`

**Propósito:** Servidor core, registro de tools, capa de permisos, loop de mantenimiento.

**Responsabilidades:**

| Componente | Estado | Notas |
|-----------|--------|-------|
| Registro de tools (25+ tools) | ✅ | Todas registradas en `ALL_TOOLS` |
| Capa de permisos (`_check_permission`) | ✅ | Resuelve rol y valida contra skill |
| Inyección de contexto (`_agent_id`, `_agent_role`, `_sender_name`) | ✅ | Inyectado en `args` antes de dispatch |
| Logging estructurado (request_id, duración) | ✅ | |
| Manejo de errores con respuestas JSON | ✅ | |
| **Maintenance loop** (stale agents + threads) | ⚠️ | Fire-and-forget sin recuperación |

**Resultado: ⚠️ Incompleta**

El servidor funciona correctamente para el flujo principal. El maintenance loop es frágil (bug #6): si crashea, no se reinicia, y los agentes stale quedan sin limpiar para siempre.

**Flujo cruzado:** Es el punto de entrada de TODAS las llamadas. La capa de permisos es el gatekeeper. El contexto de agente inyectado (`_agent_id`, `_agent_role`, `_sender_name`) alimenta a todos los handlers de tools.

---

### 4. 📋 Tools de Plan — `planner.py`

**Propósito:** Crear, leer, actualizar, listar, exportar e importar planes de trabajo.

**Tools expuestas:**

| Tool | Implementada | Estado |
|------|-------------|--------|
| `plan.create` | ✅ | Crea plan en `tasks_ready` directo |
| `plan.get` | ⚠️ | Solo devuelve id, title, status — sin tasks |
| `plan.list` | ✅ | |
| `plan.update` | ✅ | Valida con máquina de estados |
| `plan.export` | ✅ | Exporta plan + tasks + reviews |
| `plan.import` | ✅ | Importa desde JSON exportado |

**Resultado: ⚠️ Incompleta**

**Features faltantes vs. especificación:**
- `plan.check_readiness` — mencionado en el flujo de la spec pero ausente
- `plan.delete` / `plan.archive` — no hay forma de eliminar planes
- `plan.get` no incluye tasks, forzando una segunda llamada `task.list(plan_id=...)`
- `plan.create` salta el estado `planning` y crea directo en `tasks_ready`

**Flujo cruzado:** `plan.create` → produce `plan_id` → consumido por `task.create`. Export produce JSON → consumido por Import. `plan.get` → su salida NO incluye tasks (forzando llamada adicional).

---

### 5. 📝 Tools de Tareas — `tasks.py`

**Propósito:** Crear, listar, claimear, obtener, submitear trabajo y obtener diff de tareas.

**Tools expuestas:**

| Tool | Implementada | Estado |
|------|-------------|--------|
| `task.create` | ✅ | Requiere `plan_id` |
| `task.list` | ✅ | Filtro por plan_id y status |
| `task.claim` | ⚠️ | No valida `agent` contra caller (bug #3) |
| `task.get` | ✅ | |
| `task.submit_work` | ✅ | Incluye diff opcional |
| `task.get_diff` | ✅ | Para revisión del arquitecto |

**Resultado: ⚠️ Incompleta**

**Features faltantes vs. especificación:**
- **Dependencias entre tareas** — la spec menciona detección de ciclos en dependencias. No hay campo `depends_on` en la tabla ni lógica de validación.
- `task.update` / `task.delete` — no hay forma de modificar o eliminar tareas
- `task.claim` permite asignar cualquier rol (bug #3)

**Flujo cruzado:**
```
task.create(plan_id) ──→ DB (pending)
task.claim ──→ DB (in_progress, assignee) ──→ notifica chat
task.submit_work ──→ DB (review, diff) ──→ notifica chat + notifica arquitecto
task.get_diff ──→ output ──→ consumido por review (arquitecto)
```

El flujo claim → submit → review está completo. Pero si `task.claim` recibe `agent="architect"` en vez del rol real, el `assignee` queda incorrecto y las notificaciones del sistema apuntan al destinatario equivocado.

---

### 6. 🔍 Tools de Revisión — `review.py`

**Propósito:** Iniciar, aprobar, solicitar cambios y obtener historial de revisiones.

**Tools expuestas:**

| Tool | Implementada | Estado |
|------|-------------|--------|
| `review.start` | ⚠️ | Crea duplicados (bug #5) |
| `review.approve` | 🐛 | Código muerto en validación (bug #11) |
| `review.request_changes` | 🐛 | Código muerto en validación (bug #11) |
| `review.get_history` | ✅ | |

**Resultado: ⚠️ Incompleta**

**Features faltantes vs. especificación:**
- **Máximo 3 ciclos de revisión** — la spec dice "máximo 3 ciclos review → changes → review, luego escalar al humano". Esto NO está implementado. El campo `restrictions.max_concurrent_reviews` existe en `config.py` pero NUNCA se verifica programáticamente.
- **`cannot_approve_own_work`** — la restricción existe en el modelo de Skill pero NUNCA se verifica.
- **Escalación automática al humano** — no hay código que detecte 3 ciclos y escale.
- `review.start` no usa la máquina de estados (checkea manualmente `task["status"] != "review"`)
- `review.start` no verifica si ya hay un review activo → duplicados
- No hay forma de cerrar/rechazar un review sin approve o request_changes

**Flujo cruzado:**
```
review.start(task_id) ──→ DB (in_review)
review.approve ──→ DB task: approved, review: approved ──→ notifica chat + notifica assignee
review.request_changes ──→ DB task: changes_requested, review: changes_requested ──→ notifica chat + notifica assignee
```

La notificación al assignee usa el campo `assignee` de la task. Si `task.claim` lo setteó incorrectamente (bug #3), la notificación llega al destinatario equivocado.

---

### 7. 💬 Tools de Chat — `chat.py`

**Propósito:** Enviar/recibir mensajes, gestión de threads, routing de @menciones, threads de discusión con turn-taking.

**Tools expuestas:**

| Tool | Implementada | Estado |
|------|-------------|--------|
| `chat.send` | ✅ | Con turn-taking y routing de presencia |
| `chat.read` | ⚠️ | Marca como leído inconsistente (bug #7) |
| `chat.mark_read` | ✅ | |
| `chat.thread_create` | ✅ | |
| `chat.thread_list` | ✅ | |
| `chat.thread_get_pending` | 🐛 | INSTR en JSON frágil (bug #2) + semántica ambigua (bug #13) |
| `chat.thread_resolve` | ✅ | Atómico, lock-winner semantics |

**Resultado: ⚠️ Incompleta**

**Features faltantes:**
- No hay edición/borrado de mensajes
- No hay `chat.thread_get_pending` implementado server-side con búsqueda exacta de participantes (usa INSTR frágil)

**Flujo cruzado:**
```
chat.send ──→ DB + verificación de presencia (@mention routing)
chat.read ──→ output consumido por TUI y agentes
thread_get_pending ──→ output consumido por agentes para saber qué atender
review.approve → send_system_notification → chat (status_update)
task.claim → notify_chat → chat
task.submit_work → notify_chat + send_system_notification → chat
agent.idle → send_system_notification → chat
```

El chat es el sistema nervioso: todas las tools notifican eventos a través de él. El routing de @menciones verifica presencia y advierte si el destinatario está offline.

---

### 8. 👤 Tools de Presencia de Agentes — `agents.py`

**Propósito:** Heartbeat, listar, obtener, cambiar estado, whoami, ping/pong, idle, shutdown.

**Tools expuestas:**

| Tool | Implementada | Estado |
|------|-------------|--------|
| `agent.heartbeat` | ✅ | |
| `agent.list` | ✅ | |
| `agent.get` | ✅ | |
| `agent.set_status` | 🐛 | Sin validación de ownership (bug #4) |
| `agent.whoami` | ✅ | |
| `agent.ping` | ✅ | Con polling y timeout |
| `agent.pong` | ✅ | |
| `agent.idle` | ✅ | Con notificación al partner |
| `agent.shutdown_request` | ✅ | |
| `agent.shutdown_approve` | ✅ | |

**Resultado: ⚠️ Incompleta**

**Features faltantes vs. especificación:**
- `agent.set_status` permite cambiar estado de OTRO agente (bug #4). La spec dice "El propio agente".
- `agent.heartbeat` acepta cualquier string en `status` sin validación contra valores válidos (a diferencia de `agent.set_status` que tiene `enum`).
- La inyección de `_sender_name` en `server.py:239` solo mapea `architect` y `developer`. Cualquier otro rol recibe el `agent_id` crudo como sender name.

**Flujo cruzado:**
```
heartbeat ──→ DB (agents table) ──→ consumido por agent.list, agent.get, presence routing en chat.send
agent.list ──→ output consumido por TUI (status bar) y VSCode extension
whoami ──→ output con skill + tools + restricciones ──→ consumido por agente para auto-configuración
ping/pong ──→ DB (ping_requests) ──→ verificación de conectividad
idle ──→ notifica al partner vía chat ──→ visibilidad en TUI
stale agents ──→ maintenance loop ──→ reassign tasks
```

---

### 9. 🛠️ Tools de Skills — `skills.py`

**Propósito:** Descubrimiento de skills disponibles.

**Tools expuestas:**

| Tool | Implementada | Estado |
|------|-------------|--------|
| `skill.list` | ✅ | Lista skills built-in + custom |
| `skill.get` | ✅ | Devuelve detalle completo |

**Resultado: ✅ Completa**

Cumple su propósito de descubrimiento. `skill.get` acepta un `skill_name` que se resuelve como rol (semánticamente impreciso pero funcionalmente correcto porque nombres de skill = nombres de rol).

---

### 10. ⚙️ Configuración — `config.py`

**Propósito:** Cargar `bridge.json`, resolver roles, proveer skills built-in.

**Responsabilidades:**

| Componente | Estado | Notas |
|-----------|--------|-------|
| Carga multi-path de `bridge.json` | ✅ | 3 rutas en orden de prioridad |
| Resolución de roles (config → default) | ✅ | |
| Skills built-in (architect, developer, default) | ✅ | Cargados desde JSONs + hardcoded fallback |
| Skills custom desde bridge.json | ✅ | |
| `init_default_config` | ✅ | Crea bridge.json por defecto |

**Resultado: ⚠️ Incompleta**

**Features faltantes vs. especificación:**
- **Comando `agent-bridge configure`** — la spec define `configure --set`, `configure --list`, `configure --init`. En `main.py`, el único comando relacionado es `init`, que hace cosas similares pero NO es el `configure` especificado.
- **Validación de esquema de `bridge.json`** — si el JSON está mal formado, el error es genérico. No hay validación estructural.
- **Las restricciones (restrictions) de los skills NUNCA se verifican programáticamente** — existen en el modelo pero solo se retornan en `agent.whoami` para que el agente las cumpla voluntariamente.
- Skills cargados a nivel de módulo (no hot-reload, bug #17).

**Flujo cruzado:**
```
bridge.json ──→ BridgeConfig ──→ get_role_for_agent() ──→ permission layer
                            ──→ get_skill_for_role() ──→ permission layer + skill.list + skill.get
                            ──→ settings ──→ maintenance loop (offline_timeout)
```

---

### 11. ⌨️ CLI — `main.py`

**Propósito:** Punto de entrada para todos los comandos de agent-bridge.

**Comandos:**

| Comando | Implementado | Estado |
|---------|-------------|--------|
| `init` | ✅ | Bootstrap completo (bridge.json + skills + global install) |
| `start` | ✅ | SSE server + TUI (modos headless, ui-only, kanban) |
| `kanban` | ✅ | Atajo para start con kanban mode |
| `reset` | ✅ | Clear database con confirmación |
| `export` | ✅ | Exportar plan a JSON |
| `import` | ✅ | Importar plan desde JSON |
| **`configure`** | ❌ **AUSENTE** | Especificado pero NO implementado |

**Resultado: ⚠️ Incompleta**

**Features faltantes vs. especificación (AGENT-BRIDGE-SPEC.md sección 5):**

| Comando spec | Implementado? |
|-------------|--------------|
| `agent-bridge configure` | ❌ |
| `agent-bridge configure --set agent=X role=Y` | ❌ |
| `agent-bridge configure --list` | ❌ |
| `agent-bridge configure --init` | ❌ (parcialmente en `init` pero no como subcomando de configure) |

El comando `configure` es una entidad separada del `init`. `init` bootstrapa el proyecto entero, mientras que `configure` debería permitir ajustar la configuración de roles sin necesidad de editar `bridge.json` manualmente.

**Flujo cruzado:**
```
init ──→ crea bridge.json + skills ──→ consumido por server.py al iniciar
start ──→ lanza server + TUI
reset ──→ limpia DB
export ──→ produce JSON ──→ consumido por import
```

---

### 12. 🖥️ Chat TUI — `chat_tui.py`

**Propósito:** Interfaz de chat terminal con Textual.

**Capacidades:**

| Feature | Estado |
|---------|--------|
| Conexión MCP vía stdio subprocess | ✅ |
| Visualización de mensajes con timestamps | ✅ |
| @mentions con autosuggest | ✅ |
| Comandos /clear, /help | ✅ |
| Polling de mensajes (5s) | ✅ |
| Polling de estado de agentes (5s) | ✅ |
| Reconexión con exponential backoff (1s→30s) | ✅ |
| Status bar con indicadores de agentes | ✅ |
| Envío de mensajes | ✅ |

**Resultado: ✅ Completa**

Cumple su propósito. La reconexión automática y el exponential backoff están bien implementados. La UI es funcional y clara.

**Problemas menores:** Timeout duro de 30s (bug #16), no hay soporte para crear threads desde la TUI, `_format_time` puede crashear con datetimes naive (bug #12, compartido con `tui_bridge.py`).

---

### 13. 📊 Kanban TUI — `kanban_tui.py` + `kanban_board.py`

**Propósito:** Tablero kanban con lista de tareas, panel de detalle, modales de crear/mover, overlay de chat.

**Capacidades:**

| Feature | Estado |
|---------|--------|
| Lista vertical de tareas con navegación ↑↓ | ✅ |
| Panel de detalle contextual | ✅ |
| Modal crear tarea (con plan selection) | ✅ |
| Modal mover tarea (con transiciones válidas) | ✅ |
| Chat overlay contextual por tarea | ✅ |
| DB Watcher para cambios externos | ✅ |
| Status bar con conteo de tareas | ✅ |
| Indicadores de agentes en header | ✅ |

**Resultado: ⚠️ Incompleta**

**Features faltantes:**
- `action_show_detail` es un placeholder ("📄 Detalle completo — próximo release")
- No hay forma de eliminar tareas desde la TUI
- No hay forma de crear planes desde la TUI (solo tasks)
- `TaskItem` muestra UUID completo (bug #19)

**Problemas:** `move_task` valida fuera de transacción (bug #14), `_format_time` compartido (bug #12), si `_db.initialize()` falla, `_load_tasks()` se llama igual y también falla.

---

### 14. 🔌 Extensión VS Code — `extension.ts`

**Propósito:** Integración con VS Code: tree views, chat webview, terminal manager, status bar.

**Capacidades:**

| Feature | Estado |
|---------|--------|
| Sidecar manager (proceso Python) | ✅ |
| MCP Client via SSE | ✅ |
| Agent tree provider | ✅ |
| Kanban tree provider | ✅ |
| Chat webview | ✅ |
| Terminal manager | ✅ |
| Status bar con estado de conexión | ✅ |
| Quick action menu | ✅ |
| Polling periódico | ✅ |

**Resultado: ⚠️ Incompleta**

**Problemas:**
- `setInterval` sin verificación de conectividad — si el server crashea, el polling continúa indefinidamente con errores silenciosos (las `safeGet*` funciones tragan todas las excepciones)
- `refreshAll` se llama incluso cuando `state !== "connected"` — actualiza los providers con datos vacíos en vez de mostrar error
- No hay reconexión automática al server SSE (a diferencia de la Chat TUI que tiene exponential backoff)
- No hay feedback visual claro cuando la conexión se pierde

---

## 📊 Resumen de Completitud

| # | Funcionalidad | Resultado | Compleción estimada |
|---|--------------|-----------|-------------------|
| 1 | Máquina de Estados | ✅ Completa | 100% |
| 2 | Capa de Base de Datos | ⚠️ Incompleta | 85% (dry-run roto) |
| 3 | Servidor MCP | ⚠️ Incompleta | 90% (maintenance loop frágil) |
| 4 | Tools de Plan | ⚠️ Incompleta | 80% (falta delete, check_readiness) |
| 5 | Tools de Tareas | ⚠️ Incompleta | 85% (falta dependencies, update, delete) |
| 6 | Tools de Revisión | ⚠️ Incompleta | 70% (falta max cycles, escalación, enforce restrictions) |
| 7 | Tools de Chat | ⚠️ Incompleta | 90% (INSTR frágil, mark_read inconsistente) |
| 8 | Tools de Presencia | ⚠️ Incompleta | 90% (set_status sin ownership) |
| 9 | Tools de Skills | ✅ Completa | 100% |
| 10 | Configuración | ⚠️ Incompleta | 70% (falta comando configure, restrictions sin enforce) |
| 11 | CLI | ⚠️ Incompleta | 85% (falta configure subcommand) |
| 12 | Chat TUI | ✅ Completa | 95% |
| 13 | Kanban TUI | ⚠️ Incompleta | 80% (detail placeholder) |
| 14 | Extensión VS Code | ⚠️ Incompleta | 75% (sin reconexión robusta) |

**Funcionalidades completamente funcionales:** 3 de 14 (21%)
**Funcionalidades con carencias:** 11 de 14 (79%)
**Funcionalidades ausentes:** 0 de 14 (0%)

---

## 🔗 Análisis de Flujo Cruzado (Input/Output entre funcionalidades)

### Flujo principal de trabajo

```
CLI: start
  → server.py: create_server
    → database.py: initialize (schema + migrations)          ← DB inicializada
    → server.py: maintenance_loop (background)                ← Loop de mantenimiento

Agente se conecta:
  → tools/agents.py: agent.heartbeat                          ← Presencia registrada
    → database: agents table INSERT OR REPLACE
  → server.py: permission check                               ← Rol resuelto
    → config.py: get_role_for_agent() + get_skill_for_role()
  → tools/skills.py: skill.list / skill.get                   ← Descubrimiento de capacidades
  → tools/agents.py: agent.whoami                             ← Auto-configuración

Arquitecto:
  → tools/planner.py: plan.create ──→ plan_id                ──┐
    → database: plans table INSERT                             │
  → tools/tasks.py: task.create(plan_id) ──→ task_id           │ Flujo completo
    → database: tasks table INSERT                             │
  → tools/tasks.py: task.list / task.get                       │
  → tools/review.py: review.start(task_id)                     │
  → tools/review.py: review.approve / request_changes        ──┘

Desarrollador:
  → tools/tasks.py: task.claim(task_id) ──→ assignee         ──┐
    → database: tasks UPDATE                                    │
  → tools/tasks.py: task.submit_work(task_id, diff)             │ Flujo completo
    → database: tasks UPDATE (status: review)                   │
  → tools/tasks.py: task.get_diff(task_id) ──→ diff           ──┘

Chat/TUI:
  → tools/chat.py: chat.send / chat.read                      ──┐
  → tools/chat.py: thread_create / thread_list / resolve       │ Comunicación
  → tools/agents.py: agent.list / agent.get                    │
  → tools/chat.py: thread_get_pending                         ──┘

UI (ChatTUI):
  → chat_tui.py: MCPClient ──→ stdio subprocess ──→ server    ──┐
  → chat_tui.py: _poll ──→ chat.read + agent.list              │ Loop de UI
  → chat_tui.py: _do_send ──→ chat.send                       ──┘

UI (KanbanTUI):
  → kanban_tui.py: TuiBridge ──→ Database directo             ──┐
  → tui_bridge.py: get_tasks / create_task / move_task         │ Loop de UI
  → chat_overlay.py: send_message / get_messages              ──┘
```

### Puntos de conexión entre funcionalidades

| # | Salida de | Entrada a | Funciona? |
|---|-----------|----------|-----------|
| 1 | `plan.create` → `plan_id` | `task.create(plan_id)` | ✅ |
| 2 | `task.create` → `task_id` | `task.claim(task_id)` | ✅ |
| 3 | `task.claim` → `assignee` | `review.approve` (notificación) | 🐛 Bug #3 (assignee forzable) |
| 4 | `task.submit_work(task_id, diff)` → `status: review` | `review.start(task_id)` | ✅ |
| 5 | `review.start` → `task_id` | `review.approve/request_changes(task_id)` | 🐛 Bug #5 (review duplicado) |
| 6 | `review.approve` → `status: approved` | Plan check_readiness (no implementado) | ❌ No implementado |
| 7 | `review.request_changes` → `status: changes_requested` | `task.submit_work(task_id)` | ✅ |
| 8 | `chat.send` → `message_id` | `chat.read(since=message_id)` | ✅ |
| 9 | `agent.heartbeat` → `agents` table | `agent.list` | ✅ |
| 10 | `agent.list` → agent status | TUI status bar | ✅ |
| 11 | `agent.heartbeat` → role resolution | Permission layer | ✅ |
| 12 | `bridge.json` → config | `server.py: config.get_role_for_agent()` | ✅ |
| 13 | `bridge.json` → skills config | `skill.list` / `skill.get` | ✅ |
| 14 | Export JSON | Import | ✅ |
| 15 | `TuiBridge.create_task(plan_id="")` | DB FK constraint | 🐛 Falla si plan_id="" |
| 16 | `database.py: dry_run` | `with_transaction` | 🐛 Bug #1 (roto) |
| 17 | `server.py: maintenance_loop` | `database.reassign_tasks_from_agent` | 🐛 Bug #6 (irrecuperable) |

### Problemas de integración identificados

1. **Plan → Task**: `plan.create` settea `tasks_ready` directo. `task.create` requiere un `plan_id` válido. El flujo es correcto pero `plan.get` no devuelve las tasks, forzando una consulta adicional.

2. **Task → Review**: `task.submit_work` cambia status a `review`. `review.start` verifica `status == 'review'`. Luego `review.approve`/`request_changes` hacen UPDATE atómico con `WHERE status = 'review'`. El flujo es correcto pero `review.start` puede crear duplicados si se llama múltiples veces.

3. **Review → Task (feedback loop)**: `review.request_changes` → `status: changes_requested` → developer corrige → `task.submit_work` → `status: review`. Este ciclo funciona. PERO no hay contador de ciclos ni escalación automática al humano después de 3 intentos.

4. **Agent → Permission**: El rol se resuelve en dos pasos: (1) `config.get_role_for_agent(agent_id)` desde `bridge.json`, (2) si es `default`, consulta DB por rol desde heartbeat. Esto funciona pero la lógica de resolución está duplicada entre `server.py:_check_permission` y `agents.py:_heartbeat`.

5. **Config → All tools**: `BridgeConfig.load()` se llama UNA VEZ al crear el server (`server.py:212`). Si `bridge.json` cambia mientras el server corre, los cambios no se reflejan hasta reiniciar.

6. **TUI dual connection**: La ChatTUI se conecta vía MCP stdio subprocess al server. La KanbanTUI se conecta directo a la DB (mismo archivo SQLite). Ambas acceden concurrentemente a la misma DB. SQLite WAL maneja la concurrencia, pero la ChatTUI no tiene `DBWatcher` — no detecta cambios hechos por tools vía SSE u otros agentes. Solo detecta cambios en su propio polling.

7. **VSCode Extension → Server SSE**: La extensión depende del sidecar (proceso Python) corriendo. Si el sidecar muere, el polling continúa pero todas las `safeGet*` devuelven vacío. No hay reconexión automática (a diferencia de ChatTUI que sí tiene).

---

## 📋 Resumen de Features Especificadas pero no Implementadas

| Feature | Spec reference | Estado actual |
|---------|---------------|---------------|
| `agent-bridge configure` CLI | §5 Comandos de configuración | ❌ Ausente |
| `configure --set agent=X role=Y` | §5 | ❌ Ausente |
| `configure --list` | §5 | ❌ Ausente |
| Task dependencies (`depends_on`) | §2 Detección de ciclos | ❌ Ausente |
| Plan `check_readiness` | §9 FASE 3 | ❌ Ausente |
| Max 3 review cycles → escalate | §13 Anti-patterns | ❌ Ausente |
| Enforce `cannot_approve_own_work` | §6 Skill restrictions | ❌ Ausente |
| Enforce `max_concurrent_tasks` | §6 Skill restrictions | ❌ Ausente |
| `plan.delete` / `plan.archive` | No especificado pero necesario | ❌ Ausente |
| `task.update` / `task.delete` | No especificado pero necesario | ❌ Ausente |
| Hot-reload de skills | No especificado | ❌ Ausente |
| Migraciones inversas | No especificado | ❌ Ausente |
| **Total features ausentes:** | | **12** |

---

## ✅ Resumen de Features Implementadas

| Feature | Estado |
|---------|--------|
| MCP Server (stdio + SSE) | ✅ |
| Permission layer (rol + skill) | ✅ |
| Plan CRUD (create, get, list, update) | ✅ |
| Task lifecycle (create, claim, submit, get) | ✅ |
| Review lifecycle (start, approve, request_changes, history) | ✅ |
| Chat messaging (send, read, mark_read) | ✅ |
| Thread management (create, list, resolve, get_pending) | ✅ |
| Turn-taking en threads con participantes | ✅ |
| Agent presence (heartbeat, list, get, set_status, whoami) | ✅ |
| Ping/Pong para verificación de conectividad | ✅ |
| Idle + Shutdown protocol | ✅ |
| Skill discovery (list, get) | ✅ |
| Export/Import de planes | ✅ |
| Reset de base de datos | ✅ |
| Chat TUI (Textual) con auto-refresh y reconexión | ✅ |
| Kanban TUI con create/move/chat overlay | ✅ |
| DB Watcher para cambios externos | ✅ |
| Reconexión automática con exponential backoff (ChatTUI) | ✅ |
| Structured logging (request_id, duración, agente) | ✅ |
| Modo headless / ui-only / kanban | ✅ |
| VSCode Extension con tree views, chat, terminal | ✅ |
| **Total features implementadas:** | **21** |

---

## 🎯 Conclusiones

1. **El flujo principal funciona.** El ciclo plan → task → claim → submit → review → approve está implementado y funcional. Los tests de integración lo confirman.

2. **Hay 12 features especificadas que no están implementadas.** La más significativa es el comando `agent-bridge configure` completo con sus flags `--set`, `--list`, `--init`. También faltan las dependencias entre tareas, el enforcement de restricciones de skills, y la escalación automática al humano después de N ciclos de revisión.

3. **Hay 2 bugs críticos que rompen funcionalidad existente.** El modo `--dry-run` está completamente roto, y la búsqueda con `INSTR` en JSON arrays da falsos positivos.

4. **El flujo de datos entre funcionalidades es mayormente correcto**, con 14 de 17 conexiones funcionando bien. Los 3 problemas están en: (a) `task.claim` permite datos incorrectos que se propagan a notificaciones, (b) `review.start` puede duplicar revisiones, (c) el maintenance loop no se recupera si crashea.

5. **No hay enforcement de restricciones declaradas en los skills.** `max_concurrent_reviews`, `cannot_approve_own_work`, y `max_concurrent_tasks` existen en los modelos pero nunca se verifican programáticamente. El sistema confía en que los agentes las respeten voluntariamente.

6. **La aplicación tiene 21 features implementadas vs 12 ausentes**, lo que da una completitud general estimada del **64%** respecto a la especificación.

---

*Informe generado el 2026-06-06 mediante auditoría manual del código fuente.*

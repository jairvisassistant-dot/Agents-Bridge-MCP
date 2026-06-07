# Agents-Bridge-MCP — Kanban Hub para el Project Lead

> **Documento de referencia, investigación e implementación**
> Versión: 1.0 — 2026-05-29

---

## Índice

- [Visión General](#visión-general)
- [Arquitectura del Kanban Hub](#arquitectura-del-kanban-hub)
- [Módulos y Componentes](#módulos-y-componentes)
- [Referencias e Investigación](#referencias-e-investigación)
- [Validación de Patrones](#validación-de-patrones)
- [Progreso de Implementación (5 Fases)](#progreso-de-implementación)
- [Guía de Uso](#guía-de-uso)
- [Arquitectura de la DB](#arquitectura-de-la-db)

---

## Visión General

El Kanban Hub es el centro de comando para el **project lead** de Agents-Bridge-MCP.
No es para los agentes — es para que el humano gestione el proyecto, cree tareas, 
las mueva entre estados, y se comunique con los agentes.

### Stack

| Capa | Tecnología |
|------|-----------|
| UI Framework | Textual 8.2.6 (Python TUI) |
| DB | SQLite3 + WAL + RLock + BEGIN IMMEDIATE |
| Transporte MCP | SSE (servidor externo para agentes) |
| State Machine | Transiciones validadas (plan/task/review/thread) |
| Tests | pytest + asyncio |
| Linter/Formatter | ruff (line-length=120, target-version=py312) |

### Flujo de operación

```
┌──────────────────────────────────────────────────────────────────┐
│                          Terminal 1                              │
│  agent-bridge kanban                                             │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Kanban Hub (TUI)  ←→  SQLite DB  ←→  MCP Server (SSE)  │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│                          Terminal 2                        │
│  Claude Code (Arquitecto) ──vía MCP──→  SQLite DB                │
│                                                                  │
│                          Terminal 3                              │
│  OpenCode (Desarrollador) ──vía MCP──→  SQLite DB                │
└──────────────────────────────────────────────────────────────────┘
```

Los agentes escriben a la misma DB vía MCP. El DBWatcher detecta los cambios
y refresca el kanban automáticamente.

---

## Arquitectura del Kanban Hub

### Layout actual

```
┌──────────────────────────────────────────────────────────┐
│ 🔷 Agents-Bridge-MCP  │  🟢 0/0 agentes  │  💬 0 msgs  │
├──────────────────────────────────────────────────────────┤
│ 📊 0 tareas · 0 pendientes · 0 en progreso · 0 revisión │
├──────────────────────┬───────────────────────────────────┤
│ TaskList             │  TaskDetail                      │
│ (↑↓ navegación)      │  (contextual a selección)        │
│                      │                                   │
│ ● #1 Titulo tarea    │  Título completo                  │
│    📋 Pendiente      │  Descripción                      │
│    Asig: Arq         │  Estado, Asignado, Plan, Fechas   │
│                      │                                   │
├──────────────────────┴───────────────────────────────────┤
│ [N] Nueva  [M] Mover  [D] Detalle  [K] Chat  [Q] Salir  │
└──────────────────────────────────────────────────────────┘
```

### Árbol de módulos

```
src/agent_bridge/ui/
├── __init__.py              # Exports públicos
├── kanban_tui.py            # App principal (KanbanTUI)
├── kanban_board.py          # Widgets: TaskItem, TaskList, TaskDetail, KanbanBoard
├── chat_overlay.py          # ChatOverlay (ModalScreen contextual)
├── create_task_modal.py     # CreateTaskModal (formulario nueva tarea)
├── move_task_modal.py       # MoveTaskModal (selector de estado)
├── tui_bridge.py            # TuiBridge (wrappeo async de Database)
├── db_watcher.py            # DBWatcher (polling PRAGMA data_version)
├── chat_tui.py              # Legacy — ChatTUI original (sin kanban)
```

### Mapa de dependencias

```
KanbanTUI (App)
├── Database (state/database.py)
├── TuiBridge → Database (wrappeo async)
├── DBWatcher → Database (polling data_version)
├── KanbanBoard
│   ├── TaskList → TaskItem (navegación ↑↓)
│   └── TaskDetail (panel contextual)
├── CreateTaskModal → TuiBridge (formulario)
├── MoveTaskModal → TuiBridge + state_machine (transiciones)
└── ChatOverlay → TuiBridge (mensajería)
```

### Flujo de datos

```
1. App arranca → Database.initialize() (crea tablas si no existen)
2. on_mount():
   ├── _load_tasks() → TuiBridge.get_tasks() → KanbanBoard.tasks = tasks
   ├── _update_header_bar() → TuiBridge.get_connection_status() + get_unread_message_count()
   ├── _update_summary_bar() → TuiBridge.get_task_counts()
   └── set_interval(1.5s, DBWatcher.poll) ← detecta cambios externos
   
3. Usuario presiona N → CreateTaskModal → TuiBridge.create_task() → _load_tasks()
4. Usuario presiona M → MoveTaskModal → TuiBridge.move_task() → _load_tasks()
5. Usuario presiona K → ChatOverlay (contextual si hay tarea seleccionada)
6. DBWatcher detecta cambio → _on_db_change() → _load_tasks() + update bars
```

### Decisiones de arquitectura

| Decisión | Alternativa descartada | Motivo |
|----------|----------------------|--------|
| ModalScreen para chat | Side panel lateral | ModalScreen no compite por ancho, bloquea keybindings automáticamente |
| In-process (TuiBridge) | MCP subprocess | DB ya es thread-safe, eliminamos latencia y reconexión |
| Layout vertical (lista + detalle) | Columnas horizontales | 5 columnas en terminal no escalan — muy angostas |
| PRAGMA data_version polling | watchfiles/inotify/honker | ~1μs por llamada, sin dependencias externas |
| Sin Backend Strategy Pattern | SQLite/Jira/Claude backends | Solo hay SQLite, over-engineering agregarlo ahora |

---

## Módulos y Componentes

### `kanban_tui.py` — App principal

Punto de entrada. Compone header, summary bar, kanban board, y footer.
Maneja todos los bindings de teclado y orquesta las acciones.

**Bindings:**
| Tecla | Acción | Método | Estado |
|-------|--------|--------|--------|
| ↑ | Navegar arriba | `action_cursor_up` | ✅ |
| ↓ | Navegar abajo | `action_cursor_down` | ✅ |
| N | Crear tarea | `action_new_task` → `CreateTaskModal` | ✅ |
| M | Mover estado | `action_move_task` → `MoveTaskModal` | ✅ |
| D | Ver detalle | `action_show_detail` | ✅ (ya está en panel derecho) |
| K | Chat | `action_toggle_chat` → `ChatOverlay` | ✅ |
| R | Refrescar | `action_refresh` | ✅ |
| Q | Salir | `action_quit` | ✅ |

### `kanban_board.py` — Widgets del tablero

| Clase | Hereda | Propósito |
|-------|--------|-----------|
| `TaskItem` | `Static` | Una fila de tarea: icono + #id + título + badge + asignado |
| `TaskList` | `VerticalScroll` | Lista scrolleable con `selected_index` reactivo, navegación y callback |
| `TaskDetail` | `Static` | Panel derecho con detalle completo de la tarea seleccionada |
| `KanbanBoard` | `Static` | Layout Horizontal con TaskList izq + TaskDetail der |

### `chat_overlay.py` — Chat contextual

`ChatOverlay(ModalScreen)`: overlay modal para comunicación con agentes.

- **Modo general**: sin tarea seleccionada → muestra todos los mensajes
- **Modo contextual**: con tarea seleccionada → filtra por `thread_id = task.id`
- Placeholder del input cambia según contexto (sugiere @asignado si hay tarea)
- Header cambia según contexto (título de tarea vs "Chat general")
- Polling cada 5s para mensajes nuevos

### `create_task_modal.py` — Formulario de creación

`CreateTaskModal(ModalScreen[str | None])`: modal con campos:
- Título (requerido, validado)
- Descripción (TextArea opcional)
- Plan (selector de planes existentes, disabled si no hay)

Retorna el `task_id` string al crear, `None` al cancelar.

### `move_task_modal.py` — Selector de estado

`MoveTaskModal(ModalScreen[str | None])`: modal con:
- Nombre y estado actual de la tarea
- RadioSet con transiciones válidas (desde `state_machine.TASK_TRANSITIONS`)
- Botón Mover (valida contra state machine + concurrent-safe UPDATE)
- Manejo de estado terminal (approved → no se puede mover)

### `tui_bridge.py` — Bridge in-process

Wrappeo async de `Database` con métodos específicos para la UI.

| Método | SQL | Propósito |
|--------|-----|-----------|
| `get_tasks(status)` | `SELECT * FROM tasks [WHERE status=?]` | Listar tareas |
| `get_task_counts()` | `SELECT status, COUNT(*) ... GROUP BY status` | Contadores |
| `get_plans()` | `SELECT * FROM plans ORDER BY created_at DESC` | Selector de plan |
| `get_agents()` | `SELECT * FROM agents` | Estado de agentes |
| `get_agent_statuses()` | `SELECT agent_id, status ... WHERE status != 'offline'` | Indicadores header |
| `get_connection_status()` | `SELECT COUNT(*) ...` | Texto de conexión |
| `create_task(title, desc, plan_id)` | `INSERT INTO tasks ...` | Nueva tarea |
| `move_task(id, new_status)` | `UPDATE tasks SET status=... WHERE id=? AND status=?` | Cambiar estado |
| `send_message(text, sender, target, thread_id)` | `INSERT INTO messages ...` | Enviar mensaje |
| `get_messages(since, limit)` | `SELECT rowid, * FROM messages ...` | Leer mensajes |
| `get_messages_for_task(task_id, limit)` | `SELECT ... WHERE thread_id=?` | Mensajes contextuales |
| `get_unread_message_count()` | `SELECT COUNT(*) ... WHERE read=0 AND target IS NULL AND thread_id IS NULL` | Badge de mensajes |

### `db_watcher.py` — Detector de cambios externos

POLL `PRAGMA data_version` cada 1.5s. Cuando el número cambia:

1. Espera 50ms (mitigación WAL: evitar falsos positivos por checkpoint)
2. Vuelve a leer `data_version`
3. Si persiste el cambio, llama al callback `on_change(new_version)`
4. El callback en KanbanTUI refresca tareas y contadores

---

## Referencias e Investigación

### Repositorios analizados

#### kagan-sh/kagan — `v0.19.0-beta.38`
**URL:** https://github.com/kagan-sh/kagan  
**Stack:** Python 3.12+ · Textual 7.x · SQLAlchemy · SQLModel · ACP · MCP SDK

Patrones relevantes:
- **OrchestratorOverlay**: chat contextual por tarea en overlay modal (no side panel)
- **DBWatcher**: polling SQLite para cambios externos
- **Optimistic updates**: model_copy() → render → persist → revert
- **Screen-based routing**: `push_screen()` / `switch_screen()` para navegación
- **TaskScreen**: detalle de tarea con historial de sesión del agente

#### Zaloog/kanban-tui — `v0.21.1`
**URL:** https://github.com/Zaloog/kanban-tui  
**Stack:** Python 3.11+ · Textual 8.x · Pydantic · Click

Patrones relevantes:
- **Backend Strategy Pattern**: interfaz abstracta con implementaciones SQLite/Jira/Claude
- **Modal-driven CRUD**: cada operación en su propio modal screen
- **Reactive binding**: `reactive[list[Task]]` con watchers automáticos
- **Drag & Drop**: movimiento de cards entre columnas vía Textual Drag

### Comparativa

| Aspecto | kagan | kanban-tui |
|---------|-------|------------|
| Complejidad | Alta (monorepo full) | Media (solo TUI) |
| Chat integrado | Sí — OrchestratorOverlay | No |
| Drag & Drop | No (teclado) | Sí (click) |
| Auto-refresh | DBWatcher | Timer |
| Múltiples backends | Solo SQLite | SQLite, Jira, Claude |
| Tests | pytest + Playwright | pytest |

---

## Validación de Patrones

Los 5 patrones clave se investigaron contra el código real de Agents-Bridge-MCP
antes de implementar. Cada uno se verificó por compatibilidad, riesgos, y costo.

| Patrón | Decisión | Riesgo | Cambio respecto al doc original |
|--------|----------|--------|--------------------------------|
| Chat como ModalScreen overlay | ✅ Implementado | Bajo | ❌ Original decía "side panel derecho" |
| DBWatcher PRAGMA data_version | ✅ Implementado | Bajo (mitigación 50ms) | ✅ Sin cambios |
| Optimistic updates | ✅ Implementado (TuiBridge) | Medio (flash visual en fallo) | ✅ Sin cambios |
| TUI in-process (TuiBridge) | ✅ Implementado | Bajo (DB thread-safe) | ❌ Original no especificaba |
| Backend Strategy Pattern | ❌ No implementar | Cero | ❌ Original recomendaba implementar |

Detalle completo de cada patrón en la sección [Validación de Patrones detallada](#validación-de-patrones-detallada).

---

## Progreso de Implementación

### Fase 1 — Layout vertical + lista navegable ✅

**Objetivo:** Reemplazar columnas horizontales por layout vertical usable.

| Archivo | Acción |
|---------|--------|
| `kanban_board.py` | **REESCRITO** — eliminados TaskCard, KanbanColumn. Nuevos: TaskItem, TaskList (VerticalScroll con ↑↓), TaskDetail, KanbanBoard (Horizontal split) |
| `kanban_tui.py` | **MODIFICADO** — header bar, summary bar, footer con bindings, placeholders para acciones |

**Bindings resultantes:**
| Tecla | Acción | Estado |
|-------|--------|--------|
| ↑ ↓ | Navegar | ✅ |
| N | Nueva | ⏳ Placeholder |
| M | Mover | ⏳ Placeholder |
| D | Detalle | ✅ (panel ya muestra) |
| K | Chat | ⏳ Placeholder |
| Q | Salir | ✅ |

**Verificación:** ruff check ✅, ruff format ✅, imports OK ✅

---

### Fase 2 — Modal para crear tareas ✅

**Objetivo:** Poder crear tareas desde el kanban con un formulario.

| Archivo | Acción |
|---------|--------|
| `create_task_modal.py` | **NUEVO** — ModalScreen con título (req), descripción (opcional), selector de plan |
| `tui_bridge.py` | **MODIFICADO** — +`create_task(title, description, plan_id)` |
| `kanban_tui.py` | **MODIFICADO** — +`action_new_task`, `_after_task_created`, `_update_summary` |
| `__init__.py` | **MODIFICADO** — export |

**Tests:** 3 nuevos (creación, validación, defaults) — 19 total

---

### Fase 3 — Mover tarea de estado ✅

**Objetivo:** Cambiar estado de tareas con validación de state machine.

| Archivo | Acción |
|---------|--------|
| `move_task_modal.py` | **NUEVO** — ModalScreen con RadioSet de transiciones válidas + detección de estado terminal |
| `tui_bridge.py` | **MODIFICADO** — +`move_task(task_id, new_status)` con validación y UPDATE concurrent-safe |
| `kanban_board.py` | **MODIFICADO** — +`selected_task` property en KanbanBoard |
| `kanban_tui.py` | **MODIFICADO** — +`action_move_task`, `_after_task_moved` |
| `__init__.py` | **MODIFICADO** — export |

**Bugs corregidos post-release:**
1. `self.container()` → `Container()` — no existe en Textual 8.x (afectaba CreateTaskModal y MoveTaskModal)
2. `KanbanBoard.selected_task` faltaba — `action_move_task` no podía acceder a la tarea seleccionada

**Tests:** 6 nuevos (válida, inválida, terminal, inexistente, concurrente, walkthrough) — 25 total

---

### Fase 4 — Chat overlay contextual ✅

**Objetivo:** Comunicación con agentes, contextual a la tarea seleccionada.

| Archivo | Acción |
|---------|--------|
| `chat_overlay.py` | **MODIFICADO** — constructor acepta `task_context`, header contextual, fetch filtrado por `thread_id`, placeholder sugiere @asignado. Fix `self.container()` |
| `tui_bridge.py` | **MODIFICADO** — +`get_messages_for_task(task_id, limit)` |
| `kanban_tui.py` | **MODIFICADO** — `action_toggle_chat` pasa contexto de tarea, fix `call_from_thread` → `call_later` |

**Comportamiento:**
- `K` sin tarea seleccionada → chat general (todos los mensajes)
- `K` con tarea seleccionada → chat contextual (mensajes filtrados por `thread_id = task.id`, header muestra título + estado, placeholder sugiere @asignado)
- `K` repetido → no-op (evita doble overlay)
- `Escape` → cierra overlay

**Tests:** 13 nuevos (contextual header, placeholder, send, fetch, headless) — 38 total

---

### Fase 5 — Tests y pulido ✅

**Objetivo:** Cobertura de edge cases, contadores reales, UX pulida.

| Archivo | Acción |
|---------|--------|
| `tui_bridge.py` | **MODIFICADO** — +`get_unread_message_count()` |
| `kanban_tui.py` | **MODIFICADO** — header usa contador real de mensajes no leídos; `_after_task_created`/`_after_task_moved` usan `notify()` en vez de pisar summary bar |
| `kanban_board.py` | **MODIFICADO** — empty state informativo ("Presioná N para crear") |
| `test_kanban_tui.py` | **MODIFICADO** — +8 tests edge cases |

**Tests:** 8 nuevos (unread count, empty state, notify, thread_id en DB) — 46 total

---

### Resumen de fases

| Fase | Archivos nuevos | Archivos modificados | Tests nuevos | Tests totales |
|------|----------------|---------------------|-------------|--------------|
| 1 — Layout vertical | 0 | 2 | 0 | 16 |
| 2 — Crear tarea | 1 | 3 | 3 | 19 |
| 3 — Mover estado | 1 | 4 | 6 | 25 |
| 4 — Chat contextual | 0 | 3 | 13 | 38 |
| 5 — Tests y pulido | 0 | 3 | 8 | 46 |
| **Total** | **2** | **15** | **30** | **46** |

---

## Guía de Uso

### Lanzamiento

```bash
# Kanban + servidor SSE (stack completo)
agent-bridge kanban

# Solo kanban (sin servidor)
agent-bridge start --kanban --ui-only

# Solo servidor (para que los agentes se conecten)
agent-bridge start --headless
```

### Atajos de teclado

| Tecla | Acción | Notas |
|-------|--------|-------|
| `↑` `↓` | Navegar entre tareas | Scroll automático |
| `N` | Crear nueva tarea | Modal con formulario |
| `M` | Mover tarea de estado | Modal con transiciones válidas |
| `D` | Ver detalle | Panel derecho contextual |
| `K` | Abrir chat | Contextual si hay tarea seleccionada |
| `R` | Refrescar | Recarga tareas y contadores |
| `Q` | Salir | Cierra la app |
| `Escape` | Cerrar modal/overlay | Chat, crear, mover |

### Flujo de trabajo típico

1. **Crear plan** → los agentes crean planes vía MCP
2. **Crear tareas** → `N` desde el kanban (o agentes vía MCP)
3. **Asignar** → los agentes se asignan tareas con `task.claim`
4. **Monitorear** → el kanban se refresca automáticamente via DBWatcher
5. **Mover** → `M` para cambiar estado cuando sea necesario
6. **Chatear** → `K` para comunicarse con agentes sobre una tarea específica

---

## Arquitectura de la DB

### Tablas relevantes para el kanban

```sql
-- Tareas (fuente principal del kanban)
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|in_progress|review|approved|changes_requested
    assignee TEXT,
    submission_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Mensajes (usados por el chat)
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT,          -- task_id cuando es chat contextual
    sender TEXT NOT NULL,
    target TEXT,
    text TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'chat',
    priority TEXT NOT NULL DEFAULT 'normal',
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Planes (agrupación de tareas)
CREATE TABLE plans (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idle',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Agentes (presencia y estado)
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'offline',
    last_seen TEXT,
    connected_since TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
```

### State machine (transiciones de tarea)

```
pending ───→ in_progress ───→ review ───→ approved (terminal)
                                        └──→ changes_requested ───→ review
```

### Concurrencia

La DB usa `threading.RLock` + `BEGIN IMMEDIATE` para writes. Esto significa:
- Múltiples lectores concurrentes (sin lock)
- Escritores serializados (un UPDATE por vez)
- El TUI y el MCP server externo pueden escribir simultáneamente sin corrupción

---

## Validación de Patrones detallada

### 1. Chat Panel → ModalScreen overlay

| Aspecto | Decisión |
|---------|----------|
| **Qué** | `ModalScreen` de Textual con fondo translúcido. NO widget lateral permanente. |
| **Por qué** | ModalScreen bloquea keybindings automáticamente, tiene ciclo de vida limpio. |
| **Fuente** | kagan — `OrchestratorOverlay(task_id=...)` como overlay modal. |
| **Riesgo** | Bajo. |
| **Cambio respecto al doc original** | ❌ El doc original decía "side panel derecho". |

### 2. DB Watcher → PRAGMA data_version polling

| Aspecto | Decisión |
|---------|----------|
| **Qué** | Poll `PRAGMA data_version` cada 1.5s. |
| **Por qué** | Costo ~1μs/llamada. Sin dependencias. |
| **Mitigación WAL** | Double-check con 50ms de delay. |
| **Riesgo** | Bajo. |
| **Cambio** | ✅ Confirmado. |

### 3. Optimistic Updates

| Aspecto | Decisión |
|---------|----------|
| **Qué** | `model_copy()` → render → persist → revert on fail. |
| **Anti-patrón** | NO mutar el modelo directamente (`task.status = X`). |
| **Riesgo** | Medio (flash visual si falla persistencia). Aceptable. |
| **Cambio** | ✅ Confirmado. |

### 4. MCP + TUI Integration → in-process

| Aspecto | Decisión |
|---------|----------|
| **Qué** | TuiBridge importa Database directamente. NO subprocess MCP. |
| **Por qué** | DB ya es thread-safe (RLock + BEGIN IMMEDIATE). |
| **Beneficios** | Sin latencia, sin reconexión, sin serialización JSON. |
| **Riesgo** | Bajo. |
| **Cambio** | ❌ Legacy ChatTUI usaba subprocess stdio. Nuevo TUI es in-process. |

### 5. Backend Strategy Pattern

| Aspecto | Decisión |
|---------|----------|
| **Qué** | NO implementar. |
| **Por qué** | Solo SQLite como backend. |
| **Cuándo reconsiderar** | Si hay un segundo backend real. |
| **Riesgo** | Cero. |
| **Cambio** | ❌ Original recomendaba implementar. |

---

## Tests

**46 tests** en `tests/test_kanban_tui.py`, todos pasando.

| Suite | Tests | Cubre |
|-------|-------|-------|
| `TestTuiBridge` | 14 | CRUD tareas, agentes, mensajes, format_time |
| `TestTuiBridgeMessages` | 3 | get_messages_for_task (filtro, orden, vacío) |
| `TestDBWatcher` | 5 | detección de cambios, doble-check, force_refresh |
| `TestChatOverlayContextual` | 7 | header contextual, placeholder, send con thread_id, fetch filtrado |
| `TestKanbanTUIHeadless` | 3 | chat general, double-K no-op, escape cierra overlay |
| `TestKanbanTUIEdgeCases` | 8 | unread count, empty state, notify, thread_id persistido |
| **Total** | **46** | |

```bash
# Ejecutar todos los tests del kanban
uv run pytest tests/test_kanban_tui.py -v

# Suite completa del proyecto
uv run pytest
```

---

## Lecciones Aprendidas

### Técnicas

1. **Textual 8.x vs 1.x**: `self.container()` no existe en Textual 8.x. Usar `Container()` de `textual.containers`.
2. **`call_from_thread` es para threads**: en el main thread, usar `call_later` para programar corrutinas.
3. **Layout horizontal de columnas no escala en terminal**: 5 columnas compitiendo por ancho es ilegible. Layout vertical (lista + detalle) funciona.
4. **PRAGMA data_version y WAL mode**: en WAL mode, `data_version` puede cambiar durante checkpoints. Siempre hacer double-check con 50ms.
5. **Validación de state machine en writes concurrentes**: el UPDATE condicional (`WHERE id=? AND status=?`) previene race conditions aunque dos procesos muevan la misma tarea.

### De proceso

1. **Siempre verificar la versión de Textual instalada** antes de escribir código TUI. Textual 8.x tiene breaking changes respecto a 1.x/7.x.
2. **Probar con headless test** (`app.run_test()`) antes de decirle al usuario que pruebe. Atrapa errores de compose y binding.
3. **No asumir que un layout funciona** — lo que se ve bien en ASCII puede ser un desastre en terminal real.
4. **El kanban es para el humano, no para los agentes**. El project lead necesita crear, mover, y chatear — no solo mirar.

---

## Estado final del proyecto

```
┌──────────────────────────────────────────────────────────┐
│ 🔷 Agents-Bridge-MCP  │  🟢 0/0 agentes  │  💬 0 msgs  │
├──────────────────────────────────────────────────────────┤
│ 📊 0 tareas · 0 pendientes · 0 en progreso · 0 revisión │
├──────────────────────┬───────────────────────────────────┤
│ TaskList             │  TaskDetail                      │
│ 📋 No hay tareas     │  (seleccioná una tarea)          │
│ todavía              │                                   │
│ Presioná N para      │                                   │
│ crear                │                                   │
├──────────────────────┴───────────────────────────────────┤
│ [N] Nueva  [M] Mover  [D] Detalle  [K] Chat  [Q] Salir  │
└──────────────────────────────────────────────────────────┘
```

| Métrica | Valor |
|---------|-------|
| Módulos UI | 7 (+1 legacy) |
| Líneas de código | ~2100 |
| Tests | 46/46 pasan |
| Bindings funcionales | ↑↓ N M D K R Q |
| Bugs conocidos | 0 |
| Ruff | 0 errors, 0 warnings |
| Dependencias nuevas | 0 (usa Textual ya instalado) |

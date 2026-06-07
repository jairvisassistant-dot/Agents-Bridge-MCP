# Plan de Mejoras — Kanban TUI v2

> **Documento de ejecución.** Basado en auditoría del código (2026-06-07) y la directiva del supervisor:
> el chat_tui.py es la base, chat_overlay.py se integra en él, y el kanban incorpora el chat como panel persistente.

---

## Estado actual

| Componente | Archivo | Líneas | Rol |
|---|---|---|---|
| Chat app standalone | `ui/chat_tui.py` | 529 | App completa con MCPClient, status bar, agent indicators, @mentions, F1 help |
| Chat overlay modal | `ui/chat_overlay.py` | 391 | ModalScreen contextual a tarea, usa TuiBridge (DB directa) |
| Kanban app | `ui/kanban_tui.py` | 303 | App principal del supervisor, layout vertical |
| Bridge DB | `ui/tui_bridge.py` | ~220 | Wrapper async de Database para operaciones de UI |
| DB Watcher | `ui/db_watcher.py` | ~80 | Polling PRAGMA data_version cada 1.5s |

### Problemas detectados

1. **Dos chats que compiten** — `chat_tui.py` (standalone) y `chat_overlay.py` (modal en kanban). Código duplicado (~70% de superposición).
2. **Chat modal tapa el kanban** — `K` abre overlay que oculta el tablero. El supervisor no puede ver tareas mientras chatea.
3. **D (Detalle) es placeholder** — muestra notificación "próximo release" en vez de detalle real.
4. **No hay Editar/Eliminar/Asignar** desde el kanban — existen MCP tools (`task.update`, `task.delete`, `task.claim`) pero no hay bindings en la TUI.
5. **chat_tui.py usa MCPClient** (subprocess) mientras que el kanban usa TuiBridge (DB directa). Dos mecanismos de conexión distintos.

---

## Arquitectura objetivo

```
KanbanTUI (App)
├── Header bar (conexión + agentes + mensajes no leídos)
├── Summary bar (conteo de tareas por estado)
├── KanbanBoard (Horizontal split)
│   ├── TaskList (↑↓ navegación)
│   └── TaskDetail (panel contextual)
├── ChatPanel (NUEVO — persistente, no modal)  ← chat_tui.py + features del overlay
│   ├── Status bar (estado de conexión + agentes 🟢🟡⚫)
│   ├── Messages (RichLog con @menciones, timestamps)
│   ├── Help panel (F1, toggle)
│   └── Input row (Input + Send, autocomplete, /commands)
└── Footer (bindings)
```

### Flujo de datos del ChatPanel

```
ChatPanel
  └── TuiBridge (DB directa, igual que el kanban)
       ├── get_messages(since, thread_id?)
       ├── get_messages_for_task(task_id)  ← contextual
       ├── send_message(text, sender, target, thread_id?)
       ├── get_agents() → agent_status
       └── get_unread_message_count()

Contextual: cuando hay tarea seleccionada en TaskList
  → thread_id = task.id
  → placeholder sugiere @asignado
  → header dice "💬 Tarea: {titulo}"

General: sin tarea seleccionada
  → todos los mensajes
  → placeholder genérico
```

---

## Fases de ejecución

### Fase 1 — ChatPanel: widget de chat persistente

**Objetivo**: Crear un widget `ChatPanel` que unifique `chat_tui.py` (features) + `chat_overlay.py` (contexto de tarea), usable como panel en el kanban.

**Archivos**: 
- `src/agent_bridge/ui/chat_panel.py` — NUEVO
- `src/agent_bridge/ui/__init__.py` — export

**Qué incluye** (desde chat_tui.py):
- Status bar con estado de conexión + agentes online (🟢🟡⚫)
- RichLog de mensajes con timestamps, @menciones formateadas
- Input con AgentSuggester (@arquitecto, @desarrollador, /clear, /help)
- Botón Send + Enter para enviar
- /clear command, /help command
- F1 help panel toggle (idéntico al existente)
- Polling cada 5s para mensajes nuevos
- `_format_time()` con timezone local

**Qué se agrega** (desde chat_overlay.py):
- `task_context: dict | None` — modo contextual cuando hay tarea seleccionada
- Header contextual: "💬 Tarea: {titulo} | Estado: {status}"
- Placeholder contextual: "Escribí tu mensaje… (@arquitecto, @Dev:nombre, /help)" 
- Filtro de mensajes por `thread_id = task.id` en modo contextual
- `_rendered_ids: set[int]` para evitar duplicados en modo contextual (no `since`)

**Qué cambia** vs chat_tui.py:
- NO es un `App` — es un `Widget` (componible, no standalone)
- Usa `TuiBridge` en vez de `MCPClient` (DB directa, consistente con el kanban)
- NO tiene `on_mount` que conecte — recibe el bridge ya inicializado
- NO spawnea subprocess — la DB ya está abierta
- `agent_status: reactive[dict]` se mantiene
- `_poll()` se mantiene pero usa `TuiBridge.get_messages()` / `TuiBridge.get_agents()`

**Diseño del widget**:

```python
class ChatPanel(Widget):
    """Panel de chat persistente para el KanbanTUI.
    
    Modo general: muestra todos los mensajes (polling por since)
    Modo contextual: filtra por thread_id = task.id
    
    Atajos: Ctrl+L = limpiar, F1 = ayuda
    """

    agent_status: reactive[dict[str, str]] = reactive({})

    def __init__(self, bridge: TuiBridge, task_context: dict | None = None) -> None:
        ...
```

**CSS del panel** (altura fija ~30-40% del terminal):

```css
ChatPanel {
    height: 12;         /* ~30% de terminal estándar */
    dock: bottom;
    border: solid $accent;
}

#chat-status {
    height: 1;
    background: $surface;
}

#chat-log {
    height: 1fr;
}

#chat-input-row {
    height: 3;
    dock: bottom;
}
```

**Criterios de aceptación**:
- [ ] `ChatPanel` existe como Widget, no como App ni ModalScreen
- [ ] Muestra mensajes con polling cada 5s
- [ ] Status bar muestra agentes online (🟢🟡⚫)
- [ ] Envía mensajes con @mention routing
- [ ] AgentSuggester completa @mentions y /commands
- [ ] /clear, /help, F1 help panel funcionan
- [ ] Modo contextual: filtro por thread_id = task.id
- [ ] Modo contextual: placeholder sugiere @asignado
- [ ] Sin duplicados: usa `_rendered_ids` en modo contextual, `since` en modo general
- [ ] Tests pasan

---

### Fase 2 — Integrar ChatPanel en KanbanTUI

**Objetivo**: Reemplazar el chat modal overlay por el ChatPanel persistente. El kanban ahora tiene dos zonas: tablero arriba, chat abajo.

**Archivos**:
- `src/agent_bridge/ui/kanban_tui.py` — MODIFICAR
- `src/agent_bridge/ui/chat_overlay.py` — ELIMINAR (opcional, mantener para compatibilidad)

**Cambios en kanban_tui.py**:

1. **Layout**: cambia de vertical simple a dos zonas:
   ```python
   def compose(self) -> ComposeResult:
       yield Static(id="header-bar")
       yield Static(id="summary-bar")
       yield KanbanBoard()      # 1fr (ocupa espacio restante)
       yield ChatPanel(...)     # height: 12 (fijo)
       yield Footer()
   ```

2. **Binding K**: ya no push_screen overlay, ahora:
   - Si el chat está visible → toggle focus entre task list y chat input
   - Si el chat está oculto → show chat panel y focus input

   Alternativa simple: el chat está SIEMPRE visible. K solo mueve el foco al input.

3. **Contextualidad reactiva**: el ChatPanel recibe el task_context automáticamente cuando cambia la selección:
   ```python
   # En KanbanBoard._on_task_selected:
   def _on_task_selected(self, task):
       # Actualiza TaskDetail (ya existe)
       detail.task = task
       # Actualiza ChatPanel context
       chat_panel = self.app.query_one(ChatPanel)
       chat_panel.task_context = task  # reactive → se actualiza solo
   ```

4. **Remover**: `_chat_open`, `action_toggle_chat`, `_on_chat_closed`, `_after_chat_closed`, `ChatOverlay` import.

5. **Nuevo binding** opcional: `K` → focus chat input, `Escape` → focus task list.

**Criterios de aceptación**:
- [ ] ChatPanel visible siempre en la parte inferior
- [ ] K enfoca el input del chat (o toggle focus)
- [ ] Escape vuelve el foco a TaskList
- [ ] Al seleccionar tarea, chat se contextualiza automáticamente
- [ ] Sin tarea seleccionada, chat muestra todos los mensajes
- [ ] Header y summary siguen funcionando
- [ ] DBWatcher sigue funcionando
- [ ] 46 tests de kanban existentes siguen pasando (o se actualizan)

---

### Fase 3 — Kanban CRUD completo

**Objetivo**: Agregar editar, eliminar y asignar tareas desde el kanban.

#### 3.1 Editar tarea (E)

**Archivos**:
- `src/agent_bridge/ui/kanban_tui.py` — +binding `E` + `action_edit_task`
- `src/agent_bridge/ui/edit_task_modal.py` — NUEVO (similar a CreateTaskModal)
- `src/agent_bridge/ui/tui_bridge.py` — +`update_task(task_id, title, description)`
- `src/agent_bridge/ui/__init__.py` — export

**Modal**:
- Mismo diseño que CreateTaskModal pero:
  - Título y descripción pre-poblados con valores actuales
  - Campos editables
  - Solo para tareas `pending` o `in_progress` (validación igual que MCP tool)

**TuiBridge.update_task**:
```python
async def update_task(self, task_id: str, title: str | None = None, 
                      description: str | None = None) -> bool:
    # Misma lógica que _update_task en tools/tasks.py
```

**Criterios**:
- [ ] E abre modal con datos pre-poblados
- [ ] Actualiza title y/o description
- [ ] Valida: solo pending/in_progress
- [ ] Tarea no encontrada → error
- [ ] Tests

#### 3.2 Eliminar tarea (Supr/Delete)

**Archivos**:
- `src/agent_bridge/ui/kanban_tui.py` — +binding `delete` + `action_delete_task`
- `src/agent_bridge/ui/tui_bridge.py` — +`delete_task(task_id)`

**Flujo**:
1. Presiona Supr
2. Confirmación: "¿Eliminar tarea '{titulo}'?" (Sí/No)
3. Si confirma: `TuiBridge.delete_task(task_id)` → DELETE en DB
4. Notify "🗑 Tarea eliminada"
5. Refresh

**TuiBridge.delete_task**:
```python
async def delete_task(self, task_id: str) -> bool:
    # Misma lógica que _delete_task en tools/tasks.py
    # DELETE FROM reviews WHERE task_id = ?
    # DELETE FROM tasks WHERE id = ?
```

**Criterios**:
- [ ] Supr abre confirmación
- [ ] Solo pending/in_progress (validación)
- [ ] Tarea no encontrada → error
- [ ] Tests

#### 3.3 Asignar tarea a agente (A)

**Archivos**:
- `src/agent_bridge/ui/kanban_tui.py` — +binding `a` + `action_assign_task`
- `src/agent_bridge/ui/assign_task_modal.py` — NUEVO
- `src/agent_bridge/ui/tui_bridge.py` — +`assign_task(task_id, agent_id)`, +`get_available_agents()`

**Modal**:
- Lista de agentes disponibles (status != offline)
- Cada agente: nombre + rol + status 🟢🟡
- Seleccionar y confirmar
- Solo tareas pending sin assignee o pending con assignee (reasignar)

**TuiBridge.assign_task**:
```python
async def assign_task(self, task_id: str, agent_id: str) -> bool:
    # UPDATE tasks SET assignee = ?, status = 'in_progress'
    # Verificar que el agente existe
    # Verificar max_concurrent_tasks del agente
```

**TuiBridge.get_available_agents**:
```python
async def get_available_agents(self) -> list[dict]:
    # SELECT * FROM agents WHERE status != 'offline'
```

**Criterios**:
- [ ] A abre modal con lista de agentes online
- [ ] Asigna tarea (UPDATE assignee + status = 'in_progress')
- [ ] Valida que agente exista
- [ ] Valida max_concurrent_tasks
- [ ] Tests

#### 3.4 Arreglar Detalle (D)

**Archivo**: `src/agent_bridge/ui/kanban_tui.py`

Actualmente `action_show_detail` es un placeholder. El detalle real YA se muestra en el panel derecho (TaskDetail). Cambiar D para que abra un modal con el detalle completo (misma info pero en pantalla completa/centrada).

**Criterios**:
- [ ] D muestra detalle completo en modal (opcional vs enfoque simple: solo remover el placeholder)
- [ ] O simplemente sacar el binding D si el panel derecho ya muestra todo

---

## Orden de ejecución

```
Fase 1 → Fase 2 → Fase 3 (3.1 + 3.2 + 3.3 en paralelo, 3.4 opcional)

Dependencias:
- Fase 2 requiere Fase 1 (ChatPanel debe existir para integrarlo)
- Fase 3 es independiente de Fases 1-2 (toca otros archivos)
- Dentro de Fase 3: 3.1, 3.2, 3.3 no tienen dependencias entre sí
```

## Esfuerzo estimado

| Fase | Archivos | Cambio estimado | Tests |
|---|---|---|---|
| Fase 1 — ChatPanel | 1 nuevo, 1 modify | ~350 líneas | 10-15 nuevos |
| Fase 2 — Integración | 1 modify, 1 delete | ~80 líneas | 5-8 modificar |
| Fase 3.1 — Editar | 1 nuevo, 2 modify | ~150 líneas | 5 nuevos |
| Fase 3.2 — Eliminar | 2 modify | ~80 líneas | 3 nuevos |
| Fase 3.3 — Asignar | 1 nuevo, 2 modify | ~180 líneas | 6 nuevos |
| **Total** | **~10 archivos** | **~840 líneas** | **~30-35 nuevos** |

## Checklist de revisión por tarea

| Ítem | Verificación |
|---|---|
| Criterios de aceptación | Todos los `[ ]` marcados como `[x]` |
| Tests | Toda lógica nueva tiene tests |
| Test suite completa | `uv run pytest` todo verde |
| Compatibilidad hacia atrás | Kanban existente no se rompe |
| Chat existente | `agent-bridge start` (sin --kanban) sigue funcionando con chat_tui.py |
| Lint | `uv run ruff check src/` sin errores |

---

*Próximo paso: ejecutar Fase 1 (ChatPanel).*

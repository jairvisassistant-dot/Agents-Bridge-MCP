# Agent Bridge

**MCP Broker** para colaboración multi-agente entre Claude Code (Arquitecto),
OpenCode (Desarrollador) y un humano supervisor.

Agent Bridge expone un **servidor MCP** (Model Context Protocol) que orquesta
el flujo de trabajo completo: planificación → tareas → implementación →
revisión → aprobación, todo con control de permisos, trazabilidad y
visibilidad en tiempo real.

---

## Arquitectura

```
┌──────────────────────────────────────────────────────────────────┐
│                    Agent Bridge (MCP Broker)                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Claude Code  │  │   OpenCode   │  │      Humano (TUI)      │ │
│  │  (Arquitecto) │  │ (Desarrollador)│  │    (Supervisor)       │ │
│  │  AGENT_ID=cc1 │  │ AGENT_ID=oc1 │  │    agent-bridge start  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬─────────────┘ │
│         │                 │                      │               │
│         └────────┬────────┘──────────────────────┘               │
│                  │            MCP Protocol (SSE / stdio)          │
│          ┌───────┴────────┐                                      │
│          │  MCP Server    │                                      │
│          │  ┌──────────┐  │                                      │
│          │  │ Permisos │  │  Role-based tool access control      │
│          │  ├──────────┤  │                                      │
│          │  │  Tools   │  │  plan.* task.* review.* chat.*       │
│          │  ├──────────┤  │                                      │
│          │  │ DB State │  │  SQLite + WAL (persistente)          │
│          │  └──────────┘  │                                      │
│          └───────┬────────┘                                      │
│                  │                                                │
│          ┌───────┴────────┐                                      │
│          │  SQLite .db    │  Planes, tareas, reviews, msgs       │
│          └────────────────┘                                      │
└──────────────────────────────────────────────────────────────────┘
```

### Flujo de trabajo

```
Arquitecto                Humano                 Desarrollador
    │                       │                        │
    ├── plan.create ────────┤                        │
    ├── task.create ────────┤                        │
    │                       │                        ├── task.claim
    │                       │                        ├── task.submit_work
    ├── review.start ───────┤                        │
    ├── review.approve ─────┤                        │
    │                       │                        │
    └── chat ───────────────┼── chat ────────────────┘
                            │
                     (TUI en tiempo real)
```

### Fases

| Fase | Qué pasa | Tools involucradas |
|------|----------|-------------------|
| **1. Ideación** | El humano idea, el arquitecto planifica | `chat.*`, `plan.create` |
| **2. Especificación** | El arquitecto detalla tareas | `plan.update`, `task.create` |
| **3. Implementación** | El dev toma tareas y las implementa | `task.claim`, `task.submit_work` |
| **4. Revisión** | El arquitecto revisa, aprueba o pide cambios | `review.*`, `task.get_diff` |
| **5. Workflow integrado** | Server + TUI, reconexión, reassign automático | `agent-bridge start` |

---

## Instalación

```bash
git clone <repo>
cd agent-bridge
uv sync
```

Requiere Python 3.12+.

### Dependencias

- `mcp>=1.6.0` — SDK del Model Context Protocol
- `textual>=1.0.0` — Terminal UI (chat para el humano)
- `httpx>=0.28.0` — Cliente HTTP (para modo SSE)
- `aiosqlite>=0.20.0` — SQLite async

---

## Configuración

```bash
# Crear bridge.json con valores por defecto
agent-bridge configure --init

# Editar bridge.json para asignar roles
```

El archivo `bridge.json` se busca en:
1. `./bridge.json` (directorio actual)
2. `~/.config/agent-bridge/bridge.json`
3. `~/.agent-bridge.json`

### Ejemplo de bridge.json

```json
{
  "version": 1,
  "agents": [
    {
      "id": "claude-code-1",
      "name": "Terminal Principal",
      "role": "architect"
    },
    {
      "id": "opencode-1",
      "name": "Terminal Secundaria",
      "role": "developer"
    }
  ],
  "settings": {
    "heartbeat_interval_seconds": 30,
    "offline_timeout_seconds": 300
  }
}
```

Los roles disponibles por defecto son:

| Rol | Permisos |
|-----|----------|
| `architect` | `plan.*`, `task.create`, `task.get_diff`, `review.*`, `chat.*`, `agent.*`, `skill.*` |
| `developer` | `task.list`, `task.get`, `task.claim`, `task.submit_work`, `chat.*`, `agent.*`, `skill.*` |
| `default` | `chat.*`, `agent.heartbeat`, `agent.list`, `skill.*`, `hello` |

Se pueden definir **skills personalizados** en `bridge.json` para roles custom.

---

## Uso

### Terminal 1: Arquitecto (Claude Code)

```bash
AGENT_BRIDGE_ID=claude-code-1 agent-bridge
```

### Terminal 2: Desarrollador (OpenCode)

```bash
AGENT_BRIDGE_ID=opencode-1 agent-bridge
```

### Terminal 3: Humano (TUI interactiva)

```bash
agent-bridge start
```

Esto levanta:
- **Server SSE** en `http://127.0.0.1:8765/sse` (para Claude Code y OpenCode)
- **TUI** interactiva (chat en tiempo real, indicadores de estado)

### Subcomandos

#### `agent-bridge` — Modo directo (stdio)

Inicia el servidor en modo stdio. Usado por Claude Code y OpenCode como
subprocess MCP. Es el modo default.

```bash
AGENT_BRIDGE_ID=claude-code-1 agent-bridge
```

Flags:
- `--db-path` — Ruta a la DB (default: `bridge.db`)
- `--transport` — `stdio` (default) o `sse`
- `--host` / `--port` — Para modo SSE

#### `agent-bridge start` — Server SSE + TUI

Levanta el servidor SSE en background y la TUI en la terminal actual.

```bash
agent-bridge start                    # Server SSE + TUI
agent-bridge start --headless         # Solo server SSE
agent-bridge start --ui-only          # Solo TUI (conectarse a server existente)
agent-bridge start --port 9876        # Puerto custom
agent-bridge start --db-path custom.db
```

#### `agent-bridge configure` — Configuración

Crea o edita `bridge.json`.

```bash
agent-bridge configure --init         # Crea bridge.json por defecto
```

#### `agent-bridge reset` — Limpiar estado

Borra TODOS los datos (planes, tareas, mensajes, agentes) y recrea el schema desde cero.

```bash
agent-bridge reset                    # Pide confirmación
agent-bridge reset --force            # No pregunta
agent-bridge reset --db-path custom.db
```

#### `agent-bridge export` — Exportar plan

Exporta un plan completo con todas sus tareas y revisiones como JSON.

```bash
agent-bridge export <plan_id>                             # Salida por stdout
agent-bridge export <plan_id> --output plan.json          # Guardar a archivo
agent-bridge export <plan_id> -o plan.json --db-path custom.db
```

#### `agent-bridge import` — Importar plan

Importa un plan (con tareas y revisiones) desde un archivo JSON exportado previamente.

```bash
agent-bridge import plan.json
agent-bridge import plan.json --db-path custom.db
```

#### `--dry-run` — Modo de prueba

Al iniciar el servidor con `--dry-run`, la base de datos se abre en memoria (`:memory:`)
y todas las operaciones de escritura (INSERT, UPDATE, DELETE) se registran en el log
pero NO se ejecutan. Las lecturas (SELECT) sí funcionan contra la DB en memoria.

```bash
# Modo stdio con dry-run
AGENT_BRIDGE_ID=claude-code-1 agent-bridge --dry-run

# Modo SSE headless con dry-run
agent-bridge start --headless --dry-run

# Modo completo (SSE + TUI) con dry-run
agent-bridge start --dry-run
```

Útil para probar configuraciones, permisos, y el flujo de herramientas sin
modificar la base de datos real. Todas las operaciones de escritura aparecen
en el log con el prefijo `[DRY-RUN]`.

---

## Flujo de trabajo completo

### 1. El Arquitecto crea un plan

```json
// tools/call: plan.create
{"title": "Implementar autenticación JWT"}
```

### 2. El Arquitecto agrega tareas al plan

```json
// tools/call: task.create
{"plan_id": "<plan-id>", "title": "Middleware de JWT"}
```

### 3. El Desarrollador toma una tarea

```json
// tools/call: task.claim
{"task_id": "<task-id>"}
```

La tarea pasa de `pending` → `in_progress`.

### 4. El Desarrollador entrega su trabajo

```json
// tools/call: task.submit_work
{"task_id": "<task-id>", "summary": "Hecho", "diff": "..."}
```

La tarea pasa a `review`.

### 5. El Arquitecto revisa

```json
// tools/call: task.get_diff
{"task_id": "<task-id>"}

// tools/call: review.approve
{"task_id": "<task-id>", "comment": "LGTM!"}
```

La tarea pasa a `approved`.

---

## Características técnicas

### Permisos por rol

Cada tool checkea que el agente tenga el rol adecuado. Si no, devuelve un
error estructurado:

```json
{"error": "permission_denied", "your_role": "developer", "allowed_tools": [...]}
```

### Reasignación automática de tareas

Cada 60 segundos, el servidor verifica qué agents tienen `last_seen` vencido
(más de 5 minutos sin heartbeat). Los marca como `offline` y reassigna sus
tareas `in_progress` de vuelta a `pending`.

### Reconexión con exponential backoff

La TUI reconecta automáticamente si el proceso subyacente se cae:
1s → 2s → 4s → 8s → 16s → 30s (max). Muestra indicadores en el chat log.

### Structured logging

Cada llamada a tool genera un log con:
```
request_id=<uuid> tool=<name> agent=<id> duration=<ms>
```

### Manejo de errores

Todas las tools están envueltas en try/except. Si algo falla, se devuelve:
```json
{"error": "internal_error", "detail": "...", "request_id": "..."}
```

### State machine

Las transiciones de estado están validadas por una máquina de estados:

```
Plan:     idle → planning → tasks_ready → in_progress → completed
Task:     pending → in_progress → review → approved
                                    ↓
                              changes_requested → review
Review:   pending → in_review → approved / changes_requested
Thread:   open → resolved
```

---

## Desarrollo

### Correr tests

```bash
cd agent-bridge
uv run pytest
```

### Tests incluidos

| Archivo | Cubre |
|---------|-------|
| `tests/test_config.py` | Config loader, skills built-in, bridge.json |
| `tests/test_permissions.py` | Permission layer, role enforcement |
| `tests/test_chat.py` | Chat, @menciones, threads |
| `tests/test_state_machine.py` | State transitions for all entities |
| `tests/test_integration.py` | Full MCP stdio cycle (plan → task → claim → submit → review → approve) |
| `tests/test_reassignment.py` | Stale agent detection, task reassignment |
| `tests/test_start_command.py` | Argument parsing for `start` subcommand |
| `tests/test_edge_cases.py` | Concurrent claims, concurrent review, invalid operations |
| `tests/test_stress.py` | Stress test: 10 agents claiming 5 tasks concurrently |

### Estructura del proyecto

```
agent-bridge/
├── pyproject.toml
├── README.md
├── src/
│   └── agent_bridge/
│       ├── __init__.py
│       ├── __main__.py          # Entry: python -m agent_bridge
│       ├── main.py              # CLI: argument parsing, start command
│       ├── server.py            # MCP server factory, permissions, reassign
│       ├── config.py            # bridge.json loader, built-in skills
│       ├── state/
│       │   ├── database.py      # SQLite + WAL, async helpers
│       │   ├── models.py        # Pydantic models
│       │   └── state_machine.py # State transition validation
│       ├── tools/
│       │   ├── agents.py        # agent.heartbeat, agent.list, etc.
│       │   ├── chat.py          # chat.send, chat.read, threads
│       │   ├── planner.py       # plan.create, plan.list, etc.
│       │   ├── review.py        # review.start, review.approve, etc.
│       │   ├── tasks.py         # task.create, task.claim, etc.
│       │   └── skills.py        # skill.list, skill.get
│       └── ui/
│           ├── chat_tui.py      # Textual-based chat TUI
│           └── __init__.py
└── tests/
    ├── test_chat.py
    ├── test_config.py
    ├── test_integration.py
    ├── test_permissions.py
    ├── test_reassignment.py
    ├── test_start_command.py
    ├── test_state_machine.py
    └── __init__.py
```

---

## Licencia

MIT

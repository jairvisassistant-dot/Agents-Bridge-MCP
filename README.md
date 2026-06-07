# Agent Bridge

**MCP Broker** para colaboración multi-agente entre Claude Code (Arquitecto),
OpenCode (Desarrollador) y un humano supervisor.

---

## ¿Cómo funciona Agent Bridge?

Agent Bridge es un **servidor MCP** (Model Context Protocol) al que se conectan
los agentes (Claude Code, OpenCode) y el humano (vía TUI). Todos comparten el
**mismo estado**: planes, tareas, mensajes, revisiones — todo vive en una base
SQLite compartida.

### El protocolo MCP

MCP es un protocolo JSON-RPC que permite que agentes de IA llamen **tools**
(herramientas) desde un servidor remoto o local. Agent Bridge expone tools como
`plan.create`, `task.claim`, `chat.send`, etc.

Cada agente se conecta al bridge de una de estas dos formas:

| Modo | Cómo | Quién lo usa |
|------|------|-------------|
| **stdio** | El agente lanza el bridge como subproceso y se comunican por stdin/stdout | Claude Code, OpenCode |
| **SSE** | El bridge expone un endpoint HTTP (`/sse`), los agentes se conectan vía HTTP | La TUI humana, clientes remotos |

Ambos modos ven la **misma base de datos** y el **mismo servidor**, así que
comparten estado aunque estén en terminales distintas.

### ¿Qué comparten los participantes?

```
┌──────────────────────────────────────────────────────────────────┐
│                    Agent Bridge (MCP Broker)                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Claude Code  │  │   OpenCode   │  │      Humano (TUI)      │ │
│  │  (Arquitecto) │  │ (Desarrollador)│  │    (Supervisor)       │ │
│  │  AGENT_ID=cc1 │  │ AGENT_ID=oc1 │  │    agent-bridge start  │ │
│  │  modo stdio   │  │ modo stdio   │  │    modo SSE + TUI      │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬─────────────┘ │
│         │                 │                      │               │
│         └────────┬────────┘──────────────────────┘               │
│                  │            MCP Protocol (SSE / stdio)          │
│          ┌───────┴────────┐                                      │
│          │  MCP Server    │                                      │
│          │  ┌──────────┐  │                                      │
│          │  │ Permisos │  │  Valida qué tools puede llamar cada  │
│          │  │          │  │  uno según su rol                    │
│          │  ├──────────┤  │                                      │
│          │  │  Tools   │  │  plan.* task.* review.* chat.*       │
│          │  ├──────────┤  │                                      │
│          │  │ DB State │  │  SQLite + WAL (persistente)          │
│          │  └──────────┘  │                                      │
│          └───────┬────────┘                                      │
│                  │                                                │
│          ┌───────┴────────┐                                      │
│          │  SQLite .db    │  El MISMO archivo para todos         │
│          │  bridge.db     │  (plan, tareas, msgs, agentes)       │
│          └────────────────┘                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Instalación

Agent Bridge puede instalarse de dos formas: **global** (disponible en cualquier
proyecto) o **local** (como dependencia de desarrollo de un proyecto específico).

### Prerrequisitos

- Python 3.12+
- `uv` (gestor de proyectos Python)

### Opción 1: Instalación global (recomendada)

Con `uv tool install` el comando `agent-bridge` queda disponible en el PATH
desde cualquier directorio:

```bash
# Desde el directorio donde clonaste Agent Bridge
cd /ruta/a/agents-bridge-mcp
uv sync
uv tool install --editable .
```

Después de esto:

```bash
# Funciona desde CUALQUIER proyecto
cd /ruta/a/mi-proyecto
agent-bridge --help
```

### Opción 2: Instalación local (como dev dependency)

Si preferís no instalar nada global y mantener todo acotado al proyecto:

```bash
# Desde el proyecto donde querés usar Agent Bridge
cd /ruta/a/mi-proyecto
uv add --dev --editable /ruta/a/agents-bridge-mcp
```

Después lo ejecutás con `uv run`:

```bash
uv run agent-bridge --help
```

---

## Inicializar un proyecto (`agent-bridge init`)

Una vez instalado, entrá al proyecto donde querés usar Agent Bridge y ejecutá:

```bash
cd /ruta/a/mi-proyecto
agent-bridge init
```

Esto crea automáticamente:

| Archivo | Propósito |
|---------|-----------|
| `bridge.json` | Configuración de roles de los agentes |
| `.agentes/dev.Skill` | Skill para OpenCode (rol Desarrollador) |
| `.agentes/architect.Skill` | Skill para Claude Code (rol Arquitecto) |

Opciones:

```bash
agent-bridge init --path /ruta/a/mi-proyecto   # Directorio custom
agent-bridge init --dev-dep                     # Muestra comando para agregar como dev dep
```

### ¿Qué contiene cada skill?

**`.agentes/dev.Skill`** — para OpenCode (Desarrollador):
- Se conecta al bridge como `AGENT_BRIDGE_ID=opencode-1`
- Hace `git pull` antes de empezar
- Reporta disponibilidad en la TUI via `chat.send`
- Consulta tareas pendientes, las claimea y las implementa
- Hace `git push` al finalizar

**`.agentes/architect.Skill`** — para Claude Code (Arquitecto):
- Se conecta al bridge como `AGENT_BRIDGE_ID=claude-code-1`
- Hace `git pull` antes de empezar
- Reporta disponibilidad en la TUI via `chat.send`
- Crea planes, define tareas, revisa entregas
- Hace `git push` al finalizar

> Las skills están en formato **Gentle AI** con frontmatter, activation contract,
> hard rules, decision gates y execution steps. Son legibles tanto por OpenCode
> como por Claude Code.

---

## Skills de agente (`.agentes/`)

Las skills en `.agentes/` son archivos de instrucciones que cada agente lee para
saber cómo conectarse al ecosistema Agent Bridge. Están escritas en un formato
estructurado con frontmatter YAML y secciones de workflow.

| Archivo | Rol | Agente |
|---------|-----|--------|
| `dev.Skill` | Desarrollador | OpenCode |
| `architect.Skill` | Arquitecto | Claude Code |

Ambos archivos conviven en `.agentes/` y son visibles desde las dos terminales.
Cada una contiene **exactamente** las tools, restricciones y flujo que le
corresponden a su rol.

---

## Cómo levantar la TUI (Humano)

La TUI es una interfaz de **terminal a pantalla completa** (no es una ventana
gráfica ni web). Se ve así:

```
┌──────────────────────────────────────────────────────────────┐
│  AGENT BRIDGE CHAT  |  Agentes: 🟢 Arq · ⚫ Dev             │
├──────────────────────────────────────────────────────────────┤
│  ✓ Conectado al Agent Bridge                                  │
│                                                              │
│  14:30 human: Hola equipo                                    │
│  14:31 @arquitecto: necesito un plan para X                  │
│                                                              │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ > Escribí tu mensaje…                                [Enviar]│
└──────────────────────────────────────────────────────────────┘
```

Para levantarla:

```bash
agent-bridge start
```

Esto abre la TUI en la **misma terminal**. Dejá de ver el prompt y entrás en
la interfaz. Para salir: **`Ctrl+C`**.

Lo que levanta `agent-bridge start`:
- **Servidor SSE** en `http://127.0.0.1:8765/sse` — ahí se conectan los agentes
- **TUI** interactiva — para que el humano vea el chat y el estado

Variantes:

```bash
agent-bridge start                     # Server SSE + TUI
agent-bridge start --headless          # Solo server (sin TUI)
agent-bridge start --dry-run           # Modo prueba (no escribe en DB)
```

---

## Flujo completo con skills

### Diagrama del flujo

```
Terminal 1                          Terminal 2                  Terminal 3
─────────────────                   ──────────────────          ──────────────────
agent-bridge start                  OpenCode                     Claude Code
        │                                │                            │
        │  (TUI esperando)               │                            │
        │                                │                            │
        │◄────── @dev.Skill ──────────────┤                            │
        │      (git pull, conecta,       │                            │
        │       avisa 🟢 en TUI)         │                            │
        │                                │                            │
        │◄────── @architect.Skill ─────────────────────────────────────┤
        │      (git pull, conecta,       │                            │
        │       avisa 🟢 en TUI)         │                            │
        │                                │                            │
  ╔══════════════════════════════════════════════════════════════╗
  ║  Desde la TUI el humano empieza a delegar tareas            ║
  ╚══════════════════════════════════════════════════════════════╝
        │                                │                            │
  humano: @arquitecto,                  │                            │
  hacé un plan para X ──────────────────┤                            │
        │                                ├── plan.create              │
        │                                ├── task.create (x3)         │
        │                                │                            │
        │                                │                     @dev: tenés tareas
        │                                │◄──── task.claim ───────────│
        │                                │◄──── implementa ───────────│
        │                                │◄──── task.submit_work ─────│
        │                                ├── review.start             │
        │                                ├── review.request_changes   │
        │                                │◄──── corrige ──────────────│
        │                                ├── review.approve           │
```

### Paso a paso

1. **Terminal 1** — El humano levanta la TUI:
   ```bash
   agent-bridge start
   ```

2. **Terminal 2** — El humano abre OpenCode y ejecuta la skill del desarrollador:
   ```
   @dev.Skill
   ```
   La skill: hace `git pull`, conecta al bridge como `opencode-1`,
   reporta `🟢 Desarrollador conectado y listo` en la TUI.

3. **Terminal 3** — El humano abre Claude Code y ejecuta la skill del arquitecto:
   ```
   @architect.Skill
   ```
   La skill: hace `git pull`, conecta al bridge como `claude-code-1`,
   reporta `🟢 Arquitecto conectado y listo` en la TUI.

4. **Desde la TUI**, el humano empieza a delegar funciones usando @menciones:
   - `@arquitecto: hacé un plan para implementar autenticación`
   - `@desarrollador: tomá la tarea de middleware JWT`
   - `@desarrollador: pará, hacelo distinto`

### Fases del ciclo

| Fase | Qué pasa | Tools involucradas |
|------|----------|-------------------|
| **1. Ideación** | El humano idea, el arquitecto planifica | `chat.*`, `plan.create` |
| **2. Especificación** | El arquitecto detalla tareas | `plan.update`, `task.create` |
| **3. Implementación** | El dev toma tareas y las implementa | `task.claim`, `task.submit_work` |
| **4. Revisión** | El arquitecto revisa, aprueba o pide cambios | `review.*`, `task.get_diff` |
| **5. Discusión autónoma** | Agentes discuten en threads con turnos | `chat.thread_*`, `chat.thread_get_pending` |

---

## Configuración

Creá el archivo `bridge.json` para definir qué rol tiene cada agente:

```bash
agent-bridge init
```

O si ya tenés el proyecto inicializado y querés recrearlo:

```bash
# Editar bridge.json manualmente o regenerarlo
agent-bridge init --path .
```

El server busca `bridge.json` en este orden:
1. `./bridge.json` (directorio actual — el más práctico)
2. `~/.config/agent-bridge/bridge.json`
3. `~/.agent-bridge.json`

### Ejemplo

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

### Roles por defecto

| Rol | Tools permitidas |
|-----|-----------------|
| `architect` | `plan.*`, `task.create`, `task.get_diff`, `review.*`, `chat.*` (send, read, mark_read, threads), `agent.*` (heartbeat, list, get, set_status, whoami, ping, pong, idle, shutdown_request, shutdown_approve), `skill.*`, `hello` |
| `developer` | `task.*` (list, get, claim, submit_work), `chat.*` (send, read, mark_read, threads), `agent.*` (heartbeat, list, get, set_status, whoami, ping, pong, idle, shutdown_request, shutdown_approve), `skill.*`, `hello` |
| `default` | `chat.*` (send, read, mark_read, threads), `agent.heartbeat`, `agent.list`, `agent.get`, `agent.whoami`, `skill.*`, `hello` |

Se pueden definir **skills personalizados** en `bridge.json` para roles custom.

---

## Referencia de comandos

### `agent-bridge init` — Inicializar proyecto

Crea `bridge.json` y `.agentes/` skills en el proyecto actual:

```bash
agent-bridge init
agent-bridge init --path /ruta/a/mi-proyecto
agent-bridge init --dev-dep     # Incluye comando para agregar como dev dep
```

### `agent-bridge start` — Server SSE + TUI

Levanta el SSE server + interfaz humana:

```bash
agent-bridge start                     # Server SSE + TUI
agent-bridge start --headless          # Solo server SSE
agent-bridge start --ui-only           # Solo TUI (conectarse a server existente)
agent-bridge start --port 9876         # Puerto custom
agent-bridge start --db-path otra.db   # DB custom
agent-bridge start --dry-run           # Modo prueba (DB en memoria)
```

### `agent-bridge` — Modo directo (stdio)

Conecta un agente al bridge. Usado por Claude Code y OpenCode como subproceso MCP:

```bash
AGENT_BRIDGE_ID=claude-code-1 agent-bridge
AGENT_BRIDGE_ID=opencode-1 agent-bridge
```

Flags:
- `--db-path` — Ruta a la DB (default: `bridge.db`)
- `--transport` — `stdio` (default) o `sse`
- `--host` / `--port` — Para modo SSE

### `agent-bridge reset` — Limpiar estado

```bash
agent-bridge reset                     # Pide confirmación
agent-bridge reset --force             # Sin preguntar
```

### `agent-bridge export / import` — Planes

```bash
agent-bridge export <plan_id> -o plan.json
agent-bridge import plan.json
```

---

## Desarrollo

### Correr tests

```bash
uv sync --extra test
uv run pytest -v
```

### Tests incluidos

| Archivo | Cubre |
|---------|-------|
| `tests/test_config.py` | Config loader, skills built-in, bridge.json |
| `tests/test_permissions.py` | Permission layer, role enforcement, agent lifecycle tools |
| `tests/test_chat.py` | Chat, @menciones, threads, discusión autónoma, mark_read, paginación, mensajes tipados |
| `tests/test_state_machine.py` | State transitions for all entities |
| `tests/test_integration.py` | Full MCP stdio cycle (plan → task → claim → submit → review → approve) |
| `tests/test_reassignment.py` | Stale agent detection, task reassignment |
| `tests/test_start_command.py` | Argument parsing for `start` subcommand and legacy flags |
| `tests/test_edge_cases.py` | Concurrent claims, concurrent review, invalid operations |
| `tests/test_stress.py` | Stress test: 10 agents claiming 5 tasks concurrently |
| `tests/test_database_refactor.py` | Dry-run mode, database initialization, migrations, with_transaction |

---

## Estructura del proyecto

```
agents-bridge-mcp/                    ← Proyecto raíz de Agent Bridge
├── pyproject.toml                    ← Dependencias y entry point
├── README.md
├── src/
│   └── agent_bridge/
│       ├── __main__.py               ← Entry: python -m agent_bridge
│       ├── main.py                   ← CLI: argument parsing, todos los comandos
│       ├── server.py                 ← MCP server factory, permisos, reassign
│       ├── config.py                 ← bridge.json loader, built-in skills
│       ├── state/
│       │   ├── database.py           ← SQLite + WAL, helpers async
│       │   ├── models.py             ← Modelos Pydantic
│       │   └── state_machine.py      ← Validación de transiciones de estado
│       ├── tools/
│       │   ├── agents.py             ← agent.heartbeat, agent.list, etc.
│       │   ├── chat.py               ← chat.send, chat.read, threads
│       │   ├── planner.py            ← plan.create, plan.list, etc.
│       │   ├── review.py             ← review.start, review.approve, etc.
│       │   ├── tasks.py              ← task.create, task.claim, etc.
│       │   └── skills.py             ← skill.list, skill.get
│       └── ui/
│           ├── chat_tui.py           ← TUI con Textual (chat humano)
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

Cuando inicializás un proyecto con `agent-bridge init`, se crea:

```
mi-proyecto/                          ← Tu proyecto
├── bridge.json                       ← Configuración de roles
├── .agentes/
│   ├── dev.Skill                     ← Skill para OpenCode (Desarrollador)
│   └── architect.Skill               ← Skill para Claude Code (Arquitecto)
└── bridge.db                         ← Base de datos (se crea al usar el bridge)
```

---

## Características técnicas

### Permisos por rol

Cada tool checkea que el agente tenga el rol adecuado:

```json
{"error": "permission_denied", "your_role": "developer", "allowed_tools": [...]}
```

### Reasignación automática de tareas

Cada 60s, el servidor verifica qué agents tienen heartbeat vencido (>5 min).
Los marca `offline` y reassigna sus tareas a `pending`.

### Reconexión con exponential backoff

La TUI reconecta automáticamente si el proceso se cae:
1s → 2s → 4s → 8s → 16s → 30s (max).

### State machine

```
Plan:     idle → planning → tasks_ready → in_progress → completed
Task:     pending → in_progress → review → approved
                                    ↓
                              changes_requested → review
Review:   pending → in_review → approved / changes_requested
Thread:   open → resolved
```

### Manejo de errores

Todas las tools están envueltas en try/except. Si algo falla:

```json
{"error": "internal_error", "detail": "...", "request_id": "..."}
```

---

## Licencia

MIT

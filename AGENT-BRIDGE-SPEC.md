# Agent Bridge: MCP Broker para Claude Code + OpenCode

> **Documento rector del proyecto.** Esto es lo que estamos construyendo. Si en algún momento dudamos si vamos bien, volvemos acá.

---

## 1. ¿Qué estamos construyendo?

Un **MCP Broker local** que conecta dos terminales con agentes de IA distintos — Claude Code (Arquitecto) y OpenCode (Desarrollador) — más un humano supervisor. El broker expone herramientas compartidas, un chat visible por todos los participantes, y un flujo de trabajo estructurado de plan → tareas → implementación → revisión.

### El problema que resuelve

Hoy, si querés que Claude Code planifique y OpenCode implemente, tenés que copiar y pegar manualmente entre terminales. No hay trazabilidad, no hay estado compartido, no hay forma de que el humano intervenga en el medio sin romper el flujo. Además, no hay forma de saber si el otro agente está vivo, qué rol tiene cada terminal, ni qué tools/capacidades le corresponden a cada rol.

### La solución

Un **servidor MCP** que ambos agentes tienen configurado, más una **UI de chat** que el humano ve. El server es la fuente de verdad única para:
- Plan de trabajo activo
- Cola de tareas
- Artefactos generados
- Historial de revisiones
- Mensajes del chat
- **Presencia y actividad de los agentes** ← NUEVO
- **Configuración de roles por terminal** ← NUEVO
- **Skills y permisos por rol** ← NUEVO

---

## 2. Ideas tomadas de cada proyecto existente

### AgentBridge (`raysonmeng/agent-bridge`) — ⭐112

| Idea | Cómo la aplicamos |
|---|---|
| **Arquitectura two-process**: foreground MCP client + background daemon | Nuestro server MCP se compone de un proceso que habla MCP (stdio) y un daemon persistente con SQLite. Si un agente se cierra, el daemon y el estado sobreviven. |
| **Reconexión automática** con exponential backoff | Cuando OpenCode o Claude Code se reinician, reconectan al broker sin perder estado. |
| **Bidireccionalidad en la misma sesión** | Ambos agentes ven el mismo plan y las mismas tareas. Los mensajes del chat llegan a ambos en tiempo real. |

### claude-code-teams-mcp (`cs50victor/claude-code-teams-mcp`) — ⭐266

| Idea | Cómo la aplicamos |
|---|---|
| **Aislamiento con tmux** | Cada agente corre en su propio contexto. El broker no asume que los agentes comparten memoria. |
| **File locks para concurrencia** | Usamos file locks + SQLite WAL para que `claim_task` y `submit_work` no se pisen entre sí. |
| **Mensajería pull-based con inbox** | Cada agente tiene una bandeja de entrada. Revisa mensajes cuando está ocioso o al comenzar una tarea. No hay push. |
| **Detección de ciclos en dependencias** | Si el arquitecto crea dependencias circulares entre tareas, el broker lo rechaza. |
| **Soporte multi-cliente** | El server MCP funciona tanto con Claude Code como con OpenCode sin cambios. |

### Agent-MCP (`rinadelph/Agent-MCP`) — ⭐1200+

| Idea | Cómo la aplicamos |
|---|---|
| **Grafo de conocimiento compartido** | Cada artifact (plan, spec, diff, decisión) se guarda con metadatos y relaciones. No es un grafo complejo fase 1, pero la estructura de datos lo permite después. |
| **Agentes especializados en paralelo** | El arquitecto y el desarrollador tienen roles distintos. El server conoce qué puede hacer cada uno. |
| **Contexto persistente entre sesiones** | El estado vive en SQLite. Si cerrás todo y volvés al otro día, el plan sigue ahí. |

### AgentCommunicationMcp (`mattes337/AgentCommunicationMcp`)

| Idea | Cómo la aplicamos |
|---|---|
| **Almacenamiento file-based** | Cada agente puede tener archivos de contexto propio. El server administra el estado compartido, los agentes administran su contexto local. |
| **JSON-RPC sobre stdio** | MCP puro. No inventamos protocolos nuevos. |

### Claude-Codex-Review-Bridge (`amzer24/Claude-Codex-Review-Bridge-CRB`)

| Idea | Cómo la aplicamos |
|---|---|
| **Loop de review sin API keys** | Todo es local. Los agentes usan sus propios recursos (cada uno con su suscripción/modelo). El broker no necesita tokens. |
| **Flujo cíclico: escribe → revisa → corrige → repite** | El corazón de nuestro flujo de trabajo. El arquitecto revisa, el desarrollador corrige, ciclo hasta aprobación. |

---

## 3. Arquitectura del Sistema

```
                    ┌──────────────────────────────────┐
                    │       Shared Chat UI (Web/TUI)    │  ← EL HUMANO
                    │   • Threads                       │
                    │   • @menciones                    │
                    │   • Estado de agentes (vivo/muerto│
                    └──────────────┬───────────────────-┘
                                   │
                    ┌──────────────▼────────────────────┐
                    │       MCP Bridge Server            │
                    │                                    │
                    │  ┌──────────────────────────────┐  │
                    │  │ Permission Layer              │  │
                    │  │ • Valida qué tools puede      │  │
                    │  │   llamar cada rol según su    │  │
                    │  │   Skill asignado              │  │
                    │  └──────────┬───────────────────┘  │
                    │             │                       │
                    │  ┌──────────▼───────────────────┐  │
                    │  │  Core Engine (Python)         │  │
                    │  │  • State machine              │  │
                    │  │  • File locks                 │  │
                    │  │  • Agent presence/heartbeat   │  │
                    │  │  • Role router                │  │
                    │  └──────────┬───────────────────┘  │
                    │             │                       │
                    │  ┌──────────▼───────────────────┐  │
                    │  │  SQLite (estado compartido)   │  │
                    │  │  • Plan actual                │  │
                    │  │  • Tareas + estados           │  │
                    │  │  • Mensajes del chat          │  │
                    │  │  • Artefactos generados       │  │
                    │  │  • Historial de revisiones    │  │
                    │  │  • AGENTES (presencia, rol)   │  │
                    │  │  • CONFIG (roles, skills)     │  │
                    │  └──────────────────────────────┘  │
                    └──────┬──────────────┬──────────────┘
                           │              │
              ┌────────────▼─────┐  ┌─────▼──────────────┐
              │  Claude Code     │  │  OpenCode           │
              │  Rol: Arquitecto │  │  Rol: Desarrollador │
              │                  │  │                     │
              │  Skill:          │  │  Skill:             │
              │  • plan.*        │  │  • task.claim       │
              │  • review.*      │  │  • task.submit_work │
              │  • chat.*        │  │  • chat.*           │
              │  • agent.heartbeat│  │  • agent.heartbeat  │
              └──────────────────┘  └─────────────────────┘
```

### Stack propuesto

| Capa | Tecnología | Por qué |
|---|---|---|
| Lenguaje servidor | Python 3.12+ | `claude-teams-mcp` demostró que Python + MCP SDK funciona perfecto. Además, el SDK de MCP para Python es maduro. |
| Estado | SQLite + WAL | Cero dependencias externas. Transaccional. Los file locks resuelven concurrencia. |
| Chat UI | TUI con Textual (Python) o web liviana (FastAPI + HTMX) | La TUI corre al mismo nivel que las terminales de los agentes. No requiere deploy. |
| MCP SDK | `mcp` (Python SDK oficial) | Protocolo estándar. Ambos agentes lo soportan nativamente. |
| Archivos | File-based + SQLite | Los specs, diffs y artefactos se guardan como archivos. El SQLite tiene los metadatos y relaciones. |
| Concurrencia | `filelock` + SQLite WAL | Locks por tarea para evitar que dos agentes claimen la misma tarea. |
| Configuración | `bridge.json` (YAML o TOML) + `configure` CLI | Archivo editable por el humano + comando setup inicial. |

### Estados del sistema

```
───> idle ──> planning ──> tasks_ready ──> in_progress ──> review ──> approved
                    │                        │               │
                    └────────────────────────┴───────────────┘
                                      │
                                 changes_requested ───> in_progress
```

---

## 4. Sincronización y Detección de Actividad de Agentes

Este es un pilar fundamental del sistema. El server debe saber **quién está conectado, con qué rol, y si está activo** en este momento.

### Modelo de datos: sesiones de agente

Cada agente que se conecta al MCP Bridge tiene una **sesión** con:

| Campo | Descripción |
|---|---|
| `agent_id` | Identificador único del agente (ej: `claude-code-1`, `opencode-1`) |
| `role` | Rol asignado: `architect`, `developer`, `human` |
| `status` | `online`, `busy`, `away`, `offline` |
| `last_seen` | Timestamp del último heartbeat |
| `connected_since` | Timestamp de conexión |
| `metadata` | Versión del agente, plataforma, etc. |

### Protocolo de heartbeat

Cada agente DEBE llamar `agent.heartbeat` periódicamente (cada 30 segundos recomendado). El server trackea:

- Si un agente no hace heartbeat por **90 segundos** → pasa a `away`
- Si no hace heartbeat por **300 segundos** → pasa a `offline`
- Cuando vuelve a hacer heartbeat → vuelve a `online`

### Tools de presencia

| Tool | Input | Output | Quién la llama |
|---|---|---|---|
| `agent.heartbeat` | `agent_id`, `role`, `status?` | `{ "status": "online", "since": "..." }` | Todos los agentes (automático) |
| `agent.list` | — | `Agent[]` con estado de cada uno | Todos |
| `agent.get` | `agent_id` | `Agent` completo | Todos |
| `agent.set_status` | `agent_id`, `status` | estado actualizado | El propio agente |

### Comportamiento del server

1. Cuando un agente llama cualquier tool por primera vez, se registra automáticamente como `online`
2. El server rechaza tools si el agente intenta usar tools que no corresponden a su rol
3. Si un agente está `offline` por más de 5 minutos, el server **reasigna sus tareas a `pending`** y lo notifica en el chat
4. La UI del humano muestra el estado de cada agente (🟢 online, 🟡 busy, ⚫ offline)

### Routing de mensajes basado en presencia

```
@arquitecto → NO enviar si está offline → el server responde: 
  "Arquitecto está offline desde las 14:32. El mensaje quedó en su inbox."

@desarrollador → enviar siempre (inbox persistente)
```

---

## 5. Configuración de Roles por Terminal

El server NO asume que Claude Code es siempre el arquitecto y OpenCode el desarrollador. Esa asignación debe ser **configurable**.

### Archivo de configuración: `bridge.json`

Ubicación por defecto: `~/.config/agent-bridge/bridge.json` o `./bridge.json` en el directorio del proyecto.

```json
{
  "version": 1,
  "agents": [
    {
      "id": "claude-code-1",
      "name": "Terminal Principal",
      "role": "architect",
      "transport": "stdio",
      "metadata": {
        "type": "claude-code",
        "version": ">=0.1.0"
      }
    },
    {
      "id": "opencode-1",
      "name": "Terminal Secundaria",
      "role": "developer",
      "transport": "stdio",
      "metadata": {
        "type": "opencode",
        "version": ">=0.1.0"
      }
    }
  ],
  "settings": {
    "heartbeat_interval_seconds": 30,
    "offline_timeout_seconds": 300,
    "default_skill": "standard"
  }
}
```

### Comandos de configuración

| Comando | Descripción |
|---|---|
| `agent-bridge configure` | Asistente interactivo para configurar roles |
| `agent-bridge configure --set agent=opencode-1 role=developer` | Asignación directa |
| `agent-bridge configure --list` | Muestra configuración actual |
| `agent-bridge configure --init` | Crea `bridge.json` por defecto |

### ¿Cómo se resuelve el rol en cada llamada?

Hay dos mecanismos, **ordenados por prioridad**:

1. **Match por `agent_id`** (cuando el agente se identifica en `agent.heartbeat` con un ID conocido en `bridge.json`)
2. **Match por `transport` + `metadata`** (si el agente no se identifica, el server infiere el rol por cómo se conectó)
3. **Fallback a `default`** (si no hay match, el server rechaza la tool y pide configuración)

### Flujo de setup inicial

```
1. El usuario instala agent-bridge y ejecuta:
   $ agent-bridge configure --init

2. El server crea bridge.json con valores por defecto

3. El usuario edita bridge.json para asignar roles:
   "claude-code" → architect
   "opencode" → developer

4. (Opcional) El usuario ejecuta:
   $ agent-bridge configure --set agent=opencode-1 role=developer

5. Cada agente, al conectarse, se identifica con agent.heartbeat
   El server matcha el agent_id contra bridge.json y asigna el rol
```

---

## 6. Sistema de Skills por Rol

Cada rol tiene un **Skill** asociado que define: qué tools puede llamar, qué instructions tiene su system prompt, y qué restricciones aplican.

### Formato de Skill

Las skills se definen en `bridge.json` o en archivos separados dentro de `~/.config/agent-bridge/skills/`.

```json
{
  "skill": "architect",
  "version": 1,
  "description": "Skill del Arquitecto — planifica, revisa, aprueba",
  "allowed_tools": [
    "plan.create", "plan.get", "plan.list", "plan.update",
    "task.list", "task.get",
    "review.start", "review.approve", "review.request_changes",
    "review.get_history",
    "chat.send", "chat.read", "chat.thread_create",
    "agent.heartbeat", "agent.list", "agent.get"
  ],
  "instructions": [
    "Eres el Arquitecto del proyecto.",
    "Creas planes de trabajo y defines tareas con plan.create.",
    "Revisas el trabajo del desarrollador con review.*.",
    "Puedes aprobar o solicitar cambios.",
    "Siempre que recibas un @arquitecto, DEBES responder."
  ],
  "restrictions": {
    "max_concurrent_reviews": 3,
    "can_escalate_to_human": true
  }
}
```

```json
{
  "skill": "developer",
  "version": 1,
  "description": "Skill del Desarrollador — implementa, corrige, entrega",
  "allowed_tools": [
    "task.list", "task.get", "task.claim", "task.submit_work",
    "chat.send", "chat.read", "chat.thread_create",
    "agent.heartbeat", "agent.list", "agent.get"
  ],
  "instructions": [
    "Eres el Desarrollador del proyecto.",
    "Tomas tareas del plan con task.claim.",
    "Implementas y subes resultados con task.submit_work.",
    "Respondes a cambios solicitados por el arquitecto.",
    "Siempre que recibas un @desarrollador, DEBES responder."
  ],
  "restrictions": {
    "cannot_approve_own_work": true,
    "max_concurrent_tasks": 2
  }
}
```

### Validación de permisos en el server

Cada vez que un agente llama una tool, el server:

1. Obtiene el `agent_id` del heartbeat (o del transporte)
2. Busca el rol del agente en `bridge.json`
3. Carga el skill asociado al rol
4. Verifica que la tool esté en `allowed_tools`
5. Si NO está → devuelve error:
   ```json
   {
     "error": "permission_denied",
     "detail": "Tool 'review.approve' no está permitida para el rol 'developer'. 
                Skills asignada: developer. Tools permitidas: [task.list, task.claim, ...]"
   }
   ```
6. Si SÍ está → ejecuta la tool

### Skills por defecto (built-in)

El server incluye skills por defecto para `architect` y `developer`. El usuario puede:
- Usarlas tal cual
- Modificarlas en `bridge.json`
- Crear skills personalizadas (ej: `senior-developer`, `reviewer-assistant`)

### Descubrimiento de skills

| Tool | Input | Output |
|---|---|---|
| `skill.list` | — | `Skill[]` disponibles en el servidor |
| `skill.get` | `skill_name` | Skill completo con tools + instructions |
| `agent.whoami` | — | Rol actual, skill asignada, tools permitidas |

Esto permite que un agente, al conectarse, llame `agent.whoami` y sepa exactamente qué puede hacer.

---

## 7. Especificación del Servidor MCP

### Tools

#### Gestión del plan

| Tool | Input | Output | Roles permitidos |
|---|---|---|---|
| `plan.create` | `title`, `description`, `tasks[]` | `plan_id` | `architect` |
| `plan.get` | `plan_id` | `Plan` completo | Todos |
| `plan.list` | — | `Plan[]` activos | Todos |
| `plan.update` | `plan_id`, `status` | `Plan` actualizado | `architect` |

#### Gestión de tareas

| Tool | Input | Output | Roles permitidos |
|---|---|---|---|
| `task.create` | `plan_id`, `title`, `description` | `task_id` | `architect` |
| `task.list` | `status?`, `plan_id?` | `Task[]` | Todos |
| `task.claim` | `task_id`, `agent` | `Task` asignada | `developer` |
| `task.get` | `task_id` | `Task` completo | Todos |
| `task.submit_work` | `task_id`, `files[]`, `summary` | `submission_id` | `developer` |

#### Revisión

| Tool | Input | Output | Roles permitidos |
|---|---|---|---|
| `review.start` | `task_id` | `review_id` | `architect` |
| `review.approve` | `task_id`, `comment?` | status → `approved` | `architect` |
| `review.request_changes` | `task_id`, `changes[]` | status → `changes_requested` | `architect` |
| `review.get_history` | `task_id` | `Review[]` historial | Todos |

#### Chat

| Tool | Input | Output | Roles permitidos |
|---|---|---|---|
| `chat.send` | `text`, `target?`, `thread_id?` | `message_id` | Todos |
| `chat.read` | `thread_id?`, `since?`, `target?` | `Message[]` | Todos |
| `chat.thread_create` | `title`, `participants[]` | `thread_id` | Todos |
| `chat.thread_list` | — | `Thread[]` activos | Todos |

#### Presencia de agentes ← NUEVO

| Tool | Input | Output | Roles permitidos |
|---|---|---|---|
| `agent.heartbeat` | `agent_id`, `role?`, `status?` | `{ status, since }` | Todos |
| `agent.list` | — | `Agent[]` con estado | Todos |
| `agent.get` | `agent_id` | `Agent` completo | Todos |
| `agent.set_status` | `agent_id`, `status` | estado actualizado | El propio agente |

#### Skills ← NUEVO

| Tool | Input | Output | Roles permitidos |
|---|---|---|---|
| `skill.list` | — | `Skill[]` disponibles | Todos |
| `skill.get` | `skill_name` | Skill completo | Todos |
| `agent.whoami` | — | Rol + skill + tools permitidas | Todos |

**Routing de @menciones:**
- `@arquitecto` → el mensaje aparece en la inbox de Claude Code
- `@desarrollador` → el mensaje aparece en la inbox de OpenCode
- `@all` (o sin @) → mensaje público, visible en el chat

### Recursos (Resources)

| URI | Qué expone |
|---|---|
| `bridge://plan/{id}` | Plan completo en JSON |
| `bridge://task/{id}` | Tarea con estado, asignado, submission |
| `bridge://chat/thread/{id}` | Hilo de chat completo |
| `bridge://artifact/{plan_id}/{name}` | Archivos generados (specs, diffs) |
| `bridge://status` | Estado actual del sistema (planes, agentes, skills) |
| `bridge://agent/{id}` | Estado del agente (rol, status, last_seen) ← NUEVO |
| `bridge://skill/{name}` | Skill completa con tools y permisos ← NUEVO |

---

## 8. Sistema de Chat Compartido

### Cómo funciona

1. El humano abre la UI (TUI o web) que se conecta al mismo MCP Bridge Server
2. El humano escribe mensajes. Si usa `@arquitecto`, el server marca el mensaje como "para Claude Code". Si usa `@desarrollador", "para OpenCode". Si no usa @, es público.
3. Cada agente (cuando está en un ciclo de trabajo) llama `chat.read(since=ultimo_id)` y ve los mensajes nuevos
4. Si un mensaje está dirigido a ese agente, DEBE responder
5. La UI del humano se actualiza vía polling o SSE para mostrar los mensajes nuevos
6. **La UI también muestra el estado de cada agente** (online/busy/offline) ← NUEVO

### Visualización (TUI/Web)

```
┌──────────────────────────────────────────────────────┐
│  #general · Agent: 🟢 Arq · 🟡 Dev                  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [10:32] @humano: @arquitecto revisá la tarea #5     │
│                                                      │
│  [10:33] @arquitecto: Revisando. Veo que falta       │
│           manejo de errores en el middleware.         │
│           @desarrollador agregá try-catch.           │
│                                                      │
│  [10:34] @desarrollador: Ahí lo subo.               │
│                                                      │
│  [10:35] @arquitecto: ✅ Aprobado.                   │
│                                                      │
├──────────────────────────────────────────────────────┤
│ > [Escribí tu mensaje...]                       📎   │
└──────────────────────────────────────────────────────┘
```

### Threads de discusión

Cualquier participante puede crear un thread con `chat.thread_create`. Los threads tienen:
- Título
- Participantes (por defecto todos)
- Mensajes en orden
- Estado: `open` | `resolved`

Un thread se resuelve cuando el creador o el arquitecto lo cierra.

---

## 9. Flujo de Trabajo Completo

```
FASE 1: PLANIFICACIÓN (Arquitecto)
  │
  ├─ Arquitecto se identifica → agent.heartbeat(agent_id="claude-code-1", role="architect")
  ├─ Crea plan → plan.create()
  ├─ Define tareas con dependencias
  └─ Plan queda en estado "tasks_ready"
  
FASE 2: EJECUCIÓN (Desarrollador)
  │
  ├─ Desarrollador se identifica → agent.heartbeat(agent_id="opencode-1", role="developer")
  ├─ Lista tareas → task.list(status="pending")
  ├─ Claimea una → task.claim()
  ├─ Implementa en su terminal
  ├─ Sube resultados → task.submit_work()
  └─ Tarea pasa a "review"
  
FASE 3: REVISIÓN (Arquitecto)
  │
  ├─ Arquitecto revisa diff → task.get()
  ├─ ¿Aprueba? → review.approve() → tarea "approved"
  ├─ ¿Pide cambios? → review.request_changes() → "changes_requested"
  │     └─ Desarrollador corrige → vuelve a FASE 2
  └─ Si todo aprobado → plan.check_readiness()
  
FASE 4: INTERVENCIÓN HUMANA (en cualquier momento)
  │
  ├─ Humano checkea estado de agentes → agent.list()
  ├─ Si un agente está offline, el server lo informa
  └─ Humano escribe @arquitecto o @desarrollador en el chat
        └─ El agente recibe el mensaje en su inbox y responde
```

### Intervenciones del humano

| Situación | Acción del humano |
|---|---|
| El plan no refleja lo que quiere | `@arquitecto: cambiá la prioridad de la tarea X` |
| La implementación tiene un error | `@desarrollador: en la tarea Y, fijate que falta validación` |
| Los dos están discutiendo un approach | `@all: usamos la opción B, punto` |
| Quiere跟进 el progreso | Lee el plan con `plan.get()` desde la UI |
| Quiere ver quién está conectado | `agent.list()` en la UI |

---

## 10. Protocolo de Discusión Autónoma (Fase 2)

Esto NO es para el MVP. Se documenta acá para que la arquitectura lo soporte desde el día 1.

### Mecanismo

1. El humano (o un agente) crea un thread con `chat.thread_create(título, participantes=[ambos])`
2. El server le asigna a cada participante: "Deben discutir hasta llegar a una conclusión"
3. Cada agente, cuando está en un ciclo de trabajo, revisa sus threads abiertos
4. Si un thread requiere su participación, envía su postura
5. El server trackea: quién dijo qué, en qué orden
6. Un thread termina cuando:
   - Hay consenso explícito (ambos escriben "de acuerdo" o similar)
   - El humano interviene y cierra el thread
   - Timeout (configurable)

### Precondiciones para que funcione

- Ambos agentes deben tener en su system prompt que **revisen threads activos** periódicamente
- El server debe exponer `chat.thread_get_pending(agent_name)` para que el agente sepa qué threads requieren su atención
- Debe haber un mecanismo de **turn-taking** para que no hablen al mismo tiempo (básicamente: el server alterna "ahora habla X")

### Riesgo conocido

Si los dos agentes se envían mensajes en un loop sin llegar a nada, es un problema. Por eso la **intervención humana debe ser posible en cualquier momento** y el timeout debe ser agresivo (ej: 5 minutos sin actividad cierra el thread).

---

## 11. Plan de Trabajo

### Fase 0: Fundación (Día 1-2) ✅ COMPLETADA

- [x] Inicializar proyecto Python con `uv`
- [x] Agregar dependencias: `mcp` SDK, `filelock`, `aiosqlite`, `textual`
- [x] Estructura de directorios
- [x] Esqueleto del servidor MCP con hello-world tool
- [x] Verificar que tanto Claude Code como OpenCode pueden conectarse

### Fase 1: Core State Machine (Día 3-5) ✅ COMPLETADA

- [x] Modelos de datos: Plan, Task, Message, Review, Thread
- [x] Esquema SQLite + migraciones
- [x] State machine: transiciones entre estados, validaciones
- [x] File locks para operaciones críticas (claim, submit)
- [x] 29 tests de la state machine

### Fase 2: Presencia, Configuración y Skills ← RECORTADA Y PRIORIZADA

- [ ] `agent.heartbeat`, `agent.list`, `agent.get`, `agent.set_status`
- [ ] Modelo de sesiones + timeouts de presencia en SQLite
- [ ] Archivo `bridge.json` + comando `agent-bridge configure`
- [ ] Resolución de rol por agent_id/match
- [ ] Formato de Skill + skills built-in (architect, developer)
- [ ] Permission layer: validar tool llamada vs allowed_tools del skill
- [ ] `skill.list`, `skill.get`, `agent.whoami`
- [ ] Tests de presencia, configuración y permisos

### Fase 3: Tools MCP del flujo de trabajo (Día 11-14)

- [ ] Refinar `plan.*`, `task.*`, `review.*` con permisos del skill
- [ ] `task.get_diff`
- [ ] Tests de integración con MCP SDK

### Fase 4: Chat y @menciones (Día 15-18) ✅ COMPLETADA

- [x] `chat.send`, `chat.read`, `chat.thread_create`, `chat.thread_list`
- [x] Routing de @menciones con verificación de presencia
- [x] UI TUI básica con Textual (panel de chat + estado de agentes)
- [x] La UI se conecta al mismo MCP server vía stdio subprocess
- [x] Auto-refresh de mensajes nuevos + estado de agentes (cada 5s)
- [x] Tests del sistema de chat (13 tests)

### Fase 5: Workflow integrado (Día 19-22) ✅ COMPLETADA

- [x] Script de inicio: `agent-bridge start` (SSE + TUI, --headless, --ui-only)
- [x] Prueba real validada: test_integration.py cubre plan → task → claim → submit → review → approve
- [x] Manejo de errores: try/catch en todas las tools, errores estructurados con request_id
- [x] Reconexión automática: exponential backoff en la TUI (1s→30s max)
- [x] Reasignación de tareas: background loop cada 60s, stale agents → offline, tasks → pending
- [x] Structured logging: request_id, tool name, agent_id, duration en cada llamada
- [x] README completo con arquitectura, instalación, configuración, uso y desarrollo

### Fase 6: Robustez y DX (Día 23-26) ✅ COMPLETADA

- [x] Modo `--dry-run`: Database wrapper que intercepta writes (loggea en vez de ejecutar)
- [x] Comando `reset` con confirmación y `--force` para borrar todo el estado
- [x] Export/Import de planes: tools MCP `plan.export` + `plan.import` + CLI commands
- [x] Edge cases tests: 5 tests de concurrencia (claim, review, submit)
- [x] Stress test: 10 agents, 5 tasks, claims concurrentes — SQL atómico garantiza integridad
- [x] README actualizado con dry-run, reset, export, import

### Fase 7: Discusión autónoma (Futuro, post-MVP)

- [ ] `chat.thread_get_pending(agent_name)` para que los agentes sepan qué threads requieren atención
- [ ] Turn-taking en threads
- [ ] Timeout y resolución automática
- [ ] Tests de loops de discusión

---

## 12. Criterios de éxito

El proyecto está en el camino correcto cuando:

1. [ ] Un humano puede ver el chat compartido y escribir `@arquitecto: hacé un plan para X`
2. [ ] El server sabe si Claude Code y OpenCode están online/offline
3. [ ] Si un agente está offline, el server no le envía mensajes y avisa al humano
4. [ ] Claude Code recibe el mensaje, crea el plan, y las tareas aparecen en el broker
5. [ ] OpenCode ve las tareas pendientes, claimea una, implementa, y sube el resultado
6. [ ] Claude Code revisa, pide cambios, OpenCode corrige
7. [ ] Claude Code aprueba
8. [ ] En todo momento el humano puede intervenir con `@desarrollador: pará, hacelo distinto`
9. [ ] Si un agente intenta usar una tool que no le corresponde, el server lo rechaza con un error claro
10. [ ] La configuración de roles se puede cambiar sin modificar código (editando `bridge.json`)
11. [ ] Si un agente se cierra y vuelve a abrirse, retoma donde dejó sin perder estado
12. [ ] Dos sesiones separadas no se pisan entre sí (aislamiento por plan activo)

---

## 13. Anti-patterns y riesgos

| Riesgo | Mitigación |
|---|---|
| Dos agentes claiman la misma tarea | File locks + validación en SQLite (transacción atómica) |
| Loop infinito de cambios | Máximo 3 ciclos review → changes → review, luego escalar al humano |
| Agente no responde | Timeout de presencia (90s away, 300s offline). Reasignación de tareas |
| Estado corrupto en SQLite | WAL mode + backups periódicos del archivo `.db` |
| @menciones no llegan por el agente está ocupado | Inbox persistente. El agente ve los mensajes en su próximo heartbeat |
| Agente no identificado (sin heartbeat) | Fallback a rol `default` con permisos mínimos (solo chat) |
| Skills mal configuradas | Validación al cargar `bridge.json`. Error claro si falta un skill |
| Dependencia entre tareas mal definida | Detección de ciclos en `plan.create` |
| Dos terminales con el mismo agent_id | El segundo heartbeat rechazado con error "agent_id ya conectado" |

---

*Este documento es vivo. Se actualiza a medida que evolucionamos el proyecto. Cualquier cambio significativo se discute antes de aplicarlo.*

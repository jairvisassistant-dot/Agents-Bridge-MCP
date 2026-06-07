# Agent Bridge — MCP Broker + Kanban TUI

> **Documento rector único.** Esto es lo que estamos construyendo. Cualquier otro documento anterior debe considerarse obsoleto.
>
> Estado: **vivo** — se actualiza cuando el proyecto cambia.

---

## Índice

- [1. ¿Qué estamos construyendo?](#1-qué-estamos-construyendo)
- [2. Stack tecnológico](#2-stack-tecnológico)
- [3. Arquitectura](#3-arquitectura)
- [4. Kanban TUI — La interfaz del supervisor](#4-kanban-tui--la-interfaz-del-supervisor)
  - [Layout actual](#layout-actual)
  - [Atajos de teclado](#atajos-de-teclado)
  - [Flujo de trabajo del humano](#flujo-de-trabajo-del-humano)
- [5. Servidor MCP — Tools para agentes](#5-servidor-mcp--tools-para-agentes)
  - [Tools de plan](#tools-de-plan)
  - [Tools de tarea](#tools-de-tarea)
  - [Tools de revisión](#tools-de-revisión)
  - [Tools de chat](#tools-de-chat)
  - [Tools de agente](#tools-de-agente)
  - [Tools de skills](#tools-de-skills)
  - [Permisos por rol](#permisos-por-rol)
- [6. Instalación y uso](#6-instalación-y-uso)
  - [Instalación](#instalación)
  - [Comandos](#comandos)
  - [Flujo típico de trabajo](#flujo-típico-de-trabajo)
- [7. Estado actual del proyecto](#7-estado-actual-del-proyecto)
  - [Implementado](#implementado)
  - [Pendiente próximo release](#pendiente-próximo-release)
  - [38 tools MCP — estado](#38-tools-mcp--estado)
- [8. Roadmap](#8-roadmap)
- [9. Anti-patterns y riesgos](#9-anti-patterns-y-riesgos)

---

## 1. ¿Qué estamos construyendo?

Un **MCP Broker** con **Kanban TUI** que conecta agentes de IA (Claude Code, OpenCode) con un **supervisor humano**.

El humano es el centro. El Kanban es su herramienta para:

- Crear, editar, eliminar y asignar tareas
- Monitorear el progreso en tiempo real
- Comunicarse con los agentes vía chat integrado
- Dirigir el flujo de trabajo sin estar "por fuera"

Los agentes se conectan al broker vía MCP, ven las tareas, las toman, implementan, y las devuelven para revisión. Pero **quien define el rumbo es el humano desde el Kanban**.

### El problema que resuelve

Hoy, si querés que Claude Code planifique y OpenCode implemente, tenés que copiar y pegar manualmente entre terminales. No hay trazabilidad, no hay estado compartido, no hay forma de que el humano intervenga sin romper el flujo.

### La solución

| Componente | Qué hace |
|---|---|
| **Kanban TUI** | Interfaz del humano. CRUD de tareas, asignación, chat integrado, monitoreo en vivo |
| **Servidor MCP** | Backend que exponen tools para que los agentes interactúen con las tareas |
| **SQLite** | Estado compartido. Tanto el Kanban como los agentes leen/escriben a la misma DB |
| **Agentes** | Claude Code (arquitecto) y OpenCode (desarrollador) se conectan vía MCP |

---

## 2. Stack tecnológico

| Capa | Tecnología | Por qué |
|---|---|---|
| Lenguaje | Python 3.12+ | MCP SDK maduro, async-first |
| TUI | Textual 8.x | Framework moderno, reactivo, modal screens |
| Estado | SQLite + WAL | Cero dependencias, transaccional, `PRAGMA data_version` para detectar cambios |
| MCP SDK | `mcp` (Python oficial) | Protocolo estándar, ambos agentes lo soportan |
| Transporte | stdio + SSE | stdio para desarrollo local, SSE para agentes remotos |
| Concurrencia | `threading.RLock` + `BEGIN IMMEDIATE` | Writes serializados, lectores concurrentes |
| Configuración | `bridge.json` + CLI `configure` | Editable por el humano |
| Paquete | `uv` + `pyproject.toml` | Build system moderno, deterministico |
| Tests | pytest + pytest-asyncio | ~239 tests |

---

## 3. Arquitectura

```
                    ┌──────────────────────────────────────┐
                    │         KANBAN TUI (Textual)          │
                    │  ┌──────────┐  ┌──────────────────┐  │
                    │  │ TaskList │  │  TaskDetail       │  │
                    │  │ (↑↓)     │  │  (contextual)     │  │
                    │  └──────────┘  └──────────────────┘  │
                    │  ┌──────────────────────────────────┐ │
                    │  │  Chat integrado (persistente)    │ │ ← EL HUMANO
                    │  │  • @menciones                    │ │
                    │  │  • Contextual por tarea          │ │
                    │  │  • Estado de agentes             │ │
                    │  └──────────────────────────────────┘ │
                    │  Header · Summary · Footer (N M K Q) │
                    └──────────────┬───────────────────────-┘
                                   │ TuiBridge (in-process)
                    ┌──────────────▼────────────────────────┐
                    │         SQLite (estado compartido)     │
                    │  ┌──────────────────────────────────┐ │
                    │  │ tasks · plans · messages · agents│ │
                    │  │ reviews · threads · ping_requests│ │
                    │  └──────────────────────────────────┘ │
                    └──────┬──────────────┬─────────────────┘
                           │              │
              ┌────────────▼─────┐  ┌─────▼──────────────┐
              │  Claude Code     │  │  OpenCode           │
              │  Rol: Arquitecto │  │  Rol: Desarrollador │
              │  vía MCP stdio   │  │  vía MCP stdio/SSE  │
              │  o SSE           │  │                     │
              └──────────────────┘  └─────────────────────┘
```

### Flujo de datos

1. **Kanban TUI** se conecta a la DB directamente (TuiBridge in-process). Lee/escribe tareas, mensajes, agentes.
2. **Agentes** se conectan al servidor MCP (stdio o SSE). El servidor expone tools que leen/escriben la misma DB.
3. **DBWatcher** en el Kanban hace `PRAGMA data_version` cada 1.5s. Cuando un agente cambia algo, el Kanban se entera y refresca.
4. **Chat**: los mensajes del humano van a la DB. Los agentes leen con `chat.read` y responden.

---

## 4. Kanban TUI — La interfaz del supervisor

### Layout actual

```
┌──────────────────────────────────────────────────────────┐
│ 🔷 Agents-Bridge-MCP  │  🟢 0/0 agentes  │  💬 0 msgs  │  ← Header
├──────────────────────────────────────────────────────────┤
│ 📊 0 tareas · 0 pendientes · 0 en progreso · 0 revisión │  ← Summary
├──────────────────────┬───────────────────────────────────┤
│ TaskList             │  TaskDetail                      │
│ (↑↓ navegación)      │  (contextual a selección)        │
│                      │                                   │
│ ● #1 Título tarea    │  Título completo                  │
│    📋 Pendiente      │  Descripción                      │
│    Asig: Arq         │  Estado, Asignado, Plan, Fechas   │
│                      │                                   │
├──────────────────────┴───────────────────────────────────┤
│ [N] Nueva  [M] Mover  [D] Detalle  [K] Chat  [Q] Salir  │  ← Footer
└──────────────────────────────────────────────────────────┘
```

### Atajos de teclado

| Tecla | Acción | Estado |
|---|---|---|
| ↑ / ↓ | Navegar entre tareas | ✅ |
| **N** | Crear tarea (modal con título, descripción, plan) | ✅ |
| **M** | Mover tarea de estado (con validación de state machine) | ✅ |
| D | Detalle completo (panel derecho ya muestra info) | ✅ |
| **K** | Abrir chat (contextual a la tarea seleccionada) | ✅ |
| R | Refrescar manual | ✅ |
| Q | Salir | ✅ |

### Integración con el chat

El chat se abre con `K` como overlay modal. Cuando hay una tarea seleccionada, el chat se contextualiza a esa tarea (filtra mensajes por `thread_id = task.id`, el placeholder sugiere `@asignado`). Sin tarea seleccionada, muestra el chat general.

**Próximo release**: el chat debe ser persistente (no modal), visible siempre en la parte inferior del kanban.

---

## 5. Servidor MCP — Tools para agentes

### State machine

Todas las transiciones de estado se validan contra una máquina de estados
centralizada en `state_machine.py` antes de escribir en la DB.

```
Plan:     idle → planning → tasks_ready → in_progress → completed
          └─→ archived (terminal, soft-delete)

Task:     pending → in_progress → review → approved
                                    ↓
                              changes_requested → review

Review:   pending → in_review → approved / changes_requested

Thread:   open → resolved
```

Estados terminales: `completed`, `archived` (plan), `approved` (task/review),
`resolved` (thread).

### Tools de plan

| Tool | Input | Output | Roles |
|---|---|---|---|
| `plan.create` | title, description, tasks[] | plan_id | architect |
| `plan.get` | plan_id | Plan completo | todos |
| `plan.list` | — | Plan[] activos | todos |
| `plan.update` | plan_id, status | Plan actualizado | architect |
| `plan.export` | plan_id | JSON exportable | todos |
| `plan.import` | plan_data | plan_id | architect |
| `plan.archive` | plan_id | archivado | architect |
| `plan.delete` | plan_id | borrado | architect |

### Tools de tarea

| Tool | Input | Output | Roles |
|---|---|---|---|
| `task.create` | plan_id, title, description | task_id | architect |
| `task.list` | status?, plan_id? | Task[] | todos |
| `task.get` | task_id | Task completo | todos |
| `task.claim` | task_id, agent | Task asignada | developer |
| `task.submit_work` | task_id, files[], summary | submission_id | developer |
| `task.get_diff` | task_id | diff del trabajo | todos |
| `task.update` | task_id, title?, description? | actualizado | todos |
| `task.delete` | task_id | borrado | todos |

### Tools de revisión

| Tool | Input | Output | Roles |
|---|---|---|---|
| `review.start` | task_id | review_id | architect |
| `review.approve` | task_id, comment? | approved | architect |
| `review.request_changes` | task_id, changes[] | changes_requested | architect |
| `review.get_history` | task_id | Review[] historial | todos |

### Tools de chat

| Tool | Input | Output | Roles |
|---|---|---|---|
| `chat.send` | text, target?, thread_id?, msg_type?, priority? | message_id | todos |
| `chat.read` | since?, limit?, thread_id?, target?, msg_type?, unread_only?, priority_first? | Message[] | todos |
| `chat.thread_create` | title, participants[] | thread_id | todos |
| `chat.thread_list` | — | Thread[] activos | todos |
| `chat.thread_get_pending` | agent_name | threads pendientes | todos |
| `chat.mark_read` | message_id | OK | todos |

### Tools de agente

| Tool | Input | Output | Roles |
|---|---|---|---|
| `agent.heartbeat` | agent_id, role?, status? | { status, since } | todos |
| `agent.list` | — | Agent[] con estado | todos |
| `agent.get` | agent_id | Agent completo | todos |
| `agent.set_status` | agent_id, status | actualizado | propio agente |
| `agent.ping` | target_agent_id, timeout_seconds? | { status, latency_ms } | todos |
| `agent.pong` | ping_id | { status, latency_ms } | todos |
| `agent.idle` | reason? | confirmación | todos |
| `agent.whoami` | — | Rol + skill + tools permitidas | todos |

### Tools de skills

| Tool | Input | Output |
|---|---|---|
| `skill.list` | — | Skill[] disponibles |
| `skill.get` | skill_name | Skill completo |

### Permisos por rol

| Tool | architect | developer |
|---|---|---|
| plan.create, plan.update, plan.archive, plan.delete | ✅ | ❌ |
| plan.import | ✅ | ❌ |
| plan.get, plan.list, plan.export | ✅ | ✅ |
| task.create | ✅ | ❌ |
| task.claim, task.submit_work | ❌ | ✅ |
| task.list, task.get, task.update, task.delete | ✅ | ✅ |
| review.start, review.approve, review.request_changes | ✅ | ❌ |
| review.get_history | ✅ | ✅ |
| chat.* | ✅ | ✅ |
| agent.* | ✅ | ✅ |
| skill.* | ✅ | ✅ |

---

## 6. Instalación y uso

### Instalación

```bash
# Clonar e instalar
git clone <repo>
cd Agents-Bridge-MCP
uv sync

# Inicializar configuración
agent-bridge configure --init

# Ver/editar configuración
agent-bridge configure --list
agent-bridge configure --set agent=claude-code-1 role=architect
```

### Comandos

```bash
# Kanban TUI + servidor SSE (stack completo recomendado)
agent-bridge kanban

# Solo kanban (sin servidor, para cuando el server ya corre)
agent-bridge start --kanban --ui-only

# Solo servidor (para que los agentes se conecten)
agent-bridge start --headless --port 8765

# Modo dry-run (base en memoria, nada persiste)
agent-bridge kanban --dry-run

# Resetear la base de datos
agent-bridge reset --force
```

### Flujo típico de trabajo

```
1. El humano abre el Kanban → agent-bridge kanban
2. Crea tareas con N, las asigna a agentes (próximo release)
3. Los agentes ven las tareas vía MCP:
   - Arquitecto: task.list → review.approve
   - Desarrollador: task.list → task.claim → task.submit_work
4. El humano monitorea el progreso en el Kanban (auto-refresh cada 1.5s)
5. El humano chatea con los agentes con K (contextual a cada tarea)
6. El humano mueve tareas de estado con M si es necesario
```

---

## 7. Estado actual del proyecto

### Implementado

| Feature | Estado | Tests |
|---|---|---|
| Core state machine (plan → tasks → in_progress → review → approved) | ✅ Completo | 29 |
| Tools plan.* (CRUD + export/import/archive/delete) | ✅ Completo | |
| Tools task.* (CRUD + claim + submit_work + get_diff) | ✅ Completo | |
| Tools review.* (start/approve/request_changes/get_history) | ✅ Completo | |
| Tools chat.* (send/read/threads/@menciones/mark_read/msg_type/priority) | ✅ Completo | 30 |
| Tools agent.* (heartbeat/list/get/set_status/ping/pong/idle/whoami) | ✅ Completo | |
| Tools skill.* (list/get) | ✅ Completo | |
| Permission layer (role-based allowed_tools) | ✅ Completo | |
| Skills built-in (architect + developer + templates) | ✅ Completo | |
| Configuración bridge.json + CLI configure | ✅ Completo | |
| Presencia de agentes (heartbeat 30s, away 90s, offline 300s) | ✅ Completo | |
| Reasignación automática de tareas por stale agent | ✅ Completo | |
| Sistema de ping (challenge-response con latencia) | ✅ Completo | |
| Mensajería tipada (msg_type, priority, read tracking) | ✅ Completo | |
| Notificaciones automáticas server-side (status_update, dependency) | ✅ Completo | |
| Protocolo shutdown (request → approve) | ✅ Completo | |
| agent.idle (señal de disponibilidad) | ✅ Completo | |
| Discusión autónoma (threads con turn-taking, timeout, resolución) | ✅ Completo | 16 |
| Dry-run (base en memoria) | ✅ Completo | |
| Kanban TUI: navegación, crear tarea, mover estado | ✅ Completo | 46 |
| Kanban TUI: chat overlay contextual, DBWatcher, auto-refresh | ✅ Completo | |
| Tests | 239 tests, todos pasan | 239 |
| Lint | ruff 0 errors | |
| Schema DB v7 | migraciones 1→7 | |

### Pendiente próximo release

| Feature | Prioridad |
|---|---|
| **Editar tarea desde el Kanban** (existe MCP tool `task.update`, falta binding en TUI) | Alta |
| **Eliminar tarea desde el Kanban** (existe MCP tool `task.delete`, falta binding en TUI) | Alta |
| **Asignar tarea a un agente desde el Kanban** (existe `task.claim`, falta binding en TUI) | Alta |
| **Chat persistente** (hoy es modal overlay, debe ser panel fijo) | Alta |
| **Externalizar skill templates** de `main.py` a archivos `.Skill` | Media |
| **Paginación en chat.read** (limit/offset) | Media |
| Tests de integración faltantes (SSE, dry-run e2e, payloads grandes, TUI mock) | Media |

### 38 tools MCP — estado

30 de 38 tools están completas (79%). 8 tienen bugs de borde no críticos (21%):
- State machine decorativa para 4/5 operaciones de cambio de estado (el enforcement real está en condiciones SQL distribuidas)
- plan.archive fuera de state machine
- task.create sin validar plan.status
- F-strings JSON (ya corregidos en fases anteriores)
- Thresholds de stale agent alineados (ya corregidos)

---

## 8. Roadmap

### Inmediato (próximo release)

1. **Kanban: full CRUD + asignación**
   - Agregar `E` → editar tarea (modal con título + descripción)
   - Agregar `Supr` → eliminar tarea (con confirmación)
   - Agregar `A` → asignar tarea a agente (selector de agentes disponibles)
   - MCP tool `task.assign` si no existe suficiente

2. **Chat persistente**
   - Convertir chat de modal overlay a panel fijo inferior
   - Que ocupe ~30% del alto de la terminal
   - Que mantenga el contexto de la tarea seleccionada

3. **Documentación única**
   - Este documento es el rector. Borrar docs anteriores.

### Corto plazo

- Externalizar skill templates a archivos `.Skill`
- Paginación en `chat.read`
- Tests de integración para SSE, dry-run e2e, payloads grandes

### Mediano plazo

- Soporte multi-plan en el Kanban (selector de plan activo)
- Histórico de actividad por tarea
- Filtros en la lista de tareas (por estado, agente, plan)

---

## 9. Anti-patterns y riesgos

| Riesgo | Mitigación |
|---|---|
| Dos agentes claiman la misma tarea | SQL transaccional + `WHERE status='pending'` evita doble claim |
| Loop infinito de cambios | Máximo 3 ciclos review → changes → review, luego escalar al humano |
| Agente no responde | Timeout: 90s away, 300s offline. Reasignación automática de tareas |
| Estado corrupto en SQLite | WAL mode + BEGIN IMMEDIATE + RLock |
| @menciones no llegan | Inbox persistente. El agente ve mensajes en su próximo heartbeat |
| Skills mal configuradas | Validación al cargar bridge.json |
| Dependencia circular entre tareas | Detección de ciclos en plan.create |
| TUI y servidor MCP compiten por la DB | TuiBridge + DBWatcher. Ambos usan RLock. Sin corrupción. |

---

*Este documento es la única fuente de verdad del proyecto. Cualquier documento anterior en `/Recursos/` o fuera de este archivo debe considerarse obsoleto.*

*Actualizado: 2026-06-07*

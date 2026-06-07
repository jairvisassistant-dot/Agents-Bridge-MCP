# Plan de Mejoras — Agent Bridge MCP
> **Documento de ejecución para el Desarrollador.**
> Cada tarea tiene criterios de aceptación verificables. No avanzar a la siguiente sin completar la anterior dentro del mismo módulo.

---

## Contexto

Este plan consolida dos ciclos de análisis:

1. **Análisis interno** — bugs y fragilidades detectados en la arquitectura existente del proyecto.
2. **Análisis comparativo** — revisión del código fuente real de:
   - `cs50victor/claude-code-teams-mcp` — sistema de inbox tipado con Pydantic
   - `rinadelph/Agent-MCP` — mensajería con prioridades, tipos y entrega dual
   - `mattes337/AgentCommunicationMcp` — dispatch server-side por tipo de mensaje

El objetivo es fortalecer la capa de comunicación entre agentes sin romper la arquitectura existente.

---

## Estado Actual — Resumen de Deuda Técnica

| Problema | Severidad | Referencia |
|---|---|---|
| `removeAllListeners(event)` ignorado en `EventBus` del PomodoroTimer | Alta | `src/core/EventBus.js:76 vs :101` |
| Race condition en inicialización async de `TimerController` | Media | `PomodoroApp.js` |
| Mensajes sin tipo ni prioridad — texto libre sin schema | Media | `messages` table |
| `read` tracking por posición (`since`) — frágil ante saltos | Media | `chat.read` |
| Cero tests en el proyecto PomodoroTimer | Alta | `package.json` |
| Sin límite de tamaño en mensajes | Baja | `chat.send` |

---

## Fase 1 — Sistema de Ping de Conectividad
> **Estado**: Tareas creadas en bridge DB. Plan ID: `ebd1bf27`

Reemplaza la detección por `last_seen` con confirmación activa challenge-response.

### Tarea 1.1 — Migración DB: tabla `ping_requests`
**ID bridge**: `d9a5272b` | **Prioridad**: Bloqueante para 1.2

**Archivos**: `src/agent_bridge/state/database.py`

**Schema a agregar en `SCHEMA_SQL`**:
```sql
CREATE TABLE IF NOT EXISTS ping_requests (
    id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    pong_at TEXT,
    latency_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'  -- pending | pong | timeout
);
```

**Métodos a agregar en clase `Database`**:
```python
async def create_ping_request(self, sender_id: str, target_id: str) -> str
async def record_pong(self, ping_id: str) -> int          # retorna latency_ms
async def get_ping_request(self, ping_id: str) -> dict | None
```

**`SCHEMA_VERSION`**: bumper de 4 → 5

**Criterios de aceptación**:
- [ ] Tabla aparece en el schema SQL
- [ ] `SCHEMA_VERSION = 5` con migración vacía (CREATE IF NOT EXISTS maneja la tabla nueva)
- [ ] Los tres métodos async están implementados
- [ ] `latency_ms` calculado como diferencia entre `pong_at` y `sent_at`
- [ ] Verificación: `python -c "import asyncio; from agent_bridge.state.database import Database; asyncio.run(Database(':memory:').initialize())"` sin errores

---

### Tarea 1.2 — Implementar tools `agent.ping` y `agent.pong`
**ID bridge**: `898924ef` | **Depende de**: 1.1

**Archivos**: `src/agent_bridge/tools/agents.py`

**Tool `agent.ping`**:
```python
types.Tool(
    name="agent.ping",
    description="Send a connectivity ping to a specific agent and wait for their pong.",
    inputSchema={
        "type": "object",
        "properties": {
            "target_agent_id": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 10},
        },
        "required": ["target_agent_id"],
    },
)
```

**Lógica de `agent.ping`**:
1. `ping_id = await db.create_ping_request(sender_id, target_id)`
2. `await db.execute(INSERT INTO messages ...)` con `text = json.dumps({"type": "ping", "ping_id": ping_id, "from": sender_id})`
3. Loop `asyncio.sleep(0.5)` hasta timeout
4. Si llega pong → retornar `{status: "pong", latency_ms, target_agent_id}`
5. Si timeout → `UPDATE ping_requests SET status='timeout'` + retornar `{status: "timeout", last_seen}`

**Tool `agent.pong`**:
```python
types.Tool(name="agent.pong", ...)
# Lógica: latency_ms = await db.record_pong(ping_id)
```

**Criterios de aceptación**:
- [ ] Ambas tools en `AGENT_TOOLS`
- [ ] `handle_agent_tool` despacha ambas
- [ ] Polling cada 0.5s hasta timeout
- [ ] En timeout: retorna `last_seen` del agente

---

### Tarea 1.3 — Registrar tools y actualizar permisos
**ID bridge**: `765edb99` | **Depende de**: 1.2

**Archivos**: `bridge.json`

Verificar que `AGENT_TOOLS` ya incluye las tools nuevas (si 1.2 las agregó a la lista, `server.py` no necesita cambios).

Agregar en `bridge.json` a `allowed_tools` de `architect` y `developer`:
```json
"agent.ping", "agent.pong"
```

**Criterios de aceptación**:
- [ ] Ambas tools en `allowed_tools` de ambos roles
- [ ] Un agente con rol `architect` no recibe `permission_denied` al llamar `agent.ping`

---

### Tarea 1.4 — Protocolo de pong en Skills
**ID bridge**: `bdaad8a3` | **Depende de**: 1.3

**Archivos**: `.agentes/architect.Skill`, `.agentes/dev.Skill`, `src/agent_bridge/main.py` (SKILL_TEMPLATES)

Agregar en sección **"Protocolo de comunicación en TUI"** de ambas skills:

```markdown
### Protocolo de respuesta a ping

Cuando `chat.read` retorne mensajes, revisar si alguno tiene `text` que sea
JSON con `"type": "ping"`:

1. Parsear el `ping_id`
2. Llamar inmediatamente: `agent.pong(ping_id="{ping_id}")`
3. NO publicar en el chat — el pong va directo a la DB
4. Continuar con el procesamiento normal
```

**Criterios de aceptación**:
- [ ] Sección presente en ambos archivos `.Skill`
- [ ] Mismo contenido en `SKILL_TEMPLATES` dentro de `main.py`

---

## Fase 2 — Capa de Mensajería Mejorada
> **Estado**: Pendiente. Iniciar después de que Fase 1 esté completa y aprobada.

Basado en lo aprendido de los tres repos analizados. El cambio más impactante: agregar semántica al sistema de mensajes actual que usa texto libre sin schema.

---

### Tarea 2.1 — Migración DB: tipo, prioridad y lectura por mensaje
**Depende de**: Fase 1 completa | **SCHEMA_VERSION**: 6

**Archivos**: `src/agent_bridge/state/database.py`

**Migración a agregar en `_run_migrations`**:
```python
if from_version < 6:
    conn.execute("ALTER TABLE messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'chat'")
    conn.execute("ALTER TABLE messages ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
    conn.execute("ALTER TABLE messages ADD COLUMN read INTEGER NOT NULL DEFAULT 0")
    logger.info("Migration v5→v6: added msg_type, priority, read to messages")
```

**Tipos válidos para `msg_type`**:
```
chat | task_assignment | status_update | dependency_notification |
idle_notification | shutdown_request | shutdown_approved | system | ping
```

**Prioridades válidas**: `normal | high | urgent`

**Métodos nuevos en `Database`**:
```python
async def mark_message_read(self, message_id: str) -> None
async def get_unread_count(self, target: str) -> int
```

**Criterios de aceptación**:
- [ ] `SCHEMA_VERSION = 6`
- [ ] Las tres columnas existen en la tabla `messages`
- [ ] Registros existentes tienen defaults correctos (`chat`, `normal`, `0`)
- [ ] Métodos `mark_message_read` y `get_unread_count` implementados

---

### Tarea 2.2 — Actualizar `chat.send` y `chat.read` con el nuevo schema
**Depende de**: 2.1

**Archivos**: `src/agent_bridge/tools/chat.py`

**Cambios en `chat.send`**:
- Agregar parámetros opcionales al `inputSchema`: `msg_type` (default `"chat"`), `priority` (default `"normal"`)
- Agregar validación: si `msg_type` no está en la lista válida → error descriptivo
- Agregar limit de tamaño: si `len(text) > 4000` → error `message_too_long`
- Pasar `msg_type` y `priority` al INSERT de la tabla `messages`

**Cambios en `chat.read`**:
- Agregar parámetros opcionales al `inputSchema`: `msg_type` (filtro por tipo), `unread_only` (bool, default `False`), `priority_first` (bool, default `False`)
- Si `unread_only=True` → agregar `AND read = 0` al WHERE
- Si `msg_type` está presente → agregar `AND msg_type = ?`
- Si `priority_first=True` → ORDER BY `CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, created_at ASC`
- Cuando se leen mensajes → ejecutar `mark_message_read` para cada uno retornado

**Nuevo tool `chat.mark_read`**:
```python
types.Tool(
    name="chat.mark_read",
    description="Mark a specific message as read.",
    inputSchema={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
        },
        "required": ["message_id"],
    },
)
```

**Criterios de aceptación**:
- [ ] `chat.send` acepta `msg_type` y `priority` sin romper callers existentes (son opcionales)
- [ ] `chat.send` rechaza mensajes > 4000 chars con error estructurado
- [ ] `chat.read` con `unread_only=True` retorna solo no leídos
- [ ] `chat.read` con `priority_first=True` muestra urgentes primero
- [ ] `chat.mark_read` funciona independientemente
- [ ] Tests: verificar que los filtros funcionan correctamente

---

### Tarea 2.3 — Notificaciones automáticas server-side
**Depende de**: 2.2

**Archivos**: `src/agent_bridge/server.py`

Extender `_maintenance_loop` (o crear helper `_send_system_notification`) para enviar mensajes tipados automáticamente cuando cambia el estado de tareas.

**Casos a implementar**:

| Evento | Tipo de mensaje | Destinatario | Prioridad |
|---|---|---|---|
| Tarea → `approved` | `status_update` | dev (assignee) | `high` |
| Tarea `approved` desbloquea dependencias | `dependency_notification` | dev | `high` |
| Tarea → `changes_requested` | `status_update` | dev (assignee) | `high` |
| Tarea → `review` (submit_work) | `status_update` | arquitecto | `normal` |

**Helper a crear**:
```python
async def _send_system_notification(
    db: Database,
    target: str,
    text: str,
    msg_type: str,
    priority: str = "normal",
) -> None:
    await db.execute(
        "INSERT INTO messages (id, sender, target, text, msg_type, priority) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), "system", target, text, msg_type, priority),
    )
```

**Cuándo disparar**: dentro del handler de `task.submit_work` (review) y `review.approve` / `review.request_changes`. No en el maintenance_loop — disparar inline cuando ocurre el evento.

**Criterios de aceptación**:
- [ ] Cuando `review.approve` se llama → dev recibe mensaje `status_update` automático con `priority="high"`
- [ ] Cuando `review.request_changes` se llama → dev recibe mensaje `status_update` automático
- [ ] Cuando `task.submit_work` se llama → arquitecto recibe mensaje `status_update`
- [ ] Los mensajes tienen `sender="system"` y se distinguen visualmente en TUI
- [ ] No rompe el flujo existente si el dev/arquitecto no está online

---

### Tarea 2.4 — `agent.idle`: señal de disponibilidad
**Depende de**: 2.2

**Archivos**: `src/agent_bridge/tools/agents.py`

**Problema que resuelve**: el arquitecto no sabe cuándo el dev terminó una tarea y está libre para tomar otra. Actualmente el dev lo anuncia manualmente en el chat.

**Nueva tool `agent.idle`**:
```python
types.Tool(
    name="agent.idle",
    description="Signal that this agent is idle and ready for new work.",
    inputSchema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Context for availability (e.g. 'task completed', 'waiting for review')",
                "default": "available",
            },
        },
    },
)
```

**Lógica**:
1. `UPDATE agents SET status = 'online'` (salir de busy)
2. `INSERT INTO messages` con `msg_type = 'idle_notification'`, `target = NULL` (broadcast), `priority = 'normal'`
3. `text = json.dumps({"type": "idle_notification", "from": agent_id, "reason": reason})`
4. Retornar confirmación

**Actualizar `bridge.json`**: agregar `agent.idle` a `allowed_tools` de `developer` (y `architect`).

**Criterios de aceptación**:
- [ ] Tool registrada en `AGENT_TOOLS`
- [ ] Llama `agent.idle` → status del agente cambia a `online`
- [ ] Mensaje `idle_notification` aparece en `chat.read` del arquitecto
- [ ] Skills de dev actualizadas: llamar `agent.idle` al completar una tarea (antes de `task.submit_work`)

---

### Tarea 2.5 — Protocolo de shutdown ordenado
**Depende de**: 2.2

**Archivos**: `src/agent_bridge/tools/agents.py`

**Problema que resuelve**: cuando el dev se desconecta abruptamente, sus tareas quedan en `in_progress` hasta que el maintenance_loop las reasigna (5 min). Un protocolo formal permite al arquitecto pedir un cierre ordenado.

**Dos tools nuevas**:

```python
types.Tool(name="agent.shutdown_request", ...)
# Input: target_agent_id, reason (opcional)
# Lógica:
#   1. INSERT INTO messages con msg_type='shutdown_request', target=target_agent_id, priority='high'
#   2. text = json.dumps({type, request_id (uuid), from, reason})
#   3. Retornar {request_id}

types.Tool(name="agent.shutdown_approve", ...)
# Input: request_id
# Lógica:
#   1. Encontrar el mensaje de shutdown_request con ese request_id
#   2. INSERT INTO messages con msg_type='shutdown_approved', target=solicitante
#   3. UPDATE agents SET status='offline' para el agente que aprueba
#   4. Retornar confirmación
```

**Flujo completo**:
```
Arquitecto → agent.shutdown_request(target="opencode-1", reason="sprint done")
Dev lee chat.read → ve {type: "shutdown_request", request_id: "xyz"}
Dev → agent.shutdown_approve(request_id="xyz")
Arquitecto ve {type: "shutdown_approved"} en su próximo chat.read
```

**Criterios de aceptación**:
- [ ] `agent.shutdown_request` crea mensaje `shutdown_request` en inbox del target
- [ ] `agent.shutdown_approve` crea mensaje `shutdown_approved` + marca agente offline
- [ ] Sin respuesta en 5min → maintenance_loop marca offline igual (no depende del protocolo)
- [ ] Skills actualizadas con el flujo: dev sabe qué hacer al recibir `shutdown_request`
- [ ] `bridge.json` actualizado con permisos: `shutdown_request` solo `architect`, `shutdown_approve` solo `developer`

---

## Orden de ejecución

```
Fase 1 (bloqueante — en orden estricto):
  1.1 → 1.2 → 1.3 → 1.4

Fase 2 (iniciar cuando Fase 1 esté aprobada):
  2.1 → 2.2 → 2.3 (en paralelo con 2.4 y 2.5)
              2.4 ↗
              2.5 ↗
```

Las tareas 2.3, 2.4, y 2.5 pueden ejecutarse en cualquier orden después de que 2.2 esté aprobada.

---

## Checklist de revisión por tarea

Para cada tarea entregada, el arquitecto verifica:

| Ítem | Verificación |
|---|---|
| Criterios de aceptación | Todos los `[ ]` marcados como `[x]` |
| Migración DB | `SCHEMA_VERSION` bumpeado + migración aplicada sin error |
| Compatibilidad hacia atrás | Callers existentes no se rompen (parámetros nuevos son opcionales) |
| Permisos | `bridge.json` actualizado si hay tools nuevas |
| Skills | `.agentes/*.Skill` y `SKILL_TEMPLATES` en `main.py` sincronizados |
| Tests | Si la tarea toca lógica de DB o tools: tests mínimos incluidos |

---

## Restricciones técnicas

- **No usar tabla `messages` para pings** — tabla `ping_requests` separada (ya definido en Fase 1)
- **No forzar push** — el dev nunca hace `git push --force`
- **Parámetros nuevos siempre opcionales** — no romper clientes existentes
- **`sender="system"` para notificaciones automáticas** — diferenciable del chat humano
- **Máximo 4000 chars por mensaje** — validar en `chat.send`
- **`bridge.json` siempre actualizado** — si una tool nueva no está en `allowed_tools`, no funciona

---

*Arquitecto responsable: claude-architect-1 | Fecha del plan: 2026-05-14*

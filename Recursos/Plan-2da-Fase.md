# Plan de Trabajo — Segunda Fase

> **Documento de ejecución.** Basado en auditoría del código (2026-05-14), cruce con SPEC y PLAN_MEJORAS.
> Cada tarea tiene criterios de aceptación verificables. No avanzar a la siguiente sin completar la anterior.

---

## Estado Actual del Proyecto

### Implementado (SPEC Fases 0-7)
- Fundación del proyecto (uv, MCP SDK, SQLite + WAL, Textual)
- State machine completa: plan → tasks → in_progress → review → approved / changes_requested
- Tools: plan.*, task.*, review.*, chat.*, agent.*, skill.*
- Presencia de agentes (heartbeat, list, get, set_status)
- Configuración vía `bridge.json` + comandos `agent-bridge configure`
- Skills built-in (architect, developer) + permission layer
- Chat compartido con threads, @menciones, turn-taking
- TUI con Textual (panel de chat + estado de agentes)
- Discusión autónoma (threads con participantes, resolución atómica)
- Dry-run, reset, export/import
- 142 tests, todos pasando

### Bugs CRÍTICOS detectados (sin corregir)

| ID | Hallazgo | Archivo | Severidad |
|---|---|---|---|
| B-01 | F-string para construir JSON en planner/tasks/review → inyección | `planner.py:133,172`, `tasks.py:133,201-206,248`, `review.py:110,162` | CRÍTICO |
| B-02 | `uvicorn` no declarado en `pyproject.toml` | `main.py:106` | CRÍTICO |
| B-03 | `--dry-run` no se propaga al TUI | `main.py:72` | CRÍTICO |
| B-04 | `stderr=subprocess.PIPE` sin consumir → deadlock potencial | `main.py:61` | CRÍTICO |
| B-05 | Thresholds de stale agent inconsistentes (hardcodeados vs config) | `config.py` | CRÍTICO |

### Bugs MEDIOS detectados (sin corregir)
- `_maintenance_scope` mutable compartido (`server.py`)
- Path search break en `config.py`
- Test coverage faltante: SSE transport, dry-run e2e, payloads grandes, TUI

---

## Prioridades de Ejecución

```
Fase 0 (bugs críticos — resolver antes de tocar features):
  B-01 → B-02 → B-03 → B-04 → B-05

Fase 1 (Ping — PLAN_MEJORAS, orden estricto):
  1.1 → 1.2 → 1.3 → 1.4

Fase 2 (Mensajería mejorada — PLAN_MEJORAS):
  2.1 → 2.2 → 2.3 (en paralelo con 2.4, 2.5)

Fase 3 (Mejora continua — sin orden):
  3.1 Externalizar skill templates
  3.2 Paginación en chat.read
  3.3 Alinear thresholds definitivamente
  3.4 Tests de integración faltantes
```

---

## Fase 0 — Corrección de Bugs Críticos

### B-01: Reemplazar f-strings JSON con `json.dumps()`

**Archivos**: `src/agent_bridge/tools/planner.py`, `src/agent_bridge/tools/tasks.py`, `src/agent_bridge/tools/review.py`

**Qué hacer**: Cada lugar donde se construye un string JSON con f-strings (plan context, task context, review context) debe usar `json.dumps()`.

**Buscar el patrón**:
```python
# MAL — inyección potencial
f'{{"key": "{value}"}}'

# BIEN
json.dumps({"key": value})
```

**Lugares afectados**:
- `planner.py:133`, `planner.py:172`
- `tasks.py:133`, `tasks.py:201-206`, `tasks.py:248`
- `review.py:110`, `review.py:162`

**Criterios de aceptación**:
- [ ] Zero ocurrencias de f-strings con `{{` o `json.` concatenado
- [ ] `uv run ruff check src/` sin errores
- [ ] Tests existentes siguen pasando (`uv run pytest`)

---

### B-02: Agregar `uvicorn` a `pyproject.toml`

**Archivo**: `pyproject.toml`

**Qué hacer**: Agregar `uvicorn` a las dependencias (se usa en `main.py:106` para iniciar el servidor SSE pero no está declarado).

**Criterios de aceptación**:
- [ ] `uvicorn` aparece en `[project.dependencies]`
- [ ] `uv sync` lo instala sin errores
- [ ] `uv run python -c "import uvicorn"` no falla

---

### B-03: Propagar `--dry-run` al TUI

**Archivo**: `src/agent_bridge/main.py`

**Qué hacer**: Pasar `--dry-run` como argumento al subprocess del TUI, o mejor: inyectar la db dry-run en el contexto que el TUI recibe. Actualmente `--dry-run` solo afecta al server MCP, no a la TUI que se lanza como subprocess.

**Estado actual** (`main.py:72` aprox):
```python
tui_process = subprocess.Popen([sys.executable, "-m", "agent_bridge.ui.chat_tui"])
```

**Estado deseado**:
```python
tui_args = [sys.executable, "-m", "agent_bridge.ui.chat_tui"]
if args.dry_run:
    tui_args.append("--dry-run")
tui_process = subprocess.Popen(tui_args)
```

**Criterios de aceptación**:
- [ ] `agent-bridge start --dry-run` inicia TUI en modo dry-run
- [ ] TUI en dry-run no persiste mensajes en DB real
- [ ] Tests verifican que dry-run funciona end-to-end

---

### B-04: Consumir stderr del subprocess TUI

**Archivo**: `src/agent_bridge/main.py`

**Qué hacer**: El `stderr=subprocess.PIPE` en el Popen del TUI puede causar deadlock si el buffer del pipe (64KB en Linux) se llena. Solución: redirigir stderr a `/dev/null` o usar un thread para consumirlo.

**Opción recomendada**:
```python
tui_process = subprocess.Popen(
    [sys.executable, "-m", "agent_bridge.ui.chat_tui"],
    stderr=subprocess.DEVNULL,  # o subprocess.STDOUT si querés verlo
)
```

**Criterios de aceptación**:
- [ ] No hay `subprocess.PIPE` sin consumir en `main.py`
- [ ] El TUI sigue funcionando (logs de error no se pierden si usás DEVNULL, o se ven si usás STDOUT)

---

### B-05: Alinear thresholds de stale agent

**Archivo**: `src/agent_bridge/config.py`, `src/agent_bridge/server.py`

**Qué hacer**: El `config.py` puede tener valores definidos para `AGENT_AWAY_TIMEOUT` (90s) y `AGENT_OFFLINE_TIMEOUT` (300s) que deben ser usados consistentemente en `server.py` en vez de hardcodear los valores.

**Criterios de aceptación**:
- [ ] `server.py` lee los thresholds de `config.py` (o de settings)
- [ ] Un solo lugar de definición para estos valores
- [ ] No hay números mágicos (90, 300) en `server.py`

---

## Fase 1 — Sistema de Ping de Conectividad

> Basado en `Recursos/PLAN_MEJORAS.md`

### Tarea 1.1 — Migración DB: tabla `ping_requests`

**Archivos**: `src/agent_bridge/state/database.py`

**Schema a agregar**:
```sql
CREATE TABLE IF NOT EXISTS ping_requests (
    id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    pong_at TEXT,
    latency_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
);
```

**Métodos en `Database`**:
- `create_ping_request(sender_id, target_id) -> str`
- `record_pong(ping_id) -> int` (retorna latency_ms)
- `get_ping_request(ping_id) -> dict | None`

**`SCHEMA_VERSION`**: 4 → 5

**Criterios de aceptación**:
- [x] Tabla en schema SQL
- [x] `SCHEMA_VERSION = 5` con migración
- [x] Tres métodos async implementados
- [x] `latency_ms` calculado como diferencia `pong_at - sent_at`
- [x] Verificación: import + initialize sin errores

---

### Tarea 1.2 — Implementar tools `agent.ping` y `agent.pong`

**Archivos**: `src/agent_bridge/tools/agents.py`

**Tool `agent.ping`**:
- Input: `target_agent_id`, `timeout_seconds` (default 10)
- Crea `ping_request` en DB
- Envía mensaje al target con ping_id
- Loop `asyncio.sleep(0.5)` hasta timeout
- Retorna `{status: "pong"|"timeout", latency_ms?, target_agent_id}`

**Tool `agent.pong`**:
- Input: `ping_id`
- `record_pong(ping_id)` y retorna `{status: "ok", latency_ms}`

**Criterios de aceptación**:
- [x] Ambas tools en `AGENT_TOOLS`
- [x] `handle_agent_tool` despacha ambas
- [x] Polling cada 0.5s hasta timeout
- [x] En timeout: retorna `last_seen` del agente

---

### Tarea 1.3 — Registrar tools y actualizar permisos

**Archivos**: `bridge.json`

Agregar `"agent.ping"`, `"agent.pong"` a `allowed_tools` de `architect` y `developer`.

**Criterios de aceptación**:
- [x] Ambas tools en `allowed_tools` de ambos roles
- [x] `architect` puede llamar `agent.ping` sin `permission_denied`

---

### Tarea 1.4 — Protocolo de pong en Skills

**Archivos**: `.agentes/architect.Skill`, `.agentes/dev.Skill`, `src/agent_bridge/main.py` (SKILL_TEMPLATES)

Agregar sección **"Protocolo de respuesta a ping"** en todas las skills:
- Parsear `ping_id` de mensajes con `"type": "ping"`
- Llamar `agent.pong(ping_id="{ping_id}")`
- No publicar en chat

**Criterios de aceptación**:
- [x] Sección presente en ambos `.Skill`
- [x] Mismo contenido en `SKILL_TEMPLATES` de `main.py`

---

## Fase 2 — Capa de Mensajería Mejorada

### Tarea 2.1 — Migración DB: tipo, prioridad y lectura por mensaje

**Archivos**: `src/agent_bridge/state/database.py`

**Migración** (SCHEMA_VERSION 5 → 6):
```sql
ALTER TABLE messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'chat';
ALTER TABLE messages ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE messages ADD COLUMN read INTEGER NOT NULL DEFAULT 0;
```

**Tipos válidos**: `chat | task_assignment | status_update | dependency_notification | idle_notification | shutdown_request | shutdown_approved | system | ping`

**Prioridades**: `normal | high | urgent`

**Métodos nuevos**:
- `mark_message_read(message_id) -> None`
- `get_unread_count(target) -> int`

**Criterios de aceptación**:
- [x] `SCHEMA_VERSION = 6`
- [x] Tres columnas nuevas en `messages`
- [x] Defaults correctos para registros existentes
- [x] Métodos implementados

---

### Tarea 2.2 — Actualizar `chat.send` y `chat.read`

**Archivos**: `src/agent_bridge/tools/chat.py`

**`chat.send`**:
- Parámetros opcionales: `msg_type` (default `"chat"`), `priority` (default `"normal"`)
- Validación: `msg_type` en lista válida
- Límite: `len(text) > 4000` → error `message_too_long`

**`chat.read`**:
- Parámetros opcionales: `msg_type` (filtro), `unread_only` (bool), `priority_first` (bool)
- Si `unread_only=True` → `AND read = 0`
- Si `msg_type` → `AND msg_type = ?`
- Si `priority_first=True` → `ORDER BY CASE priority WHEN 'urgent' THEN 0 ...`

**Nuevo tool `chat.mark_read`**:
- Input: `message_id`
- Marca mensaje como leído

**Criterios de aceptación**:
- [x] `chat.send` acepta `msg_type` y `priority` (opcionales, no rompe callers)
- [x] Rechaza mensajes > 4000 chars
- [x] `chat.read` con `unread_only=True` funciona
- [x] `chat.read` con `priority_first=True` ordena urgentes primero
- [x] `chat.mark_read` funciona independientemente
- [x] Tests de filtros

---

### Tarea 2.3 — Notificaciones automáticas server-side

**Archivos**: `src/agent_bridge/server.py`, `src/agent_bridge/tools/chat.py`

**Helper**:
```python
async def _send_system_notification(db, target, text, msg_type, priority="normal"):
    await db.execute("INSERT INTO messages ...")
```

**Eventos**:

| Evento | msg_type | target | priority |
|---|---|---|---|
| task → `approved` | `status_update` | dev (assignee) | `high` |
| Task `approved` desbloquea dependencias | `dependency_notification` | dev | `high` |
| task → `changes_requested` | `status_update` | dev (assignee) | `high` |
| task → `review` (submit_work) | `status_update` | arquitecto | `normal` |

**Cuándo disparar**: inline en `review.approve`, `review.request_changes`, `task.submit_work`.

**Criterios de aceptación**:
- [x] `review.approve` → dev recibe `status_update` con `priority="high"`
- [x] `review.request_changes` → dev recibe `status_update`
- [x] `task.submit_work` → arquitecto recibe `status_update`
- [x] `sender="system"` y distinguible en TUI
- [x] No rompe si destinatario offline

---

### Tarea 2.4 — `agent.idle`: señal de disponibilidad

**Archivos**: `src/agent_bridge/tools/agents.py`

**Tool `agent.idle`**:
- Input: `reason` (opcional, default `"available"`)
- `UPDATE agents SET status = 'online'`
- `INSERT INTO messages` con `msg_type='idle_notification'`, broadcast (`target=NULL`)

**Permisos**: agregar `agent.idle` a `allowed_tools` de `developer` y `architect`.

**Criterios de aceptación**:
- [x] Tool registrada en `AGENT_TOOLS`
- [x] `agent.idle` cambia status del agente a `online`
- [x] Mensaje `idle_notification` visible en `chat.read`
- [x] Skills actualizadas

---

### Tarea 2.5 — Protocolo de shutdown ordenado

**Archivos**: `src/agent_bridge/tools/agents.py`

**Tool `agent.shutdown_request`**:
- Input: `target_agent_id`, `reason` (opcional)
- Crea mensaje `shutdown_request` con `priority='high'`
- Retorna `{request_id}`

**Tool `agent.shutdown_approve`**:
- Input: `request_id`
- Encuentra el mensaje original
- Crea mensaje `shutdown_approved`
- Marca agente offline

**Permisos**:
- `shutdown_request` → solo `architect`
- `shutdown_approve` → solo `developer`

**Criterios de aceptación**:
- [x] `shutdown_request` crea mensaje en inbox del target
- [x] `shutdown_approve` crea `shutdown_approved` + marca offline
- [x] Timeout 5min → maintenance_loop marca offline igual
- [x] Skills actualizadas
- [x] `bridge.json` actualizado

---

## Fase 3 — Mejora Continua

### 3.1 — Externalizar skill templates

**Archivo**: `src/agent_bridge/main.py` (~420 líneas con templates hardcodeados)

Mover las plantillas de skills a archivos separados en `~/.config/agent-bridge/skills/` o en el directorio del proyecto. El `main.py` las carga desde disco.

**Criterios de aceptación**:
- [ ] Skills por defecto existen como archivos .Skill
- [ ] `main.py` las lee de disco en vez de tenerlas hardcodeadas
- [ ] `agent-bridge init` las crea si no existen

---

### 3.2 — Paginación en `chat.read`

**Archivo**: `src/agent_bridge/tools/chat.py`

Agregar parámetros `limit` (default 50) y `offset` (default 0) a `chat.read`.

**Criterios de aceptación**:
- [ ] `chat.read(limit=10, offset=20)` retorna página correcta
- [ ] Sin parámetros, funciona igual que antes (default 50)

---

### 3.3 — Tests de integración faltantes

Agregar tests para:
- SSE transport (conexión, reconexión, mensajes)
- Dry-run end-to-end (server + TUI)
- Payloads grandes (mensajes > 4000 chars rechazados)
- TUI con mock de server

---

## Orden de Ejecución Recomendado

```
Semana 1: Fase 0 (bugs críticos)
  B-01 (f-strings) → B-02 (uvicorn) → B-03 (dry-run) → B-04 (stderr) → B-05 (thresholds)

Semana 2: Fase 1 (Ping)
  1.1 → 1.2 → 1.3 → 1.4

Semana 3-4: Fase 2 (Mensajería)
  2.1 → 2.2 → 2.3 + 2.4 + 2.5 (en paralelo después de 2.2)

Semana 5+: Fase 3 (Mejora continua)
  3.1 → 3.2 → 3.3 (según prioridad)
```

---

## Checklist de Revisión por Tarea

| Ítem | Verificación |
|---|---|
| Criterios de aceptación | Todos los `[x]` marcados |
| Migración DB | `SCHEMA_VERSION` bumpeado + migración sin error |
| Compatibilidad hacia atrás | Parámetros nuevos son opcionales |
| Permisos | `bridge.json` actualizado si hay tools nuevas |
| Skills | `.agentes/*.Skill` y `SKILL_TEMPLATES` sincronizados |
| Tests | Toda lógica de DB o tools tiene tests |
| Lint | `uv run ruff check src/` sin errores |
| Test suite | `uv run pytest` todo verde |

---

*Última actualización: 2026-05-29*

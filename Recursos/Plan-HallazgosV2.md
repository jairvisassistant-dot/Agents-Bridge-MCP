# Plan de Trabajo V2 — Corrección de Hallazgos Remanentes

> **Generado:** 2026-06-07  
> **Origen:** [Plan-HallazgosV1.md](./Plan-HallazgosV1.md) — Análisis de completitud post-fixes  
> **Hallazgos a corregir:** 10 issues (3 🔴 críticos, 2 🟡 altos, 3 🟠 medios, 2 🔵 bajos)  
> **8 tools afectadas** de 38 (21%) + 2 issues de infraestructura  
> **Estrategia:** Fundación primero (state machine), luego data integrity, luego infraestructura

---

## Resumen Ejecutivo

Quedan **10 issues** identificados en la auditoría post-fixes. Los bugs críticos del informe V1 (dry-run, INSTR) ya están corregidos. Los issues restantes son **de borde/edge case** — el flujo feliz funciona pero hay condiciones específicas donde el sistema falla.

### Issues por Fase de Corrección

| # | Issue | Archivo | Severidad | Esfuerzo |
|---|-------|---------|-----------|----------|
| 🔴 C1 | State machine decorativa (4 tools) | `tasks.py`, `review.py` | **Crítica** | ~1.5h |
| 🔴 C2 | `plan.archive` fuera de state machine | `state_machine.py`, `planner.py` | **Crítica** | ~15min |
| 🔴 C3 | `task.create` no valida `plan.status` | `tasks.py` | **Crítica** | ~15min |
| 🟡 V1 | VSCode claimTask envía `agent_id` en vez de `agent` | `mcpClient.ts` | **Alta** | ~5min |
| 🟡 M2 | `_maintenance_scope` global compartida | `server.py` | **Alta** | ~30min |
| 🟠 M1 | `plan.import` sin validación de estados | `database.py` | **Media** | ~20min |
| 🟠 M5 | `plan.delete` cascade incompleta | `planner.py` | **Media** | ~15min |
| 🟠 M4 | Maintenance loop sin exponential backoff | `server.py` | **Media** | ~10min |
| 🔵 M3 | `chat.read since` — rowid vs UUID ambigüedad | `chat.py` | **Baja** | ~15min |
| 🔵 V2 | `submitWork` envía `agent_id` extra (inocuo) | `mcpClient.ts` | **Baja** | ~5min |

---

## Principios de Ejecución

1. **State machine real, no decorativa.** El cambio más importante: `validate_task_transition()` debe ejecutarse ANTES del SQL, no después. Sin esto, la máquina de estados es cosmética.
2. **Testeamos lo que tocamos.** Cada fix incluye su test. Sin test no está terminado.
3. **Un fix por capa.** Primero la validación (state machine + plan status), después la integridad de datos (import/delete), después infraestructura.
4. **PRs pequeños y enfocados.** Cada fase es un PR independiente. Máximo ~300 líneas cambiadas por PR.
5. **Sin regresiones.** El patrón C1 cambia el flujo de 4 tools. Cada una debe verificarse individualmente.

---

## Fase 0 — Quick Wins (~20 min)

**Archivos:** `mcpClient.ts`, `server.py`  
**PR único** — cambios triviales, 100% seguros, archivos independientes.

### 0.1 — V1: VSCode claimTask usa `agent` en vez de `agent_id`

| Campo | Detalle |
|-------|---------|
| **Archivo** | `extensions/vscode/src/mcpClient.ts` (línea 261) |
| **Código actual** | `agent_id: agentId` |
| **Código nuevo** | `agent: agentId` |
| **Qué cambia** | El nombre del parámetro que la extensión envía al servidor. El servidor espera `agent` y recibe `agent_id`. |
| **Impacto** | Sin este fix, la extensión VSCode SIEMPRE cae en `"developer"` para `_agent_role`, porque `args.get("agent")` es `undefined` al recibir `agent_id`. |
| **Verificación** | `claimTask("abc", "opencode-1")` envía `{task_id: "abc", agent: "opencode-1"}` en vez de `{task_id: "abc", agent_id: "opencode-1"}`. |

### 0.2 — M4: Exponential backoff en maintenance loop

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/server.py` (línea 194-196) |
| **Código actual** | `await anyio.sleep(5)` — fijo, sin backoff |
| **Código nuevo** | `delay = min(delay * 2, 60); await anyio.sleep(delay)` — backoff exponencial 1s → 2s → 4s → ... → 60s max |
| **Verificación** | Loop se reinicia en 1s tras crash, luego duplica hasta 60s. Resetea a 1s tras ciclo exitoso. |

### 0.3 — V2: Limpiar `agent_id` extra en submitWork (opcional, inocuo)

| Campo | Detalle |
|-------|---------|
| **Archivo** | `extensions/vscode/src/mcpClient.ts` (línea 276) |
| **Código actual** | `agent_id: agentId` en el payload de `submitWork` |
| **Código nuevo** | Eliminar el parámetro `agent_id` (no lo usa el servidor) |
| **Verificación** | `submitWork` envía solo `{task_id, summary, diff}`. Sin cambios en el servidor. |

---

## Fase 1 — Integridad de Planes: State Machine Foundation (~30 min)

**Archivos:** `state_machine.py`, `planner.py`, `tasks.py`  
**PR único** — cambios en la state machine + dos validaciones que dependen de ella.  
**Razón:** Sin actualizar `PLAN_TRANSITIONS` primero (C2), la validación de `task.create` (C3) no tendría sentido porque el estado `archived` no existiría en la máquina.

### 1.1 — C2: Agregar "archived" a PLAN_TRANSITIONS

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/state/state_machine.py` (líneas 42-48) |
| **Código actual** | `PLAN_TRANSITIONS` no incluye `"archived"`. `_archive_plan` escribe directo a DB. |
| **Código nuevo** | Agregar `"archived"` como estado terminal en `PLAN_TRANSITIONS`. Transiciones permitidas hacia `archived` desde: `"tasks_ready"`, `"in_progress"`, `"completed"`. |
| **También:** | Actualizar `PlanStatus` type en `models.py` (línea 10) para incluir `"archived"`. |
| **Dependencias** | Ninguna — es un cambio en la state machine pura. |

```python
# state_machine.py — PLAN_TRANSITIONS actualizado
PLAN_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    "idle": {"planning"},
    "planning": {"tasks_ready", "idle"},
    "tasks_ready": {"in_progress", "idle", "archived"},
    "in_progress": {"completed", "idle", "archived"},
    "completed": {"archived"},
    "archived": set(),  # terminal state
}
```

### 1.2 — C2: Usar validate_plan_transition en _archive_plan

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/tools/planner.py` (líneas 265-291) |
| **Código actual** | `_archive_plan` verifica manualmente `row["status"] in ("completed", "archived")` y escribe directo |
| **Código nuevo** | Leer status actual, llamar `validate_plan_transition(current_status, "archived")`, luego UPDATE |
| **Verificación** | `plan.archive` sobre un plan `idle` → error. `plan.archive` sobre `tasks_ready` → OK. |

### 1.3 — C3: Validar plan.status en task.create

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/tools/tasks.py` (líneas 147-177) |
| **Código actual** | `_create_task` no consulta `plan.status`. Solo verifica que `plan_id` no esté vacío. |
| **Código nuevo** | Después de validar `plan_id`, hacer SELECT del status del plan. Si el plan está `completed` o `archived`, devolver error. |
| **Estados permitidos** | Solo `planning`, `tasks_ready`, `in_progress` |
| **Verificación** | `task.create(plan_id=completed_plan)` → error. `task.create(plan_id=valid_plan)` → OK. |

```python
# A agregar en _create_task, después de la validación de plan_id
plan_row = await db.execute_one("SELECT status FROM plans WHERE id = ?", (plan_id,))
if plan_row is None:
    return [types.TextContent(type="text", text='{"error": "plan not found"}')]
if plan_row["status"] in ("completed", "archived"):
    return [types.TextContent(
        type="text",
        text=json.dumps({"error": f"plan is {plan_row['status']}, cannot add tasks"})
    )]
```

---

## Fase 2 — State Machine Real Enforcement (~1.5h)

**Archivos:** `tasks.py`, `review.py`  
**PR único** — los 4 fixes comparten el mismo patrón arquitectónico.  
**Razón:** Este es el fix más importante de todo el plan. Convierte la state machine de decorativa a enforceble. Sin esto, cambiar `TASK_TRANSITIONS` no tiene efecto real.

### El patrón correcto (referencia: `plan.update`)

```python
# planner.py:206-214 — EL MODELO A SEGUIR
row = await db.execute_one("SELECT status FROM plans WHERE id = ?", (plan_id,))
current_status = row["status"]
try:
    validate_plan_transition(current_status, target_status)  # ← PRIMERO validar
except TransitionError as e:
    return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

await db.execute("UPDATE plans SET status = ? ...", (target_status, plan_id))  # ← DESPUÉS escribir
```

### 2.1 — Fix `_claim_task` (tasks.py:280-301)

**Patrón actual (ROTO):**
```python
affected = await db.execute_write("UPDATE ... WHERE status = 'pending'")  # ← escribe primero
if affected == 0:
    row = await db.execute_one("SELECT status ...")
    try:
        validate_task_transition(row["status"], "in_progress")  # ← valida después (solo error msg)
    except TransitionError as e:
        return error
```

**Patrón nuevo (CORRECTO):**
```python
row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
if row is None:
    return error
try:
    validate_task_transition(row["status"], "in_progress")  # ← validar PRIMERO
except TransitionError as e:
    return error

affected = await db.execute_write(
    "UPDATE tasks SET status = 'in_progress' ... WHERE id = ? AND status = ?",
    (agent, task_id, row["status"]),  # ← WHERE usa status leído, no hardcodeado
)
if affected == 0:
    return error  # race condition o concurrent update
```

| Campo | Detalle |
|-------|---------|
| **Qué cambia** | `validate_task_transition()` se mueve ANTES del UPDATE. El WHERE status usa el valor leído (no hardcodeado). |
| **Riesgo** | Race condition entre el SELECT y el UPDATE. El WHERE status captura esto: si otro proceso cambió el status, el UPDATE falla y se retorna error. |
| **Verificación** | Test: claim task en estado `pending` → OK. Claim task en estado `review` → error (state machine). Claim concurrente → uno gana, otro recibe error de concurrencia. |

### 2.2 — Fix `_submit_work` (tasks.py:325-344)

**Mismo patrón que 2.1.**

| Campo | Detalle |
|-------|---------|
| **Código actual** | `WHERE status IN ('in_progress', 'changes_requested')` hardcodeado. validate DESPUÉS. |
| **Código nuevo** | Leer status actual → `validate_task_transition(current, "review")` → UPDATE con `WHERE status = current` |
| **Verificación** | Test: submit en `in_progress` → OK. Submit en `pending` → error. |

### 2.3 — Fix `_approve_review` (review.py:175-201)

**Misma lógica pero dentro de `with_transaction`.**

| Campo | Detalle |
|-------|---------|
| **Código actual** | Dentro de `_do_approve` hace UPDATE con `WHERE status='review'`. Sin validate. |
| **Código nuevo** | Antes de `with_transaction`: leer status, `validate_task_transition(current, "approved")`. Dentro de la transacción: mismo UPDATE atómico. |
| **Verificación** | Test: approve task en `review` → OK. Approve task en `pending` → error. |

### 2.4 — Fix `_request_changes` (review.py:241-268)

**Mismo patrón que 2.3.**

| Campo | Detalle |
|-------|---------|
| **Código actual** | Dentro de `_do_request_changes` hace UPDATE con `WHERE status='review'`. Sin validate. |
| **Código nuevo** | Antes de `with_transaction`: leer status, `validate_task_transition(current, "changes_requested")`. Dentro de la transacción: UPDATE atómico. |
| **Verificación** | Test: request_changes en `review` → OK. En `approved` → error. |

---

## Fase 3 — Integridad de Datos en Import/Delete (~35 min)

**Archivos:** `database.py`, `planner.py`  
**PR único** — ambos son sobre limpieza/validación de datos persistentes.

### 3.1 — M1: Validar estados en plan.import

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/state/database.py` (líneas 480-537) |
| **Código actual** | `plan.get("status", "idle")` sin validación. Tasks y reviews igual. |
| **Código nuevo** | Antes de INSERT, validar que `plan_status` esté en `PlanStatus.__args__` (o valores conocidos). Lo mismo para `task.status` y `review.status`. Si algún estado es inválido, rechazar todo el import. |
| **Validación** | Importar con `plan.status = "invalid_state_123"` → error. Importar con datos válidos → OK. |
| **Verificación** | Test con plan data corrupto → error message con detalle de qué campo es inválido. |

```python
# Pseudocódigo para la validación
VALID_PLAN_STATUSES = {"idle", "planning", "tasks_ready", "in_progress", "completed", "archived"}
VALID_TASK_STATUSES = {"pending", "in_progress", "review", "approved", "changes_requested"}
VALID_REVIEW_STATUSES = {"pending", "in_review", "approved", "changes_requested"}

plan_status = plan.get("status", "idle")
if plan_status not in VALID_PLAN_STATUSES:
    raise ValueError(f"Invalid plan status: {plan_status}")
```

### 3.2 — M5: Cascade completa en plan.delete

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/tools/planner.py` (líneas 304-310) |
| **Código actual** | DELETE reviews → DELETE tasks → DELETE plan. Threads y messages huérfanos. |
| **Código nuevo** | Agregar DELETE de messages vinculados a tasks del plan (via `messages.thread_id` relacionado a threads de esas tasks). |
| **Consideración** | Los mensajes pueden ser importantes para auditoría. Alternativa: marcar como `thread_id = NULL` en vez de borrar. |
| **Verificación** | Test: crear plan con task, enviar mensaje, borrar plan → mensaje no queda huerfano (borrado o desvinculado). |

---

## Fase 4 — Infraestructura Hardening (~45 min)

**Archivos:** `server.py`, `chat.py`  
**PR único o 2 PRs pequeños** (server.py es independiente de chat.py).  
**Razón:** Issues que afectan la robustez del sistema en producción.

### 4.1 — M2: _maintenance_scope per-instancia

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/server.py` (líneas 25, 310-326) |
| **Código actual** | `_maintenance_scope` es variable **module-level**. Si `create_server()` se llama múltiples veces, todos comparten el mismo scope. |
| **Código nuevo** | Mover `_maintenance_scope` adentro de `create_server()`, como variable en el closure de `init()`. O usar un `dict[str, CancelScope]` keyeado por `db_path`. |
| **Dependencias** | M4 (backoff) ya implementado en Fase 0. El scope se usa en el wrapper del maintenance loop. |
| **Verificación** | Test: crear 2 servidores con distintos `db_path` → cada uno tiene su propio maintenance loop. El segundo no hereda el scope del primero. |

```python
# server.py — cambio conceptual
# En vez de:
_maintenance_scope: anyio.CancelScope | None = None  # module-level

# Hacer:
_instances: dict[str, anyio.CancelScope] = {}  # key = db_path

# En init():
if db_path not in _instances:
    scope = anyio.CancelScope()
    _instances[db_path] = scope
    asyncio.get_running_loop().create_task(_wrapper(db, config, scope))
```

### 4.2 — M3: Fix ambigüedad rowid vs UUID en chat.read since

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/tools/chat.py` (líneas 500-511) |
| **Código actual** | `int(since)` primero, fallback a UUID. UUIDs como `"12345678-...."` se interpretan como rowid. |
| **Código nuevo** | Opción A (recomendada): soportar `since_rowid` (int) y `since` (UUID) como parámetros separados. Opción B: prefijo `rowid:` para distinguir. |
| **Probabilidad** | Baja — rowid 12345678 requiere ~12M mensajes. |
| **Verificación** | Test: `chat.read(since="12345678-1234-....")` → busca por UUID, NO como rowid. |

---

## Fase 5 — Testing y Verificación (~30 min)

**Archivos:** `tests/test_edge_cases.py` (o archivo nuevo `tests/test_state_machine_enforcement.py`)  
**PR único** — todos los tests nuevos juntos.

### Plan de Tests

| # | Fix | Test | Tipo |
|---|-----|------|------|
| 1 | C2 | `test_plan_archive_transition_valid`: archivar plan `tasks_ready` → OK | unit |
| 2 | C2 | `test_plan_archive_transition_invalid`: archivar plan `idle` → error | unit |
| 3 | C3 | `test_create_task_in_completed_plan`: crear task en plan completado → error | unit |
| 4 | C3 | `test_create_task_in_valid_plan`: crear task en plan `planning` → OK | unit |
| 5 | C1 | `test_task_claim_validates_state_machine_first`: claim task `pending` → OK. Claim task ya `in_progress` → error | unit |
| 6 | C1 | `test_task_submit_validates_state_machine_first`: submit en `in_progress` → OK. Submit en `pending` → error | unit |
| 7 | C1 | `test_review_approve_validates_state_machine`: approve en `review` → OK. Approve en `pending` → error | unit |
| 8 | C1 | `test_review_request_changes_validates_state_machine`: request_changes en `review` → OK. En `approved` → error | unit |
| 9 | C1 | `test_concurrent_claim_race_condition`: dos claims simultáneos → uno gana | integración |
| 10 | M1 | `test_plan_import_invalid_status`: import con `status: "bad"` → error | unit |
| 11 | M1 | `test_plan_import_valid_data`: import con datos correctos → OK | unit |
| 12 | M5 | `test_plan_delete_cascade_messages`: borrar plan → mensajes no quedan huérfanos | integración |
| 13 | M2 | `test_maintenance_scope_per_instance`: dos servidores → cada uno con su loop | integración |
| 14 | M3 | `test_chat_read_since_uuid_not_rowid`: since con UUID que parece entero → busca por UUID | unit |

---

## 🗺️ Mapa de Dependencias Entre Fases

```
Fase 0 (Quick Wins) ← sin dependencias
   V1: mcpClient.ts    M4: server.py    V2: mcpClient.ts
   │
   ▼
Fase 1 (State Machine Foundation) ← depende de Fase 0
   1.1 C2: state_machine.py + models.py  ← PRIMERO (base para todo)
   1.2 C2: planner.py                    ← depende de 1.1
   1.3 C3: tasks.py                      ← depende de 1.1 (usa "archived" en validación)
   │
   ▼
Fase 2 (State Machine Real Enforcement) ← depende de Fase 1
   2.1 C1: task.claim                    ← usa el patrón validate-before-write
   2.2 C1: task.submit_work              ← mismo patrón
   2.3 C1: review.approve                ← mismo patrón
   2.4 C1: review.request_changes        ← mismo patrón
   │
   ├──────────────────────┐
   ▼                      ▼
Fase 3 (Data Integrity)    Fase 4 (Infrastructure)
   3.1 M1: database.py      4.1 M2: server.py
   3.2 M5: planner.py       4.2 M3: chat.py
   │                      │
   └──────────┬───────────┘
              ▼
      Fase 5 (Testing)
```

---

## 📊 Tabla Resumen de Esfuerzo

| Fase | Descripción | Archivos | Issues | Esfuerzo estimado | PRs |
|------|-------------|----------|--------|-------------------|-----|
| 0 | Quick Wins | `mcpClient.ts`, `server.py` | V1, M4, V2 | ~20 min | 1 |
| 1 | State Machine Foundation | `state_machine.py`, `models.py`, `planner.py`, `tasks.py` | C2, C3 | ~30 min | 1 |
| 2 | State Machine Real Enforcement | `tasks.py`, `review.py` | C1 (4 tools) | ~1.5h | 1 |
| 3 | Data Integrity | `database.py`, `planner.py` | M1, M5 | ~35 min | 1 |
| 4 | Infrastructure | `server.py`, `chat.py` | M2, M3 | ~45 min | 1-2 |
| 5 | Testing | `test_edge_cases.py` | Todos | ~30 min | 1 |

**Total issues corregidos:** 10 (3 🔴, 2 🟡, 3 🟠, 2 🔵)  
**Esfuerzo total estimado:** ~4-5h  
**PRs totales:** ~6 (1 por fase, Fase 4 puede ser 2)

---

## 🧪 Estrategia de Testing

Cada fix en Fases 1-4 incluye su test correspondiente. Los tests se agregan en la Fase 5 pero pueden escribirse en paralelo con cada fix.

```bash
# Tests de state machine
pytest tests/test_edge_cases.py -xvs -k "test_plan_archive"
pytest tests/test_edge_cases.py -xvs -k "test_create_task_in_completed_plan"

# Tests de enforcement
pytest tests/test_edge_cases.py -xvs -k "test_task_claim_validates"
pytest tests/test_edge_cases.py -xvs -k "test_review_approve_validates"

# Tests de import
pytest tests/test_edge_cases.py -xvs -k "test_plan_import"

# Suite completa
pytest tests/ -x --timeout=60
```

---

## 🚀 Prioridad de Ejecución Recomendada

### 🥇 Hoy — Fase 0 (20 min)
V1 es el fix más urgente: la extensión VSCode no puede asignar tareas correctamente. M4 evita log-spamming. V2 es limpieza trivial.

### 🥈 Hoy — Fase 1 (30 min)
C2 y C3 son la base para Fase 2. Sin `"archived"` en `PLAN_TRANSITIONS`, las validaciones de Fase 2 no tienen sentido completo. Sin la validación de `plan.status` en `task.create`, se pueden corromper planes.

### 🥉 Hoy-Mañana — Fase 2 (1.5h)
El fix más importante. Convierte la state machine de decorativa a real. Cambia el patrón en 4 tools. Requiere pruebas cuidadosas de regresión.

### 🏅 — Fase 3 + 4 + 5 (~2h)
Importan pero no son críticas para el funcionamiento diario. M2 solo afecta a múltiples servidores. M3 es baja probabilidad. M5 es limpieza de datos huérfanos.

---

## 🎯 Conclusión

La corrección de estos 10 issues lleva el código de **79% de tools completas** a un **~97%**. Los 3 cambios clave son:

1. **V1** (Fase 0): Fix de 1 línea que habilita la extensión VSCode para asignar tareas
2. **C1** (Fase 2): Cambio de patrón en 4 tools que hace enforceable la state machine
3. **C2 + C3** (Fase 1): Cierre de los agujeros de validación en el ciclo de vida de planes

El resto (M1, M2, M3, M4, M5, V2) son hardening — importantes pero no bloqueantes.

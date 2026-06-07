# Plan de Trabajo — Corrección de Hallazgos V1

> **Generado:** 2026-06-06  
> **Última actualización:** 2026-06-07  
> **Origen:** [HallazgosV1.md](./HallazgosV1.md) — 20 hallazgos (2 críticos, 5 altos, 7 medios, 6 bajos) + 12 features ausentes  
> **Estrategia:** Agrupar por archivo para minimizar context switching, fundación primero para habilitar testing
> **Estado general:** Fases 0–6 completadas ✅ | Fase 7 ✅ completada | Fase 8 pendiente

---

## 📋 Estado de Ejecución

| Fase | Descripción | Estado |
|------|-------------|--------|
| **0** | Quick Wins & Safety | ✅ Completado |
| **1** | Fundación: Base de Datos | ✅ Completado |
| **2** | Integridad de Datos: Tasks + Agents + Reviews | ✅ Completado |
| **3** | Chat System Correctness | ✅ Completado |
| **4** | Resiliencia y Sistema | ✅ Completado |
| **5** | Consolidación de Máquina de Estados | ✅ Completado |
| **6** | Configuración y Hot-Reload | ✅ Completado |
| **7** | Features Faltantes | ✅ Completado |
| **8** | Distribución: Extensión VSCode | ❌ Pendiente |

**Commits:** [`86f6625`](https://github.com/jairvisassistant-dot/Agents-Bridge-MCP/commit/86f6625) (fases 0–6), fases 7.2–7.6 pendiente de commit

---

---

## Principios de Ejecución

1. **Cada fase debe dejar el código en un estado mejor que antes.** No importa si no se termina todo — cada merge parcial mejora el sistema.
2. **Testeamos lo que tocamos.** Cada fix incluye su test o actualización de test existente. Sin test no está terminado.
3. **PRs pequeños y enfocados.** Idealmente 1 PR por fase, máximo ~400 líneas cambiadas. Si una fase excede, se parte en sub-PRs.
4. **Sin deuda nueva.** No postergamos calidad para después. Si tocamos un archivo, dejamos el formato y tipos al día (ruff).
5. **Primero datos, después UX.** Correcciones de integridad de datos antes que mejoras visuales.

---

## ✅ Fase 0 — Quick Wins & Safety (~10 min)

**Archivos:** `.gitignore`, `kanban_board.py`  
**PR único** — cambios triviales y 100% seguros.  
**Estado:** COMPLETADO

### ✅ 0.1 — Bug #10: .gitignore sin bridge.db

| Campo | Detalle |
|-------|---------|
| **Archivo** | `.gitignore` |
| **Qué** | Agregar `bridge.db*` después de la línea 21 |
| **Verificación** | ✅ `bridge.db*` agregado. `git status` ya no muestra `bridge.db` ni sus variantes. |

### ✅ 0.2 — Bug #19: UUID completo en TaskItem

| Campo | Detalle |
|-------|---------|
| **Archivo** | `src/agent_bridge/ui/kanban_board.py` (~línea 75) |
| **Qué** | Truncar `task_id` a primeros 8 caracteres en display |
| **Cómo** | Cambiar `f"#{task_id}"` por `f"#{task_id[:8]}"` |
| **Verificación** | ✅ Implementado: `task_id = (task.get("id") or "?")[:8]`. IDs en kanban se ven como `#550e8400`. |

---

## ✅ Fase 1 — Fundación: Base de Datos (~45 min)

**Archivo:** `src/agent_bridge/state/database.py`  
**PR único** — todos los cambios en database.py, unificados.  
**Razón:** Sin una DB funcional en dry-run no podemos testear el resto de fixes de forma aislada.  
**Estado:** COMPLETADO (ya implementado en working tree)

### ✅ 1.1 — Bug #1: Modo `--dry-run` completamente roto (CRÍTICO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | `_connect()` crea una `:memory:` **nueva en cada llamada** cuando `_dry_run=True`. |
**Solución** | Cachear la conexión `:memory:` como `self._dry_run_conn`. |
**Verificación** | ✅ `_connect()` cachea `self._dry_run_conn`; `_initialize()` usa la misma conexión. Tests dry-run pasan. |

### ✅ 1.2 — Bug #9: `with_transaction` ignora `dry_run` (MEDIO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | `with_transaction()` no checkea `_dry_run` antes de ejecutar. |
**Solución** | Guarda al inicio de `_run()`: si `_dry_run`, loguear y retornar None. |
**Verificación** | ✅ `with_transaction._run()` retorna `None` inmediatamente si `_dry_run` está activo. |

### ✅ 1.3 — Bug #20: Sin migración inversa (BAJO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | `_run_migrations` solo migra hacia adelante. |
**Solución** | `_run_reverse_migrations()` con reversiones v7→v6, v6→v5, v5→v4, v4→v3, v3→v2. |
**Verificación** | ✅ Implementado y llamado desde `_initialize()` cuando `current_version > SCHEMA_VERSION`. |

---

## ✅ Fase 2 — Integridad de Datos: Tasks + Agents + Reviews (~60 min)

**Archivos:** `tasks.py`, `agents.py`, `review.py`  
**PR único** — son archivos separados pero lógicamente relacionados (ciclo plan → task → review).  
**Razón:** Estos bugs producen datos incorrectos que persisten en la DB. Arreglarlos temprano evita que datos corruptos se propaguen.  
**Estado:** COMPLETADO (ya implementado en working tree)

### ✅ 2.1 — Bug #3: `task.claim` permite asignar cualquier rol (ALTO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/tools/tasks.py` (~línea 169) |
**Causa raíz** | El parámetro `agent` lo provee el caller y no se valida contra `_agent_role` inyectado por el servidor. |
**Solución** | Comparar `args.get("agent")` con `args.get("_agent_role")`. Si no coinciden, devolver error. Si `_agent_role` no está presente (por ejemplo, llamado directo sin server), permitir el valor del input como fallback. |
**Código ofensivo** | `agent = args.get("agent", "developer")` — debería ser `args.get("_agent_role", args.get("agent", "developer"))` |
**Dependencias** | Fase 1 (para testear con dry-run) |
**Verificación** | Test que llama `task.claim` con `agent="architect"` teniendo rol `developer` y verifica que retorna error. |

### 2.2 — Bug #4: `agent.set_status` permite cambiar estado de OTRO agente (ALTO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/tools/agents.py` (~línea 276) |
**Causa raíz** | No verifica que `agent_id` del input coincida con `_agent_id` inyectado. |
**Solución** | Agregar validación al inicio de `_set_status()`: si `_agent_id` está presente en args y `args["agent_id"] != args["_agent_id"]`, devolver error "cannot set status for another agent". |
**Código ofensivo** | Líneas 276-293 |
**Dependencias** | Fase 1 |
**Verificación** | Test que llama `set_status(agent_id="other-agent", status="offline")` teniendo id "my-agent" y verifica que retorna error. |

### 2.3 — Bugs #5, #11: `review.start` duplicados + código muerto (ALTO + MEDIO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/tools/review.py` |
**Causa raíz #5** | `review.start` inserta sin verificar si ya existe un review activo (`status='in_review'`) para esa task. |
**Solución #5** | Antes de INSERT, hacer SELECT de reviews activos para `task_id`. Si existe alguno, devolver `{"error": "review already active", "review_id": existing_id}`. |
**Causa raíz #11** | El flujo después de `try/except` en approve/request_changes es inalcanzable (si `validate_task_transition` pasa, el UPDATE debería funcionar porque la única transición válida es desde `review`). |
**Solución #11** | Simplificar: eliminar el bloque `try/except`. Si `affected == 0`, devolver error directamente. El UPDATE con `WHERE id=? AND status='review'` es la verdadera validación atómica. |
**Dependencias** | Fase 1 |
**Esfuerzo** | Bajo — cambios localizados |
**Verificación** | Test de `review.start` llamado dos veces para misma task → primera OK, segunda error. Test de approve con task en estado incorrecto → error sin dead code. |

---

## ✅ Fase 3 — Chat System Correctness (~50 min)

**Archivo:** `src/agent_bridge/tools/chat.py`  
**PR único** — los 3 bugs están en el mismo archivo y comparten queries SQL.  
**Razón:** El chat es el sistema nervioso del bridge. Bugs aquí afectan a todos los agentes.  
**Estado:** COMPLETADO

### ✅ 3.1 — Bug #2: INSTR en JSON arrays da falsos positivos (CRÍTICO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | `INSTR(participants, ?)` busca subcadena dentro de la representación JSON. |
**Solución** | Extraer el array con `json.loads()` en Python y filtrar con `in`. |
**Verificación** | ✅ Implementado: `_parse_participants()` usa `json.loads()`. No hay más `INSTR` en queries de participantes. |

### ✅ 3.2 — Bug #7: `chat.read` marca como leído inconsistentemente (ALTO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | Con filtro `target` marcaba mensajes como leídos. Sin filtro no marcaba ninguno. |
**Solución** | Eliminar el bloque que marcaba como leído desde `chat.read`. `chat.mark_read` es la única vía. |
**Verificación** | ✅ Bloque de auto-mark eliminado. `chat.read` solo lee, nunca modifica `read_status`. |

### ✅ 3.3 — Bug #13: Semántica ambigua en `thread_get_pending` (MEDIO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | `current_turn IS NULL` no distingue "thread sin actividad" de "thread con actividad sin turno". |
**Solución** | Usar `(last_activity_at = created_at)` como proxy de "sin actividad". Si `current_turn IS NULL` e `last_activity_at == created_at`, el thread no tiene mensajes → no se muestra como pending. |
**Verificación** | ✅ Implementado en `_thread_get_pending`. Test actualizado: `test_thread_get_pending_new_thread_no_messages` verifica que threads sin mensajes NO aparecen como pending. |

---

## ✅ Fase 4 — Resiliencia y Sistema (~40 min)

**Archivos:** `server.py`, `chat_tui.py`, `tui_bridge.py`  
**PR único o 2 PRs** (uno para server, otro para UI)  
**Razón:** Bugs que hacen que el sistema degrade silenciosamente.  
**Estado:** COMPLETADO (ya implementado en working tree)

### ✅ 4.1 — Bug #6: Maintenance loop fire-and-forget irrecuperable (ALTO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/server.py` |
**Causa raíz** | Se lanzaba con `asyncio.create_task` sin manejo de errores ni reinicio. |
**Solución** | Wrapper con `try/except` + `anyio.sleep(5)` en catch + `CancelScope` para limpieza ordenada. |
**Verificación** | ✅ `_maintenance_loop` tiene `while True` externo con `except Exception: sleep(5)` para reinicio automático. Envuelto en `CancelScope` desde `init()`. |

### ✅ 4.2 — Bug #12: `_format_time` crashea con datetimes naive (MEDIO)

| Campo | Detalle |
|-------|---------|
**Archivos** | `src/agent_bridge/ui/chat_tui.py`, `tui_bridge.py` |
**Causa raíz** | `astimezone()` raisea `ValueError` si el datetime es naive. |
**Solución** | `if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)` antes de `astimezone()`. |
**Verificación** | ✅ Ambos archivos tienen el guard. Datetimes naives se tratan como UTC antes de conversión. |

### ✅ 4.3 — Bug #14: `move_task` valida fuera de transacción (MEDIO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/ui/tui_bridge.py` |
**Causa raíz** | `can_transition` se llamaba fuera de `execute_write`. Race condition entre validación y UPDATE. |
**Solución** | `can_transition` + UPDATE dentro de `with_transaction`. UPDATE con `WHERE id=? AND status=?` para atomicidad. |
**Verificación** | ✅ `move_task` usa `db.with_transaction(_do_move)` que lee status, valida, y updatea atómicamente. |

### ✅ 4.4 — Bug #16: Timeout duro 30s en MCPClient (BAJO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/ui/chat_tui.py` |
**Causa raíz** | `asyncio.wait_for(readline(), timeout=30)` hardcodeado. |
**Solución** | Hacer configurable vía parámetro `request_timeout` (default 120s). |
**Verificación** | ✅ Timeout ahora es `self._request_timeout` (default 120s), configurable desde el constructor. |

---

## ✅ Fase 5 — Consolidación de Máquina de Estados (~35 min)

**Archivos:** `planner.py` + revisión de `review.py`  
**PR único** — ambos cambios son sobre usar la máquina de estados ya existente.  
**Razón:** La máquina de estados está completa pero no se usa. Esto es deuda técnica que confunde a futuros desarrolladores.  
**Estado:** COMPLETADO (ya implementado en working tree)

### ✅ 5.1 — Bug #8: `plan.create` bypass state machine (MEDIO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/tools/planner.py` |
**Causa raíz** | El plan se creaba directamente en `tasks_ready`, saltándose `idle → planning → tasks_ready`. |
**Solución** | Usar `validate_plan_transition("idle", "planning")` y crear el plan con `status='planning'`. Tools `plan.finalize` para la transición a `tasks_ready`. |
**Verificación** | ✅ `_create_plan` valida contra state machine y crea con `status='planning'`. |

### ✅ 5.2 — Bug #15: `plan.get` no devuelve tasks asociadas (BAJO)

| Campo | Detalle |
|-------|---------|
**Archivo** | `src/agent_bridge/tools/planner.py` |
**Causa raíz** | `plan.get` solo devolvía metadatos del plan, sin incluir tasks. |
**Solución** | Query `SELECT ... FROM tasks WHERE plan_id = ?` incluida en el response de `plan.get`. |
**Verificación** | ✅ `_get_plan` incluye campo `tasks` con id, title, status, assignee, description. |

---

## ✅ Fase 8 — Distribución: Extensión VSCode Autocontenida (~3h)

**Archivos:** `build/bundle-backend.sh`, `.github/workflows/release.yml`, `extensions/vscode/package.json`  
**PR único** — toda la cadena de distribución.  
**Razón:** Hoy la extensión VSCode requiere que el backend Python esté instalado por separado. El objetivo es que instalar el `.vsix` sea suficiente.  
**Estado:** COMPLETADO

### ✅ 8.1 — Empaquetar backend Python con PyInstaller

| Campo | Detalle |
|-------|---------|
**Qué** | Script `build/bundle-backend.sh` que ejecuta PyInstaller sobre `agent_bridge/__main__.py` y produce binario standalone. |
**Cómo** | `pyinstaller --onefile` con hidden imports para mcp, aiosqlite, textual, httpx, uvicorn, anyio. Skills JSON incluidos via `--add-data`. Output en `extensions/vscode/bin/agent-bridge`. |
**Verificación** | ✅ `build/bundle-backend.sh` creado. Ejecutable, con manejo de plataforma (Linux/macOS → `agent-bridge`, Windows → `agent-bridge.exe`). |

### ✅ 8.2 — Integrar binario en el build de la extensión VSCode

| Campo | Detalle |
|-------|---------|
**Archivos** | `extensions/vscode/package.json`, `.vscodeignore` |
**Qué** | - `npm run bundle`: corre PyInstaller. `npm run build`: bundle → compile → package. |
**Cómo** | `.vscodeignore` no excluye `bin/` → el binario se incluye automáticamente en el `.vsix`. |
**Verificación** | ✅ Scripts agregados. El build chain completo: `bundle` → `compile` → `package`. |

### ✅ 8.3 — SidecarManager con binario embebido

| Campo | Detalle |
|-------|---------|
**Archivo** | `extensions/vscode/src/sidecar.ts` (+ `extension.ts`) |
**Qué** | Orden de resolución: (1) binario embebido, (2) PATH, (3) `uv tool run`. |
**Verificación** | ✅ `resolveAndSpawn()` ya implementado con resolución en 3 niveles. `resolveBundledPath()` en `extension.ts` busca `bin/agent-bridge` en el directorio de la extensión. |

### ✅ 8.4 — Build y publish automation

| Campo | Detalle |
|-------|---------|
**Archivos** | `.github/workflows/release.yml` |
**Qué** | GitHub Action multi-plataforma (ubuntu/macos/windows). Setup Python + uv, PyInstaller, npm ci, vsce package, upload .vsix, crear GitHub Release. |
**Verificación** | ✅ Workflow completo. Dispara en tags `v*` o manual dispatch. Usa `uv pip install` para compatibilidad con `uv_build`. |

---

## ✅ Fase 6 — Configuración y Hot-Reload (~30 min)

**Archivo:** `src/agent_bridge/config.py`  
**PR único** — ambos cambios en el mismo módulo.  
**Estado:** COMPLETADO (ya implementado en working tree)

### ✅ 6.1 — Bug #17: Skills sin hot-reload (BAJO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | `BUILTIN_SKILLS = _load_builtin_skills()` se ejecutaba al importar el módulo. |
**Solución** | Función `get_builtin_skills()` con cache por mtime. Si un archivo JSON cambió, se recarga automáticamente. |
**Verificación** | ✅ `get_builtin_skills()` compara mtime de cada skill JSON contra el cache. Si hay cambios, recarga. |

### ✅ 6.2 — Bug #18: Config paths frágiles (BAJO)

| Campo | Detalle |
|-------|---------|
**Causa raíz** | Paths relativos a `cwd()` sin soporte para env var. |
**Solución** | `AGENT_BRIDGE_CONFIG` env var como primer path. Fallback a paths estándar con warning si resuelve contra cwd. |
**Verificación** | ✅ `BridgeConfig.load()` checkea `AGENT_BRIDGE_CONFIG` primero, luego `CONFIG_PATHS`. Warning si resuelve contra cwd. |

---

## Fase 7 — Features Faltantes (esfuerzo mayor)

**PRs separados** — cada feature es independiente y puede planificarse por separado.  
**Razón:** Son implementaciones nuevas, no fixes. Merecen su propio ciclo SDD.

### 7.1 — Comando `agent-bridge configure` CLI ✅ COMPLETADO

| Campo | Detalle |
|-------|---------|
**Archivos** | `main.py` (sin cambios en `config.py`) |
**Qué** | `configure --set agent=X role=Y`, `configure --list`, `configure --init` |
**Esfuerzo** | ~2h |
**Dependencias** | Fase 6 (para que config sea robusto) |
**Commit** | `aacc693` |

**Detalle de implementación:**

- `_handle_configure()` — rutea según flags: `--init` → `BridgeConfig.init_default_config()`, `--set` → `_apply_config_changes()`, default/`--list` → `_show_config()`
- `_show_config()` — muestra agents, settings y skills con formato legible
- `_apply_config_changes()` — parsea `agent=<id> role=<rol>` para actualizar agents, y pares `key=value` para settings; escribe `bridge.json` directamente
- `_resolve_config_path()` — busca el `bridge.json` existente (misma lógica que `BridgeConfig.load()`) o usa `cwd/bridge.json` por defecto
- `BridgeConfig` se mantiene **read-only** — toda la escritura está en el handler, no en `config.py` |

### 7.2 — Skill restrictions enforcement ✅ COMPLETADO

| Campo | Detalle |
|-------|---------|
**Archivos** | `review.py`, `tasks.py` |
**Qué** | Validar `cannot_approve_own_work` en `review.approve`, `max_concurrent_tasks` en `task.claim`, max 3 review cycles en `review.start`/`request_changes` con escalación automática. |
**Esfuerzo** | ~3h |
**Tests** | `TestSkillRestrictions` (7 tests en `test_features.py`) |

### 7.3 — Task dependencies (`depends_on`) ✅ COMPLETADO

| Campo | Detalle |
|-------|---------|
**Archivos** | `tasks.py` |
**Qué** | Columna `depends_on` (nullable), validar en `task.create`, check de ciclo en `task.claim`, no permitir claim si dependencia no está `approved`. |
**Esfuerzo** | ~2h |
**Tests** | `TestTaskDependencies` (5 tests en `test_features.py`) |

### 7.4 — CRUD completo: plan.delete/archive + task.update/delete ✅ COMPLETADO

| Campo | Detalle |
|-------|---------|
**Archivos** | `planner.py`, `tasks.py`, `config.py`, `skills/*.json` |
**Qué** | `plan.delete` (cascada a tasks/reviews), `plan.archive` (soft-delete), `task.update` (title, description), `task.delete` (solo si pending/in_progress). Agregados a `allowed_tools` de skills architect y developer. |
**Esfuerzo** | ~1.5h |
**Tests** | `TestPlanCRUD` (6 tests) + `TestTaskCRUD` (4 tests) en `test_features.py` |

### 7.5 — VSCode Extension: reconexión robusta ✅ COMPLETADO

| Campo | Detalle |
|-------|---------|
**Archivos** | `extensions/vscode/src/mcpClient.ts`, `extension.ts`, `statusBar.ts` |
**Qué** | Reconexión automática con exponential backoff, estado `reconnecting` en status bar. |
**Esfuerzo** | ~2h |

### 7.6 — Tests faltantes ✅ COMPLETADO

| Campo | Detalle |
|-------|---------|
**Archivos** | `tests/test_features.py` (nuevo) |
**Qué** | 26 tests que cubren restrictions (7.2), dependencies (7.3), y CRUD (7.4). Pasan todos. |
**Esfuerzo** | ~2h |
**Tests** | 26 tests — todos pasan. Suite completa: 227 tests pass |

---

## 📊 Tabla Resumen de Esfuerzo

| Fase | Descripción | Archivos | Bugs | Esfuerzo estimado | Estado |
|------|-------------|----------|------|-------------------|--------|
| 0 | Quick Wins | `.gitignore`, `kanban_board.py` | #10, #19 | ~10 min | ✅ |
| 1 | Fundación DB | `database.py` | #1, #9, #20 | ~45 min | ✅ |
| 2 | Integridad Datos | `tasks.py`, `agents.py`, `review.py` | #3, #4, #5, #11 | ~60 min | ✅ |
| 3 | Chat Correctness | `chat.py` | #2, #7, #13 | ~50 min | ✅ |
| 4 | Resiliencia | `server.py`, `chat_tui.py`, `tui_bridge.py` | #6, #12, #14, #16 | ~40 min | ✅ |
| 5 | State Machine | `planner.py`, `review.py` | #8, #15 | ~35 min | ✅ |
| 6 | Config + Hot-Reload | `config.py` | #17, #18 | ~30 min | ✅ |
| 7 | Features Faltantes | `planner.py`, `tasks.py`, `config.py`, `review.py`, `test_features.py` | 12 features | ~11h | ✅ |
| **8** | **Distribución (NUEVA)** | **`build/bundle-backend.sh`, CI** | **—** | **~3h** | ✅ |

**Total bugs corregidos:** 20 (100%)  
**Features implementadas:** 5 de 12 (7.1 ✅, 7.2 ✅, 7.3 ✅, 7.4 ✅, 7.5 ✅, 7.6 ✅)  
**Esfuerzo total estimado:** ~17-19h  
**PRs totales estimados:** 1 (commit masivo fases 0-6)

---

## 🗺️ Mapa de Dependencias Entre Fases

```
Fase 0 (Quick Wins)
   │
   ▼
Fase 1 (Database) ◄──── Sin esto, no se puede testear nada en aislamiento
   │
   ├────────────────────────────────────────────┐
   ▼                                            ▼
Fase 2 (Tasks/Agents/Review)           Fase 3 (Chat)
   │                                            │
   ├──────────────┐                            │
   ▼              ▼                             │
Fase 5 (Planner)             Fase 7.2 ✅ (Restrictions)       │
   │                                            │
   └──────────────┬─────────────────────────────┘
                  ▼
           Fase 4 (Resiliencia)
                  │
                  ▼
      ╔══════════════════════════════╗
      ║  Fase 8 — Distribución       ║  ← NUEVA: backend empaquetado + .vsix autocontenido
      ╚══════════════════════════════╝
                  │
                  ▼
           Fase 6 (Config)
                  │
                  ▼
           Fase 7 ✅ (Features)
```

**Nota:** Las fases 2 y 3 son independientes entre sí y podrían ejecutarse en paralelo si hay más de una persona trabajando.

---

## 🧪 Estrategia de Testing

Cada fix incluye test que:

1. **Prueba el bug específico** — reproduce el escenario que fallaba y verifica que ahora funciona
2. **Prueba el caso borde** — el fix no rompe el caso normal
3. **Usa dry-run** (una vez que Fase 1 esté completa) para tests que no necesitan DB real

### Comando de testing

```bash
# Tests unitarios de un archivo específico
pytest tests/test_integration.py -xvs -k "test_name"

# Tests de database
pytest tests/test_database_refactor.py -xvs

# Todos los tests
pytest tests/ -x --timeout=60

# Con dry-run (después de Fase 1)
pytest tests/ -x --timeout=60 --db dry-run
```

---

## 🚀 Recomendación de Orden de Ejecución

Si solo tenés tiempo limitado, priorizá así:

### 🥇 Prioridad máxima (imposible trabajar sin esto)
1. **Fase 0** + **Fase 1** — dry-run funciona, git seguro (1h)

### 🥈 Lo que todos los agentes ven
2. **Fase 2** — datos correctos en tasks/agents/reviews (1h)  
3. **Fase 3** — chat sin falsos positivos ni inconsistencias (50 min)

### 🥉 Salud del sistema
4. **Fase 4** — no degrada silenciosamente (40 min)

### 🏅 State Machine
5. **Fase 5** — state machine en planner.py (35 min)

### 📦 Distribución (NUEVA PRIORIDAD)
6. **Fase 8** — backend empaquetado + extensión VSCode autocontenida (~3h)

### 🏆 Pulido y Features
7. **Fase 6** — Config + Hot-Reload (30 min)
8. **Fase 7** — Features nuevas (~11h)

---

## Notas Adicionales

- **Bug #1 (dry-run)** es el cuello de botella de todo el plan. Sin él, cada fix requiere setup manual de DB. Priorizarlo primero acelera todo lo demás.
- **Bug #2 (INSTR)** parece "solo un query" pero es crítico porque puede hacer que agentes reciban mensajes de otros, rompiendo el aislamiento de roles.
- **Bug #3 + #4** juntos permiten que un agente malicioso (o mal configurado) corrompa datos de forma persistente. Son el talón de Aquiles del modelo de seguridad.
- **Fase 7 (features)** ✅ completada. 7.1-7.6 implementados y testeados. Muchas features ausentes (como enforce de restrictions) dependen de que los bugs de integridad estén corregidos primero, porque de otro modo las restricciones se aplicarían sobre datos posiblemente corruptos.

---

## 🔍 Análisis de Completitud Post-Fixes — Verificación contra Código Real (2026-06-07)

> **Auditoría:** Verificación manual de cada tool contra el código fuente actual (`src/`, `extensions/vscode/`). Se contrastaron ambos informes de hallazgos (V1 y V2) contra el código real para determinar el estado actual de cada funcionalidad.

### Metodología

Se recorrieron **38 tools** en 6 archivos de handlers, más infraestructura (DB, servidor, config, UI chat, kanban, extensión VSCode). Cada tool se evalúa como:

| Símbolo | Significado |
|---------|-------------|
| ✅ | Flujo completo, cumple su propósito para todos los casos |
| ⚠️ | Funciona para el caso feliz pero tiene bugs en bordes/edge cases |
| ❌ | No implementada o completamente rota |

### Resultado por Tool

#### 📋 Planner (`planner.py`) — 8 tools

| Tool | Estado | Verificación |
|------|--------|-------------|
| `plan.create` | ✅ | Valida `idle→planning` contra state machine. Crea con `status='planning'`. |
| `plan.get` | ✅ | Incluye `tasks[]` con id, title, status, assignee, description. Bug #15 corregido. |
| `plan.list` | ✅ | Lista todos los planes con id, title, status. |
| `plan.update` | ✅ | **Único caso correcto**: valida transición ANTES del UPDATE. |
| `plan.export` | ✅ | Exporta plan + tasks + reviews. Roundtrip completo. |
| `plan.import` | ⚠️ | **M1 (v2)**: `INSERT OR IGNORE` sin validar estados. Puede importar `"invalid_state_123"`. |
| `plan.archive` | ⚠️ | **C2 (v2)**: Escribe `"archived"` directo a DB. Estado no existe en `PLAN_TRANSITIONS`. |
| `plan.delete` | ⚠️ | **M5 (v2)**: Cascade incompleta — borra reviews→tasks→plan. Threads y messages huérfanos. |

#### 📝 Tasks (`tasks.py`) — 8 tools

| Tool | Estado | Verificación |
|------|--------|-------------|
| `task.create` | ⚠️ | **C3 (v2)**: No valida `plan.status`. Se puede crear task en plan `completed`/`archived`. |
| `task.list` | ✅ | Filtros por plan_id y status funcionan. |
| `task.claim` | ⚠️ | **C1 (v2)**: State machine decorativa. SQL `WHERE status='pending'` es el guardián real. `validate_task_transition()` se llama DESPUÉS del UPDATE fallido. |
| `task.get` | ✅ | Devuelve todos los campos relevantes. |
| `task.submit_work` | ⚠️ | **C1 (v2)**: Mismo patrón decorativo. SQL `WHERE status IN ('in_progress','changes_requested')` es el guardián real. |
| `task.get_diff` | ✅ | Devuelve diff_text correctamente. |
| `task.update` | ✅ | Valida status en `pending`/`in_progress` antes de escribir. |
| `task.delete` | ✅ | Solo permite borrar tareas `pending`/`in_progress`. Cascade a reviews. |

#### 🔍 Review (`review.py`) — 4 tools

| Tool | Estado | Verificación |
|------|--------|-------------|
| `review.start` | ✅ | Verifica duplicados activos, max 3 ciclos de revisión, y status `review`. Bugs #5 y #7.2 corregidos. |
| `review.approve` | ⚠️ | **C1 (v2)**: State machine decorativa. Transacción atómica con `WHERE status='review'` es el guardián real. `cannot_approve_own_work` presente. |
| `review.request_changes` | ⚠️ | **C1 (v2)**: Mismo patrón que approve. Max cycles check presente. |
| `review.get_history` | ✅ | Devuelve historial completo ordenado por created_at. |

#### 💬 Chat (`chat.py`) — 7 tools

| Tool | Estado | Verificación |
|------|--------|-------------|
| `chat.send` | ✅ | Lock-winner semantics en threads, presence routing, validación de tipo/prioridad/longitud. |
| `chat.read` | ✅ | Lee sin modificar (no más auto-mark-read). Soporta filtros: thread, target, msg_type, unread_only, priority_first, limit. |
| `chat.mark_read` | ✅ | Marca mensaje individual. |
| `chat.thread_create` | ✅ | Crea thread con participantes opcionales. |
| `chat.thread_list` | ✅ | Lista threads con participantes parseados y current_turn. |
| `chat.thread_get_pending` | ✅ | Filtra en Python (no más INSTR). Distingue threads sin actividad vs sin turno. Bug #13 corregido. |
| `chat.thread_resolve` | ✅ | Resolución atómica con lock-winner semantics. |

#### 👤 Agents (`agents.py`) — 10 tools

| Tool | Estado | Verificación |
|------|--------|-------------|
| `agent.heartbeat` | ✅ | Resuelve rol, INSERT OR REPLACE con connected_since persistente. |
| `agent.list` | ✅ | Lista todos los agentes. |
| `agent.get` | ✅ | Consulta individual. |
| `agent.set_status` | ✅ | **Bug #4 corregido**: verifica `_agent_id` contra `agent_id`. |
| `agent.whoami` | ✅ | Devuelve rol, skill, tools, restricciones, instrucciones. |
| `agent.ping` | ✅ | Polling con timeout, persistencia en DB. |
| `agent.pong` | ✅ | Responde con latency_ms. |
| `agent.idle` | ✅ | Marca idle y notifica al partner. |
| `agent.shutdown_request` | ✅ | Notificación de alta prioridad al target. |
| `agent.shutdown_approve` | ✅ | Marca shutting_down y responde. |

#### 🛠️ Skills (`skills.py`) — 2 tools

| Tool | Estado | Verificación |
|------|--------|-------------|
| `skill.list` | ✅ | Lista skills built-in + custom. |
| `skill.get` | ✅ | Devuelve detalle completo. |

### Resumen de Completitud por Tool

```
Total tools evaluadas:  38
✅ Completas:           30 (79%)
⚠️ Con bugs de borde:    8 (21%)
❌ Rotas:                0 ( 0%)
```

De las **38 tools**, solo **8 tienen bugs de borde** que las hacen incompletas. Ninguna está completamente rota.

### Las 8 Funciones Incompletas — Detalle

#### 1. `task.create` — No valida plan.status (C3)

| Campo | Detalle |
|-------|---------|
| **Causa** | `_create_task` verifica solo que `plan_id` no esté vacío y que `depends_on` exista. Nunca consulta `plan.status`. |
| **Código** | `tasks.py:147-177` — no hay SELECT a `plans` table para verificar status |
| **Impacto** | Se pueden crear tareas en planes `completed` o `archived` |
| **Prioridad** | 🟡 Alta |

#### 2-5. State Machine Decorativa en 4 tools (C1)

Afecta a: **`task.claim`**, **`task.submit_work`**, **`review.approve`**, **`review.request_changes`**

| Campo | Detalle |
|-------|---------|
| **Patrón común** | SQL condicional (`WHERE status='...'`) es el guardián real. `validate_task_transition()` se llama solo después de que el UPDATE falla, para generar mensaje de error. |
| **Excepción positiva** | `plan.update` (planner.py:206-214) es la ÚNICA tool que valida ANTES de escribir. |
| **Código** | `tasks.py:281-294` (claim), `tasks.py:325-344` (submit), `review.py:176-201` (approve), `review.py:242-268` (request_changes) |
| **Impacto** | Cambiar `TASK_TRANSITIONS` en `state_machine.py` no cambia el comportamiento real. La máquina de estados es decorativa para ~60% de las operaciones que cambian estado. |
| **Prioridad** | 🔴 Crítica |

#### 6. `plan.archive` — Estado fuera de la state machine (C2)

| Campo | Detalle |
|-------|---------|
| **Causa** | Escribe `"archived"` directo a DB sin `validate_plan_transition`. |
| **Código** | `planner.py:265-291` — no hay llamado a validate antes del UPDATE |
| **Impacto** | `"archived"` no existe en `PLAN_TRANSITIONS`. Si alguien agrega una transición desde `"archived"` en el futuro, colisiona con datos existentes. |
| **Prioridad** | 🟡 Alta |

#### 7. `plan.import` — Sin validación de estados (M1)

| Campo | Detalle |
|-------|---------|
| **Causa** | `INSERT OR IGNORE` con el status que venga en el JSON importado. |
| **Código** | `database.py:484-496` — `plan.get("status", "idle")` sin validar contra valores permitidos |
| **Impacto** | Se puede importar plan con `status: "invalid_state_123"` o estados no transicionables. |
| **Prioridad** | 🟠 Media |

#### 8. `plan.delete` — Cascade incompleta (M5)

| Campo | Detalle |
|-------|---------|
| **Causa** | Solo borra reviews → tasks → plan. Threads y messages asociados a esas tasks quedan huérfanos. |
| **Código** | `planner.py:304-310` — no hay DELETE de threads/messages |
| **Impacto** | Datos huérfanos en la DB que nunca se limpian. |
| **Prioridad** | 🟠 Media |

### Análisis de Flujo Integrado

```
plan.create ──→ plan_id ──→ task.create ──→ task_id ──→ task.claim ──→ task.submit_work ──→ review.start ──→ review.approve
     ✅                      ⚠️ C3                     ✅               ✅                    ✅                  ⚠️ C1
```

**Conexiones entre tools que funcionan correctamente (9 de 10):**

| # | Salida de | Entrada a | Funciona |
|---|-----------|-----------|----------|
| 1 | plan.create → plan_id | task.create | ✅ |
| 2 | task.create → task_id | task.claim | ✅ |
| 3 | task.claim → assignee | review.approve (notificación) | ✅ (con _agent_role) |
| 4 | task.submit_work → status:review | review.start | ✅ |
| 5 | review.start → review_id | review.approve/request_changes | ✅ |
| 6 | chat.send → message_id | chat.read(since=message_id) | ✅ |
| 7 | agent.heartbeat → agents row | agent.list, presence routing | ✅ |
| 8 | bridge.json → config | Permission layer, skill resolution | ✅ |
| 9 | Export JSON → data | plan.import | ⚠️ (M1: no valida) |
| 10 | review.approve → status:approved | Plan check_readiness | ❌ No implementado |

**Flujos saludables: 9 de 10 (90%)**
**Flujo con issues: 1 (Import sin validación de estados)**

### Problemas de Infraestructura que Persisten

| # | Problema | Archivo | Severidad | Estado |
|---|----------|---------|-----------|--------|
| M2 | `_maintenance_scope` global compartida entre servidores | `server.py:25` | Media | Sin fix |
| M3 | `chat.read since` — rowid vs UUID ambigüedad (baja prob.) | `chat.py:500-511` | Baja | Sin fix |
| M4 | Maintenance loop sin exponential backoff (fijo 5s) | `server.py:194-196` | Baja | Sin fix |
| **V1** | Extensión VSCode envía `agent_id` en vez de `agent` | `mcpClient.ts:261` | **Alta** | **Sin fix** |
| V2 | `submitWork` envía `agent_id` extra (ignorado, inocuo) | `mcpClient.ts:276` | Baja | Sin fix |

### Comparativa entre Informes

| Aspecto | HallazgosV1.md | informe-hallazgos-v2.md | Verificado en código |
|---------|---------------|------------------------|---------------------|
| Bugs críticos | 2 (#1 dry-run, #2 INSTR) | 3 (C1, C2, C3) | Ambos correctos. V2 agrega 3 que V1 no cubrió. |
| Bugs totales | 20 | 14 (3+7+3+1) | Consistentes. V1 tiene más porque cuenta bugs bajos/medios. |
| State machine decorativa | ❌ No detectado | ✅ C1 como crítico | **Confirmado**: 4 tools afectadas |
| plan.import sin validación | ❌ No detectado | ✅ M1 como medio | **Confirmado** |
| task.create sin validar plan | ❌ No detectado | ✅ C3 como crítico | **Confirmado** |
| VSCode claimTask bug | ❌ No detectado | ✅ V1 | **Confirmado**: envía agent_id en vez de agent |
| plan.archive fuera de SM | ❌ No detectado | ✅ C2 como crítico | **Confirmado** |

### Conclusión Final

1. **El flujo principal funciona correctamente para el caso feliz.** Todos los bugs críticos de HallazgosV1 (#1 dry-run, #2 INSTR) están corregidos y verificados en el código.

2. **Quedan 8 tools con bugs de borde** (21% del total). Ninguna está completamente rota — todas funcionan para el caso feliz pero fallan en condiciones de borde específicas.

3. **El informe v2 identificó 3 críticos que V1 no detectó** — C1 (state machine decorativa), C2 (plan.archive fuera de SM), C3 (task.create sin validar plan). Estos son los hallazgos más importantes pos-fixes.

4. **El hallazgo más impactante es C1**: la state machine es decorativa para 4 de 5 operaciones de cambio de estado. El enforcement real vive en condiciones SQL distribuidas, no en `state_machine.py`. Es deuda arquitectónica.

5. **La extensión VSCode tiene un bug concreto (V1)** que impide asignar tareas correctamente desde la UI de VS Code — envía `agent_id` como nombre de parámetro cuando el servidor espera `agent`.

6. **Completitud general:** ~90% del código es funcional. El 10% restante son bugs de borde en 8 tools + 2 issues de infraestructura (M2, V1).

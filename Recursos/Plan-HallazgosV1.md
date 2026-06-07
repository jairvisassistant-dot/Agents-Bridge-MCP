# Plan de Trabajo — Corrección de Hallazgos V1

> **Generado:** 2026-06-06  
> **Última actualización:** 2026-06-07  
> **Origen:** [HallazgosV1.md](./HallazgosV1.md) — 20 hallazgos (2 críticos, 5 altos, 7 medios, 6 bajos) + 12 features ausentes  
> **Estrategia:** Agrupar por archivo para minimizar context switching, fundación primero para habilitar testing
> **Estado general:** Fases 0–6 completadas ✅ | Fase 7 parcial | Fase 8 pendiente

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
| **7** | Features Faltantes | ⚠️ Parcial (7.1, 7.5 hechos) |
| **8** | Distribución: Extensión VSCode | ❌ Pendiente |

**Commit:** `TBD` (fases 0–6 en un solo commit masivo)

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

## Fase 8 — Distribución: Extensión VSCode Autocontenida (~3h)

**Archivos:** `extensions/vscode/src/sidecar.ts`, `extensions/vscode/src/config.ts`, `extensions/vscode/package.json`, + nuevo build script  
**PR único** — toda la cadena de distribución.  
**Razón:** Hoy la extensión VSCode requiere que el backend Python esté instalado por separado. El objetivo es que instalar el `.vsix` sea suficiente.

### 8.1 — Empaquetar backend Python con PyInstaller

| Campo | Detalle |
|-------|---------|
**Qué** | Crear script `build/bundle-backend.sh` que ejecute PyInstaller sobre `agent_bridge/__main__.py` y produzca un binario standalone `agent-bridge` |
**Cómo** | Usar `pyinstaller --onefile --name agent-bridge src/agent_bridge/__main__.py`. El binario incluye Python + dependencias + código. Sin dependencia externa de Python en la máquina del usuario. |
**Riesgo** | PyInstaller no siempre captura imports dinámicos. Verificar que mcp, aiosqlite, textual, httpx, uvicorn se incluyan explícitamente. El binario pesa ~15-30MB. |
**Verificación** | `./dist/agent-bridge start --dry-run` funciona en una máquina SIN Python instalado. |

### 8.2 — Integrar binario en el build de la extensión VSCode

| Campo | Detalle |
|-------|---------|
**Archivos** | `extensions/vscode/package.json`, nuevo `extensions/vscode/build.mjs` |
**Qué** | Agregar script `build` que: (1) corre PyInstaller, (2) copia el binario a `extensions/vscode/bin/`, (3) compila TypeScript, (4) genera el `.vsix` con `vsce package` |
**Cómo** | Usar `vsce` con `package.json` que incluya `bin/` en `files`. El binario se distribuye dentro del `.vsix`. |
**Dependencias** | 8.1 (tener el binario) |
**Esfuerzo** | 1h |
**Verificación** | `npm run package` genera un `.vsix` que contiene el binario. |

### 8.3 — Modificar SidecarManager para usar binario embebido

| Campo | Detalle |
|-------|---------|
**Archivo** | `extensions/vscode/src/sidecar.ts` |
**Qué** | El `SidecarManager.resolveAndSpawn()` debe probar en este orden: (1) binario embebido en `extensions/vscode/bin/agent-bridge`, (2) `agent-bridge` en PATH, (3) `uv tool run agent-bridge` |
**Cómo** | Usar `context.extensionPath` para resolver la ruta al binario dentro de la extensión instalada. |
**Dependencias** | 8.2 |
**Esfuerzo** | Bajo — ~20 líneas nuevas en `sidecar.ts` |
**Verificación** | La extensión en un ambiente limpio (sin Python, sin uv) arranca el sidecar correctamente usando el binario embebido. |

### 8.4 — Build y publish automation

| Campo | Detalle |
|-------|---------|
**Archivos** | `.github/workflows/release.yml` (nuevo) |
**Qué** | GitHub Action que: (1) setup Python + uv, (2) build PyInstaller, (3) compila TS, (4) package .vsix, (5) lo sube como release artifact |
**Dependencias** | 8.1, 8.2 |
**Esfuerzo** | 1h |
**Verificación** | Release creado automáticamente con .vsix descargable. |

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

### 7.2 — Skill restrictions enforcement

| Campo | Detalle |
|-------|---------|
**Archivos** | `review.py`, `tasks.py`, `agents.py` (permission layer) |
**Qué** | Validar `cannot_approve_own_work` en `review.approve`, `max_concurrent_tasks` en `task.claim`, max 3 review cycles en `review.start`/`request_changes` con escalación automática. |
**Esfuerzo** | ~3h |
**Dependencias** | Fase 2 (review/task fixes), Fase 5 (state machine) |

### 7.3 — Task dependencies (`depends_on`)

| Campo | Detalle |
|-------|---------|
**Archivos** | `tasks.py`, `database.py` (migración v7) |
**Qué** | Agregar columna `depends_on` (nullable, FK a tasks.id), validar en `task.create`, check de ciclo en `task.claim`, no permitir claim si dependencia no está `approved`. |
**Esfuerzo** | ~2h |
**Dependencias** | Fase 1 (migración), Fase 2.1 (task.claim) |

### 7.4 — CRUD completo: plan.delete/archive + task.update/delete

| Campo | Detalle |
|-------|---------|
**Archivos** | `planner.py`, `tasks.py` |
**Qué** | `plan.delete` (cascada a tasks/reviews), `plan.archive` (soft-delete), `task.update` (title, description), `task.delete` (solo si pending/in_progress) |
**Esfuerzo** | ~1.5h |
**Dependencias** | Fase 2, Fase 5 |

### 7.5 — VSCode Extension: reconexión robusta

| Campo | Detalle |
|-------|---------|
**Archivos** | `extensions/vscode/src/extension.ts` |
**Qué** | Agregar reconexión automática con exponential backoff (similar a ChatTUI), mostrar estado de conexión en status bar, pausar polling cuando disconnected. |
**Esfuerzo** | ~2h |
**Dependencias** | Ninguna |

### 7.6 — Tests faltantes

| Campo | Detalle |
|-------|---------|
**Archivos** | `tests/` |
**Qué** | Agregar tests unitarios para cada fix a medida que se implementa. Tests de regresión para bugs críticos. |
**Esfuerzo** | Distribuido a lo largo de todas las fases |
**Dependencias** | Cada fase incluye sus tests |

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
| 7 | Features Faltantes | Múltiples | 12 features | ~11h | ⚠️ Parcial |
| **8** | **Distribución (NUEVA)** | **`sidecar.ts`, build script, CI** | **—** | **~3h** | ❌ |

**Total bugs corregidos:** 20 (100%)  
**Features implementadas:** 2 de 12 (7.1 configure ✅, 7.5 reconexión VSCode ✅)  
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
Fase 5 (Planner)  Fase 7.2 (Restrictions)       │
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
           Fase 7 (Features)
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
- **Fase 7 (features)** está deliberadamente al final. Muchas features ausentes (como enforce de restrictions) dependen de que los bugs de integridad estén corregidos primero, porque de otro modo las restricciones se aplicarían sobre datos posiblemente corruptos.

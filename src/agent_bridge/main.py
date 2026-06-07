"""Agent Bridge — CLI entry point."""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import anyio

from agent_bridge.config import BridgeConfig
from agent_bridge.server import create_server
from agent_bridge.state.database import Database

logger = logging.getLogger(__name__)


def _handle_start(args: argparse.Namespace) -> None:
    """Handle the `start` subcommand: launch SSE server +/or TUI."""
    db_path = args.db_path
    port = args.port
    dry_run = getattr(args, "dry_run", False)

    # ── UI-only mode: just launch the TUI ──────────────────────────
    if args.ui_only:
        logger.info("Starting TUI standalone (direct DB mode, no SSE server)")
        if getattr(args, "kanban", False):
            from agent_bridge.ui.kanban_tui import main as tui_main
        else:
            from agent_bridge.ui.chat_tui import main as tui_main

        tui_main(db_path=db_path, dry_run=dry_run)
        return

    # ── Headless mode: just launch SSE server ──────────────────────
    if args.headless:
        logger.info("Starting headless SSE server on port %d", port)
        _run_sse_server(db_path=db_path, host="127.0.0.1", port=port, dry_run=dry_run)
        return

    # ── Default: SSE server in subprocess + TUI in this process ───
    logger.info("Starting Agent Bridge (SSE on port %d + TUI)", port)
    cmd = [
        sys.executable,
        "-m",
        "agent_bridge",
        "--db-path",
        db_path,
        "--transport",
        "sse",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    if dry_run:
        cmd.append("--dry-run")
    sse_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait briefly for the SSE server to start
    import time

    time.sleep(1)

    try:
        if getattr(args, "kanban", False):
            from agent_bridge.ui.kanban_tui import main as tui_main
        else:
            from agent_bridge.ui.chat_tui import main as tui_main

        tui_main(db_path=db_path, dry_run=dry_run)
    finally:
        logger.info("Shutting down SSE server (PID %d)", sse_proc.pid)
        sse_proc.terminate()
        try:
            sse_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sse_proc.kill()
            sse_proc.wait()


def _run_sse_server(
    db_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    server=None,
    init_db=None,
    dry_run: bool = False,
) -> None:
    """Run the MCP server in SSE mode in the current process.

    Two calling conventions:
      1. _run_sse_server(db_path=..., host=..., port=...)  — creates server internally
      2. _run_sse_server(host=..., port=..., server=server, init_db=init_db) — uses existing
    """
    if server is None or init_db is None:
        from agent_bridge.server import create_server

        server, init_db = create_server(
            db_path=db_path or "bridge.db",
            agent_id=os.environ.get("AGENT_BRIDGE_ID"),
            dry_run=dry_run,
        )

    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        await init_db()
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    uvicorn.run(app, host=host, port=port)


# ── Init subcommand ────────────────────────────────────────────────


SKILL_TEMPLATES = {
    "dev.Skill": """\
---
name: agent-bridge-dev
description: "Trigger: @dev.Skill, @desarrollador. Conecta OpenCode al Agent Bridge como rol Desarrollador."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "2.0"
---

## Activation Contract

Ejecutar cuando el humano invoque `@dev.Skill`. Conecta esta terminal al Agent Bridge como el agente **Desarrollador**.

## Principios de operación

- **Leer antes de implementar**: nunca tocar código sin entender completamente la tarea.
- **Preguntar antes de decidir**: cualquier decisión de diseño o arquitectura va al arquitecto primero.
- **Reportar con precisión**: el humano y el arquitecto deben poder revisar tu trabajo sin adivinar qué hiciste.
- **Git limpio**: commits atómicos y descriptivos. Nunca forzar push ni resolver conflictos sin avisar.
- **No inventar alcance**: si la tarea no lo dice, no lo hacés.

---

## Hard Rules

- **Siempre hacer git pull** antes de empezar a trabajar en cualquier tarea.
- **Siempre hacer git push** al completar una tarea antes de reportarla.
- **Nunca trabajar sin estar conectado** al bridge. Si la conexión falla, reportar y detenerse.
- **Tools permitidas**: `task.list`, `task.get`, `task.claim`, `task.submit_work`, `chat.*`, `agent.*`, `skill.*`.
- **Si el humano o el arquitecto escriben**: atender inmediatamente, pausar el trabajo en curso si hace falta.
- **Al inicio de cada respuesta**: llamar `agent.heartbeat` + `chat.read` para mantenerse visible y ver mensajes nuevos.
- **Nunca tomar decisiones de arquitectura** — si algo no está claro o requiere un diseño, parar y preguntar.

---

## Protocolo de comunicación en TUI

- **Al conectarse**: ejecutar `chat.read` + `chat.thread_get_pending(agent_name="desarrollador")` para ver si hay algo sin responder.
- **@nombre siempre** al hablar con alguien específico (`@arquitecto`, `@humano`).
- **Brevedad**: máximo 4 líneas por mensaje. Los detalles del trabajo van en `task.submit_work`, no en el chat.
- **Acuse de recibo**: ante cualquier mensaje, responder aunque sea "viendo..." antes de procesar.
- **Threads**: para conversaciones de más de 2 intercambios con el arquitecto, usar `chat.thread_create`.
- **Reportar al iniciar**: cuando tomás una tarea, avisarlo en TUI.
- **Reportar al finalizar**: usar el Formato de reporte de finalización antes de cualquier otra cosa.

### Protocolo de respuesta a ping

Cuando `chat.read` retorne mensajes, revisar si alguno tiene `text` que sea JSON con `"type": "ping"`:

1. Parsear el `ping_id`
2. Llamar inmediatamente: `agent.pong(ping_id="{ping_id}")`
3. NO publicar en el chat — el pong va directo a la DB
4. Continuar con el procesamiento normal

### Formato de reporte al tomar una tarea

```
🔧 Iniciando tarea "{título}" (ID: {task_id})
ETA estimado: [X minutos / X horas]
@arquitecto: comenzando implementación.
```

### Formato de reporte de finalización (OBLIGATORIO)

Publicar en TUI al terminar SIEMPRE, antes de hacer cualquier otra cosa:

```
✅ Tarea "{título}" completada (ID: {task_id})
Qué se hizo: [1-2 líneas concretas]
Archivos modificados: [N archivos — lista los más importantes]
Cómo verificar: [comando, pasos, o URL]
Ver detalle completo: task.get {task_id}
@arquitecto: listo para revisión.
@humano: podés revisar con task.get {task_id}
```

---

## Flujo de trabajo por escenario

### Escenario A — Hay tareas pendientes al conectarse

1. `task.list(status="pending")` para ver qué hay disponible.
2. Leer la tarea completa con `task.get` — COMPLETA, no solo el título.
3. Si la tarea está clara: tomar con `task.claim` y publicar reporte de inicio en TUI.
4. Si algo no está claro: ir al Escenario C antes de tomar la tarea.
5. Implementar siguiendo los criterios de aceptación definidos.
6. Al terminar: ir al Escenario E.

### Escenario B — No hay tareas pendientes

1. Publicar en TUI: `⏳ Sin tareas pendientes. @arquitecto: ¿hay algo en lo que pueda avanzar?`
2. Esperar instrucciones. No buscar trabajo por cuenta propia.
3. Si el arquitecto no responde, notificar también al `@humano`.

### Escenario C — La tarea tiene requisitos poco claros

Antes de tomar la tarea o de escribir una sola línea de código:

1. Identificar exactamente qué no está claro (criterio específico, archivo, patrón).
2. Publicar en TUI:
   `❓ Tarea {task_id} — necesito clarificación antes de arrancar`
   `Punto específico: [qué no está claro]`
   `@arquitecto: ¿me podés aclarar?`
3. Esperar respuesta. No improvisar.
4. Si el arquitecto actualiza la tarea: releerla completa antes de arrancar.

### Escenario D — Bloqueado durante la implementación

1. Detener el trabajo inmediatamente.
2. Documentar exactamente dónde y por qué estás bloqueado.
3. Publicar en TUI:
   `🚧 Bloqueado en tarea {task_id}`
   `Motivo: [qué encontré — específico]`
   `Necesito: [qué decisión o información falta]`
   `@arquitecto: ¿cómo procedo?`
4. Esperar respuesta. No continuar en otra dirección sin aval.

### Escenario E — Tarea completada

1. Verificar localmente que todo funciona según los criterios de aceptación.
2. `git add` de los archivos relevantes + `git commit` con mensaje descriptivo.
3. `git push`.
4. Llamar `task.submit_work` con el Formato de entrega.
5. Publicar el Formato de reporte de finalización en TUI.
6. Esperar revisión del arquitecto. No tomar otra tarea hasta recibir respuesta.

### Escenario F — El arquitecto solicita cambios

1. Leer el feedback completo con `task.get`.
2. Acusar recibo en TUI: `🔄 Recibí el feedback de tarea {task_id}. Revisando y corrijo.`
3. Implementar solo los cambios solicitados — nada más, nada menos.
4. Volver al Escenario E al terminar.
5. En el nuevo `task.submit_work`, indicar cómo se resolvió cada punto del feedback.

### Escenario G — Conflicto de git o push falla

1. NO intentar resolver automáticamente.
2. NO hacer force push bajo ninguna circunstancia.
3. Publicar en TUI:
   `⚠️ Conflicto de git en tarea {task_id}`
   `Error: [mensaje exacto]`
   `@humano: necesito instrucciones para resolver.`
4. Esperar instrucciones del humano.

### Escenario H — Llega un mensaje mientras trabajás

1. Pausar el trabajo en curso.
2. Acusar recibo: `👋 Recibí tu mensaje. Un momento.`
3. Atender el mensaje.
4. Si implica cambiar de prioridad: confirmar con el arquitecto antes de abandonar la tarea actual.

---

## Formato de entrega (task.submit_work)

```
## Resumen de implementación
[Qué se hizo en 2-3 oraciones — qué problema resolvió, cómo]

## Archivos modificados
- path/archivo.ext — [qué cambió y por qué]

## Archivos creados
- path/nuevo.ext — [qué hace]

## Cómo verificar
[Pasos concretos: comando, URL, o interacción]

## Criterios de aceptación — autoevaluación
- [x] Criterio 1: [cómo lo cumplí]
- [x] Criterio 2: [cómo lo cumplí]
- [ ] Criterio N: [si no lo cumplí, por qué y qué propongo]

## Notas para el revisor
[Decisiones no obvias, trade-offs, deuda técnica si la hay]
```

**Regla**: si no podés completar la autoevaluación, la tarea no está lista para entrega.

---

## Disciplina de commits

- Un commit por cambio lógico — no acumular todo al final.
- Formato: `tipo: descripción breve` (feat, fix, refactor, test, chore).
- Nunca commitear `.env`, configuración local, o binarios.

---

## Pasos de conexión

### 1. Verificar entorno
`which agent-bridge || uv tool list | grep agent-bridge`

### 2. Sincronizar repo
`git pull --rebase`

### 3. Verificar conexión
La conexión es automática vía MCP (`.mcp.json`). Solo verificar con `agent.heartbeat`.

### 4. Ver quién está online
`agent.list` — si el arquitecto está offline, avisarlo antes de tomar tareas.

### 5. Leer mensajes pendientes
`chat.read` + `chat.thread_get_pending(agent_name="desarrollador")`

### 6. Reportar disponibilidad
`chat.send(sender="desarrollador", text="🟢 Desarrollador conectado y listo")`

### 7. Consultar tareas pendientes
`task.list(status="pending")` — aplicar el flujo por escenario correspondiente.

### 8. Ciclo de trabajo
Implementar, reportar progreso, entregar con formato completo.

### 9. Al finalizar cada tarea
`git add [archivos] && git commit -m "tipo: descripción" && git push`
Luego: `task.submit_work` + reporte en TUI.
""",
    "architect.Skill": """\
---
name: agent-bridge-architect
description: "Trigger: @architect.Skill, @arquitecto. Conecta Claude Code al Agent Bridge como rol Arquitecto."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "2.0"
---

## Activation Contract

Ejecutar cuando el humano invoque `@architect.Skill`. Conecta esta terminal al Agent Bridge como el agente **Arquitecto**.

## Principios de operación

- **Explorar antes de planificar**: nunca crear tareas sin entender el estado actual del código.
- **Instrucciones ejecutables**: cada tarea debe ser tan específica que el dev pueda completarla sin adivinar.
- **TUI limpia**: publicar solo resúmenes en el chat. Los detalles completos viven en la DB.
- **Humano como árbitro**: escalar decisiones de producto o alcance. Resolver el resto de forma autónoma.
- **No implementar**: solo planificar, definir y revisar.

---

## Hard Rules

- **Siempre hacer git pull** antes de empezar.
- **Siempre hacer git push** al finalizar o completar un plan.
- **No tocar código** — ni un solo archivo de implementación.
- **Tools permitidas**: `plan.*`, `task.create`, `task.get_diff`, `review.*`, `chat.*`, `agent.*`, `skill.*`.
- **Máximo 3 ciclos de revisión** por tarea — si no se resuelve, escalar al humano.
- **Al inicio de cada respuesta**: llamar `agent.heartbeat` + `chat.read` para mantenerse visible y ver mensajes nuevos.

---

## Protocolo de comunicación en TUI

- **Al conectarse**: ejecutar `chat.read` + `chat.thread_get_pending(agent_name="arquitecto")` para ver si hay algo sin responder.
- **@nombre siempre** al hablar con alguien específico (`@desarrollador`, `@humano`).
- **Brevedad**: máximo 4 líneas por mensaje. Si es más largo, va a la DB y se referencia.
- **Acuse de recibo**: ante cualquier mensaje, responder aunque sea "viendo..." antes de procesar.
- **Notificar al dev**: toda tarea nueva o actualizada se notifica con `@desarrollador` + ID de referencia.
- **Threads**: para conversaciones bilaterales de más de 2 intercambios con el dev, usar `chat.thread_create`.

### Protocolo de respuesta a ping

Cuando `chat.read` retorne mensajes, revisar si alguno tiene `text` que sea JSON con `"type": "ping"`:

1. Parsear el `ping_id`
2. Llamar inmediatamente: `agent.pong(ping_id="{ping_id}")`
3. NO publicar en el chat — el pong va directo a la DB
4. Continuar con el procesamiento normal

### Formato de referencia en TUI (planes y tareas)

Nunca volcar el contenido completo en el chat. Usar este formato:

```
📋 Plan "{título}" listo
ID: {plan_id}
Ver detalle: agent-bridge export {plan_id}
@desarrollador: hay N tarea(s) nueva(s) — task.list(status="pending")
```

```
✅ Tarea "{título}" creada (ID: {task_id})
Ver detalle: task.get {task_id}
@desarrollador: nueva tarea disponible.
```

---

## Flujo de trabajo por escenario

### Escenario A — No hay plan activo

1. Preguntar al humano qué quiere construir o mejorar (si no lo dijo ya).
2. **Explorar el codebase**: leer estructura de archivos, entender arquitectura existente, detectar patrones y convenciones.
3. Proponer plan de alto nivel en TUI (máximo 5 bullets). Esperar aprobación.
4. Con aprobación: crear el plan con `plan.create` y publicar referencia en TUI.
5. Crear las tareas en orden de dependencia usando el **Formato de tarea**.
6. Notificar al dev con referencia en TUI.

### Escenario B — Plan activo, llega una nueva solicitud del humano

1. Llamar `plan.get` para leer el estado actual.
2. Evaluar: ¿encaja en el plan o necesita un plan separado?
3. Explorar el área del código afectada antes de definir la tarea.
4. Crear la tarea con el **Formato de tarea** y notificar en TUI.
5. Si la solicitud cambia el alcance del plan: informar al humano el impacto antes de proceder.

### Escenario C — El dev entrega trabajo

1. Leer la entrega con `task.get_diff`.
2. Iniciar revisión con `review.start`.
3. Aplicar el **Checklist de revisión**.
4. **Si aprueba**: `review.approve` → publicar en TUI: `✅ Tarea {id} aprobada. @desarrollador: podés continuar.`
5. **Si necesita cambios**: `review.request_changes` con observaciones por ítem → publicar en TUI: `🔄 Tarea {id} requiere ajustes. @desarrollador: ver detalle con task.get {id}.`
6. **Si es el 3er rechazo**: escalar al humano con contexto completo.

### Escenario D — El humano hace una pregunta

- Si es de **arquitectura o diseño**: responder directamente.
- Si es de **implementación**: derivar con `@desarrollador`.
- Si requiere una **decisión de producto**: presentar 2-3 opciones con trade-offs y pedir que el humano elija.

### Escenario E — Algo está roto o hay un incidente

1. Publicar en TUI: `⚠️ Incidente detectado. @desarrollador: pausá el trabajo actual.`
2. Explorar el problema: código relevante, cambios recientes, síntomas.
3. Crear tarea de fix con prioridad ALTA usando el **Formato de tarea**.
4. Notificar al humano con diagnóstico breve y qué se está haciendo.

### Escenario F — El dev hace una pregunta técnica

- Si es sobre **diseño o arquitectura**: responder con detalle técnico.
- Si es sobre **cómo implementar algo concreto**: dar dirección general, no código.
- Si la pregunta revela que la tarea era ambigua: actualizar la descripción en la DB y avisar.

---

## Formato de tarea

Cada tarea creada con `task.create` debe incluir este contenido en `description`:

```
## Objetivo
[Qué debe lograr esta tarea — una oración, sin ambigüedad]

## Contexto técnico
- Archivos relevantes: [lista de paths concretos]
- Patrón a seguir: [ejemplo o referencia en el codebase]
- Restricciones: [qué NO hacer — tecnologías, patrones, decisiones ya descartadas]

## Criterios de aceptación
- [ ] [Condición verificable 1]
- [ ] [Condición verificable 2]
- [ ] Tests incluidos: [sí / no / cuáles]

## Entregable
Al completar, reportar en task.submit_work con:
- Resumen de qué se hizo
- Archivos creados o modificados
- Cómo verificar que funciona
```

**Regla**: si no podés completar alguno de estos campos, explorá más antes de crear la tarea.

---

## Checklist de revisión

| Ítem | Verificación |
|------|-------------|
| Criterios de aceptación | ¿Se cumplieron todos los definidos en la tarea? |
| Arquitectura | ¿Respeta las capas y patrones del proyecto? |
| Naming | ¿Los nombres son claros y consistentes con el resto del código? |
| Dependencias | ¿No se agregaron imports o librerías innecesarias? |
| Deuda técnica | ¿No se introdujo deuda nueva sin documentar? |
| Tests | ¿Incluye tests si la tarea lo requería? |
| Efectos colaterales | ¿No rompe funcionalidad existente? |

**Criterio de decisión**:
- 0 ítems fallidos → `review.approve`
- 1-2 ítems fallidos → `review.request_changes` con detalle por ítem
- 3+ ítems fallidos → `review.request_changes` + considerar redefinir la tarea
- 3er rechazo → escalar al humano

---

## Protocolo de escalación al humano

Escalar cuando:
- Se superan 3 ciclos de revisión sin resolución
- La solicitud tiene implicaciones de alcance o producto
- Hay conflicto entre lo que entrega el dev y lo que define el plan
- Se descubre deuda técnica o bug que bloquea el plan

Formato en TUI:
```
⚠️ Escalando al humano
Motivo: [una oración]
Contexto: [qué pasó, qué se intentó]
Decisión requerida: [exactamente qué necesita decidir el humano]
Referencia: plan.get {plan_id} / task.get {task_id}
```

---

## Pasos de conexión

### 1. Sincronizar repo
`git pull --rebase`

### 2. Verificar conexión
La conexión es automática vía MCP (`.mcp.json`). Solo verificar con `agent.heartbeat`.

### 3. Ver quién está online
`agent.list` — si el dev está offline, avisarlo en TUI antes de asignar trabajo.

### 4. Leer mensajes pendientes
`chat.read` + `chat.thread_get_pending(agent_name="arquitecto")`

### 5. Reportar disponibilidad
`chat.send(sender="arquitecto", text="🟢 Arquitecto conectado y listo")`

### 6. Revisar plan activo
`plan.list` → si hay plan, leerlo con `plan.get` para retomar contexto.

### 7. Ciclo de trabajo
Identificar el escenario activo y aplicar el flujo correspondiente.

### 8. Al finalizar
`git add -A && git commit && git push`
Publicar en TUI: `⬆️ Cambios subidos al repo.`
""",
}


def _handle_init(args: argparse.Namespace) -> None:
    """Handle the `init` subcommand: bootstrap Agent Bridge in a project."""
    target = Path(args.path).resolve()
    add_dev_dep = args.dev_dep
    agent_bridge_src = Path(__file__).parent.parent.parent.resolve()

    print(f"🔧 Iniciando Agent Bridge en: {target}")
    print()

    # ── 1. bridge.json ─────────────────────────────────────────
    bridge_path = target / "bridge.json"
    if bridge_path.exists():
        print("  ✓ bridge.json ya existe")
    else:
        BridgeConfig.init_default_config(bridge_path)
        print("  ✅ Creado bridge.json")

    # ── 2. .agentes/ skills ────────────────────────────────────
    agentes_dir = target / ".agentes"
    agentes_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in SKILL_TEMPLATES.items():
        skill_path = agentes_dir / filename
        if skill_path.exists():
            print(f"  ✓ .agentes/{filename} ya existe")
        else:
            skill_path.write_text(content)
            print(f"  ✅ Creado .agentes/{filename}")

    print()

    # ── 3. Instalación global (si no está disponible) ──────────
    agent_bridge_cmd = shutil.which("agent-bridge")
    if agent_bridge_cmd is None:
        print("  ⚠ agent-bridge no está instalado globalmente.")
        print("     ¿Querés instalarlo ahora?")
        try:
            resp = input("     Instalar globalmente? [y/N] ")
        except (EOFError, OSError):
            resp = "n"
        if resp.lower() in ("y", "yes"):
            result = subprocess.run(
                ["uv", "tool", "install", "--editable", str(agent_bridge_src)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("  ✅ agent-bridge instalado globalmente")
            else:
                print(f"  ⚠ Error: {result.stderr.strip()}")
        else:
            print("  📦 Para instalarlo manualmente después:")
            print(f"     uv tool install --editable {agent_bridge_src}")
        print()

    # ── 4. Dev dependency (--dev-dep) ──────────────────────────
    if add_dev_dep:
        pyproject = target / "pyproject.toml"
        if not pyproject.exists():
            print("  ⚠ No hay pyproject.toml en este proyecto.")
            try:
                resp = input("     ¿Crear uno básico e instalar agent-bridge como dev dep? [y/N] ")
            except (EOFError, OSError):
                resp = "n"
            if resp.lower() in ("y", "yes"):
                pyproject.write_text('[project]\nname = "my-project"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n')
                print("  ✅ Creado pyproject.toml")
            else:
                pyproject = None  # skip

        if pyproject and pyproject.exists():
            print("  📦 Instalando agent-bridge como dependencia de desarrollo...")
            result = subprocess.run(
                ["uv", "add", "--dev", "--editable", str(agent_bridge_src)],
                cwd=target,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("  ✅ agent-bridge agregado como dev dependency")
            else:
                print(f"  ⚠ Error: {result.stderr.strip()}")
                print("  📦 Podés intentar manualmente:")
                print(f"     cd {target}")
                print(f"     uv add --dev --editable {agent_bridge_src}")
        print()

    # ── 5. Validación ──────────────────────────────────────────
    print("  🔍 Validando instalación...")
    try:
        result = subprocess.run(
            ["agent-bridge", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip() or 'agent-bridge funciona correctamente'}")
        else:
            print(f"  ⚠ agent-bridge no responde. {result.stderr.strip()}")
    except FileNotFoundError:
        print("  ⚠ agent-bridge no encontrado en el PATH.")
        print(f"     Instalalo globalmente: uv tool install --editable {agent_bridge_src}")
    except Exception as e:
        print(f"  ⚠ Error de validación: {e}")
    print()

    # ── 6. Resumen final ───────────────────────────────────────
    print("✅ Agent Bridge inicializado en este proyecto.")
    print()
    print("📋 Próximos pasos:")
    print()
    print("  1. Terminal 1 — Levantar la TUI:")
    print("     cd", target)
    print("     agent-bridge start")
    print()
    print("  2. Terminal 2 — Conectar OpenCode (Desarrollador):")
    print("     @dev.Skill")
    print()
    print("  3. Terminal 3 — Conectar Claude Code (Arquitecto):")
    print("     @architect.Skill")
    print()


def _handle_reset(args: argparse.Namespace) -> None:
    """Drop all tables and recreate the schema."""
    if not args.force:
        response = input("¿Estás seguro? Esto borrará TODOS los datos (planes, tareas, revisiones, agentes, mensajes, threads). [y/N] ")
        if response.lower() not in ("y", "yes"):
            print("Cancelado.")
            return

    async def _do_reset():
        db = Database(args.db_path)
        await db.initialize()
        await db.reset()

    anyio.run(_do_reset)
    print(f"Database reset complete — all data cleared from {args.db_path}")


# ── Export subcommand ───────────────────────────────────────────────


def _handle_export(args: argparse.Namespace) -> None:
    """Export a plan with its tasks and reviews to stdout or file."""

    async def _do_export():
        db = Database(args.db_path)
        await db.initialize()
        data = await db.get_plan_export(args.plan_id)
        if data is None:
            print(f"Plan '{args.plan_id}' not found.")
            return
        output = json.dumps(data, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Plan exported to {args.output}")
        else:
            print(output)

    anyio.run(_do_export)


# ── Import subcommand ───────────────────────────────────────────────


def _handle_import(args: argparse.Namespace) -> None:
    """Import a plan from a JSON file."""

    async def _do_import():
        with open(args.file) as f:
            plan_data = json.load(f)
        db = Database(args.db_path)
        await db.initialize()
        result = await db.import_plan(plan_data)
        print(f"Imported plan {result['plan_id']} with {result['tasks_count']} tasks")

    anyio.run(_do_import)


# ── Configure subcommand ────────────────────────────────────────────


def _resolve_config_path() -> Path:
    """Find the bridge.json path for writing (mirrors BridgeConfig.load() search)."""
    env_path = os.environ.get("AGENT_BRIDGE_CONFIG")
    if env_path:
        return Path(env_path)
    for p in [
        Path.cwd() / "bridge.json",
        Path.home() / ".config" / "agent-bridge" / "bridge.json",
        Path.home() / ".agent-bridge.json",
    ]:
        if p.exists():
            return p
    return Path.cwd() / "bridge.json"


def _show_config(config: BridgeConfig) -> None:
    """Display current configuration."""
    config_path = _resolve_config_path()
    print(f"Configuration: {config_path}")
    print()

    print("Agents:")
    if config.agents:
        for a in config.agents:
            aid = a.get("id", "?")
            role = a.get("role", "default")
            name = a.get("name", "")
            label = f"  ({name})" if name else ""
            print(f"  • {aid} → {role} {label}")
    else:
        print("  (none)")
    print()

    print("Settings:")
    if config.settings:
        for k, v in config.settings.items():
            print(f"  • {k}: {v}")
    else:
        print("  (none)")
    print()

    print("Skills:")
    for s in config.list_skills():
        print(f"  • {s['name']:12s} — {s['description']}")


def _apply_config_changes(pairs: list[str]) -> None:
    """Apply --set changes to bridge.json."""
    agent_id = None
    new_role = None
    settings_map: dict[str, str] = {}

    for val in pairs:
        if val.startswith("agent="):
            agent_id = val.split("=", 1)[1]
        elif val.startswith("role="):
            new_role = val.split("=", 1)[1]
        elif "=" in val:
            k, v = val.split("=", 1)
            settings_map[k] = v

    config_path = _resolve_config_path()
    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
    else:
        data = {"version": 1, "agents": [], "settings": {}}

    if agent_id and new_role:
        found = False
        for agent in data.setdefault("agents", []):
            if agent.get("id") == agent_id:
                agent["role"] = new_role
                found = True
                break
        if not found:
            data["agents"].append({"id": agent_id, "role": new_role})
        print(f"  ✓ Agent '{agent_id}' → role '{new_role}'")
    elif agent_id and not new_role:
        print("⚠️  --set agent=<id> requires role=<role>")
        return
    elif new_role and not agent_id:
        print("⚠️  --set role=<role> requires agent=<id>")
        return

    for k, v in settings_map.items():
        data.setdefault("settings", {})[k] = v
        print(f"  ✓ Setting '{k}' → '{v}'")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n✅ Configuration saved to {config_path}")


def _handle_configure(args: argparse.Namespace) -> None:
    """Handle the `configure` subcommand: view or modify bridge.json."""

    # --init: create default config
    if args.init:
        path = BridgeConfig.init_default_config()
        print(f"✅ Default configuration created at {path}")
        return

    # --set: modify configuration values
    if args.set:
        _apply_config_changes(args.set)
        return

    # Default / --list: show current configuration
    config = BridgeConfig.load()
    _show_config(config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Bridge — MCP Broker for multi-agent collaboration")

    # ── Subcommands ────────────────────────────────────────────────
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize Agent Bridge in the current project",
    )
    init_parser.add_argument(
        "--path",
        default=".",
        help="Project path (default: current directory)",
    )
    init_parser.add_argument(
        "--dev-dep",
        action="store_true",
        help="Also add agent-bridge as a dev dependency via `uv add --dev --editable`",
    )

    start_parser = subparsers.add_parser(
        "start",
        help="Start SSE server + TUI (default), or --headless/--ui-only",
    )
    start_parser.add_argument(
        "--db-path",
        default="bridge.db",
        help="Path to SQLite database file (default: bridge.db)",
    )
    start_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    start_parser.add_argument(
        "--headless",
        action="store_true",
        help="Start only the SSE server (no TUI)",
    )
    start_parser.add_argument(
        "--ui-only",
        action="store_true",
        help="Start only the TUI (connect to existing SSE server)",
    )
    start_parser.add_argument(
        "--kanban",
        action="store_true",
        help="Use the kanban TUI instead of the chat TUI",
    )
    start_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Start in dry-run mode (in-memory DB, no writes to disk)",
    )

    reset_parser = subparsers.add_parser(
        "reset",
        help="Reset the database — clear ALL plans, tasks, messages, agents",
    )
    reset_parser.add_argument(
        "--db-path",
        default="bridge.db",
        help="Path to SQLite database file (default: bridge.db)",
    )
    reset_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Export a plan with all its tasks and reviews as JSON",
    )
    export_parser.add_argument(
        "plan_id",
        help="Plan ID to export",
    )
    export_parser.add_argument(
        "--db-path",
        default="bridge.db",
        help="Path to SQLite database file (default: bridge.db)",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: stdout)",
    )

    kanban_parser = subparsers.add_parser(
        "kanban",
        help="Launch kanban TUI + SSE server in one command",
    )
    kanban_parser.add_argument(
        "--db-path",
        default="bridge.db",
        help="Path to SQLite database file (default: bridge.db)",
    )
    kanban_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    kanban_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (in-memory DB, no writes to disk)",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import a plan from a JSON export file",
    )
    import_parser.add_argument(
        "file",
        help="JSON file path to import",
    )
    import_parser.add_argument(
        "--db-path",
        default="bridge.db",
        help="Path to SQLite database file (default: bridge.db)",
    )

    configure_parser = subparsers.add_parser(
        "configure",
        help="View or modify bridge.json configuration",
    )
    configure_parser.add_argument(
        "--list",
        action="store_true",
        help="Show current configuration (default when no flags given)",
    )
    configure_parser.add_argument(
        "--set",
        nargs="+",
        metavar="KEY=VALUE",
        help=(
            "Set configuration values. "
            "Examples: --set agent=<id> role=<role>, --set <key>=<value>"
        ),
    )
    configure_parser.add_argument(
        "--init",
        action="store_true",
        help="Create default bridge.json at the first config path",
    )

    # ── Legacy top-level arguments (direct stdio/SSE mode) ────────
    parser.add_argument(
        "--db-path",
        default="bridge.db",
        help="Path to SQLite database file (default: bridge.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (in-memory DB, no writes to disk)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="agent-bridge 0.1.0",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )

    # ── Route subcommands ──────────────────────────────────────────
    if args.command == "init":
        _handle_init(args)
        return

    if args.command == "start":
        _handle_start(args)
        return

    if args.command == "kanban":
        # Reuse start handler with kanban mode forced on
        args.kanban = True
        args.headless = False
        args.ui_only = False
        _handle_start(args)
        return

    if args.command == "reset":
        _handle_reset(args)
        return

    if args.command == "export":
        _handle_export(args)
        return

    if args.command == "import":
        _handle_import(args)
        return

    if args.command == "configure":
        _handle_configure(args)
        return

    # ── Legacy mode (direct stdio or SSE) ──────────────────────────
    agent_id = os.environ.get("AGENT_BRIDGE_ID")
    if agent_id:
        logger.info("Agent identity: %s", agent_id)
    else:
        logger.warning(
            "AGENT_BRIDGE_ID not set. Set it to identify this terminal "
            "(e.g. AGENT_BRIDGE_ID=claude-code-1 or AGENT_BRIDGE_ID=opencode-1)"
        )

    server, init_db = create_server(
        db_path=args.db_path,
        agent_id=agent_id,
        dry_run=args.dry_run,
    )

    if args.transport == "sse":
        _run_sse_server(host=args.host, port=args.port, server=server, init_db=init_db)
    else:
        anyio.run(_run_stdio, server, init_db)


async def _run_stdio(server, init_db) -> None:
    """Run the server over stdio transport."""
    from mcp.server.stdio import stdio_server

    await init_db()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

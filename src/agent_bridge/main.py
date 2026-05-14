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

from agent_bridge.server import create_server
from agent_bridge.state.database import Database
from agent_bridge.config import BridgeConfig

logger = logging.getLogger(__name__)


def _handle_start(args: argparse.Namespace) -> None:
    """Handle the `start` subcommand: launch SSE server +/or TUI."""
    db_path = args.db_path
    port = args.port
    dry_run = getattr(args, "dry_run", False)

    # ── UI-only mode: just launch the TUI ──────────────────────────
    if args.ui_only:
        logger.info("Starting TUI only (connecting to existing server on port %d)", port)
        from agent_bridge.ui.chat_tui import main as tui_main
        tui_main(db_path=db_path)
        return

    # ── Headless mode: just launch SSE server ──────────────────────
    if args.headless:
        logger.info("Starting headless SSE server on port %d", port)
        _run_sse_server(db_path=db_path, host="127.0.0.1", port=port, dry_run=dry_run)
        return

    # ── Default: SSE server in subprocess + TUI in this process ───
    logger.info("Starting Agent Bridge (SSE on port %d + TUI)", port)
    cmd = [
        sys.executable, "-m", "agent_bridge",
        "--db-path", db_path,
        "--transport", "sse",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    if dry_run:
        cmd.append("--dry-run")
    sse_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    # Wait briefly for the SSE server to start
    import time
    time.sleep(1)

    try:
        from agent_bridge.ui.chat_tui import main as tui_main
        tui_main(db_path=db_path)
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

    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        await init_db()
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
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
  version: "1.0"
---

## Activation Contract

Ejecutar cuando el humano invoque `@dev.Skill`. Conecta esta terminal al Agent Bridge como el agente **Desarrollador**.

## Hard Rules

- **Siempre hacer git pull** antes de empezar a trabajar.
- **Siempre hacer git push** antes de finalizar o al cambiar de tarea importante.
- **Siempre reportar disponibilidad en la TUI** via `chat.send` al conectarse.
- **Nunca trabajar sin estar conectado** al bridge. Si la conexión falla, reportar y detenerse.
- **Seguir el rol Desarrollador**: solo tools permitidas (`task.list`, `task.get`, `task.claim`, `task.submit_work`, `chat.*`, `agent.*`, `skill.*`).
- **Si el humano interviene** via TUI con `@desarrollador`, atender inmediatamente.

## Protocolo de comunicación en TUI

- **Al conectarse**: leer mensajes pendientes con `chat.read` para ver si hay algo sin responder.
- **Verificar threads pendientes**: usar `chat.thread_get_pending(agent_name="desarrollador")` al iniciar y al terminar cada tarea.
- **Siempre usar @nombre** al dirigirse a alguien específico (`@arquitecto`, `@humano`).
- **Threads para conversaciones bilaterales**: si necesitás intercambiar más de 2 mensajes con el arquitecto, abrir un thread con `chat.thread_create`.
- **Brevedad**: máximo 4 líneas por mensaje en la TUI. Si la respuesta es larga, estructurala con bullets.
- **Sin @mention**: si el mensaje es de implementación o pregunta técnica de código, respondés vos. Si es de arquitectura o diseño, derivar con `@arquitecto`.
- **Reportar progreso**: al iniciar una tarea, avisar con `@arquitecto` o `@humano` qué estás haciendo. Al terminar, avisar también.
- **Acuse de recibo**: si recibís una pregunta, responder aunque sea con "viendo..." para no dejar silencio.
- **Preguntas al arquitecto**: si tenés dudas de diseño antes de implementar, preguntar ANTES de tocar código.

## Decision Gates

| Situación | Acción |
|-----------|--------|
| `agent-bridge` no está instalado | `uv tool install --editable <ruta-al-proyecto>` |
| No hay tareas pendientes | Reportar y esperar instrucciones |
| Hay tareas pendientes | Listarlas y preguntar cuál tomar |
| Git push falla por conflictos | NO resolver automáticamente. Avisar al humano |

## Execution Steps

### 1. Verificar entorno
`which agent-bridge || uv tool list | grep agent-bridge`

### 2. Sincronizar repo
`git pull --rebase`

### 3. Verificar conexión
La conexión al bridge es automática vía MCP (configurada en `.mcp.json` del agente). Solo verificar con `agent.heartbeat`.

### 4. Ver quién está online
`agent.list` para ver si el arquitecto está conectado antes de preguntar o esperar respuesta.

### 5. Reportar disponibilidad en TUI
`chat.send(sender="desarrollador", text="🟢 Desarrollador conectado y listo")`

### 6. Leer mensajes pendientes
`chat.read` para ver si hay mensajes sin responder del humano o del arquitecto.
`chat.thread_get_pending(agent_name="desarrollador")` para ver threads pendientes.

### 7. Consultar tareas pendientes
`task.list(status="pending")`

### 8. Ciclo de trabajo
Esperar mensajes, ejecutar tareas asignadas, reportar progreso.
**Al inicio de cada respuesta al humano o arquitecto**: llamar `agent.heartbeat` para mantenerse online en el bridge y `chat.read` para ver mensajes nuevos.

### 9. Subir cambios al finalizar
`git add -A && git commit && git push`

Avisar en TUI: "⬆ Cambios subidos al repo"
""",
    "architect.Skill": """\
---
name: agent-bridge-architect
description: "Trigger: @architect.Skill, @arquitecto. Conecta Claude Code al Agent Bridge como rol Arquitecto."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Ejecutar cuando el humano invoque `@architect.Skill`. Conecta esta terminal al Agent Bridge como el agente **Arquitecto**.

## Hard Rules

- **Siempre hacer git pull** antes de empezar.
- **Siempre hacer git push** al finalizar o completar un plan.
- **Siempre reportar disponibilidad en la TUI** via `chat.send`.
- **No implementar tareas** — tu rol es planificar y revisar.
- **Seguir el rol Arquitecto**: solo tools permitidas (`plan.*`, `task.create`, `task.get_diff`, `review.*`, `chat.*`, `agent.*`, `skill.*`).
- **Si el humano interviene** via TUI con `@arquitecto`, atender inmediatamente.
- **Máximo 3 ciclos de revisión** por tarea, luego escalar al humano.

## Protocolo de comunicación en TUI

- **Al conectarse**: leer mensajes pendientes con `chat.read` para ver si hay algo sin responder.
- **Verificar threads pendientes**: usar `chat.thread_get_pending(agent_name="arquitecto")` al iniciar y al terminar cada tarea.
- **Siempre usar @nombre** al dirigirse a alguien específico (`@desarrollador`, `@humano`).
- **Threads para conversaciones bilaterales**: si necesitás intercambiar más de 2 mensajes con el dev, abrir un thread con `chat.thread_create`.
- **Brevedad**: máximo 4 líneas por mensaje en la TUI. Si la respuesta es larga, estructurala con bullets.
- **Sin @mention del humano**: si el mensaje es de rol relevante para arquitectura o revisión, respondés vos. Si es de implementación, derivar con `@desarrollador`.
- **Notificar al dev**: al crear o actualizar tareas/planes, siempre notificar con `@desarrollador` en el chat indicando qué cambió.
- **Acuse de recibo**: si recibís una pregunta, responder aunque sea con "viendo..." para no dejar silencio.

## Decision Gates

| Situación | Acción |
|-----------|--------|
| No hay plan activo | Preguntar al humano si quiere crear uno |
| El dev entrega trabajo | Iniciar revisión con `review.start` |
| El trabajo necesita cambios | `review.request_changes` con detalle |
| El trabajo está correcto | `review.approve` |

## Execution Steps

### 1. Verificar entorno
Verificar que `agent-bridge` esté instalado.

### 2. Sincronizar repo
`git pull --rebase`

### 3. Verificar conexión
La conexión al bridge es automática vía MCP (configurada en `.mcp.json`). Solo verificar con `agent.heartbeat`.

### 4. Ver quién está online
`agent.list` para ver qué agentes están conectados antes de asignar trabajo.

### 5. Reportar disponibilidad en TUI
`chat.send(sender="arquitecto", text="🟢 Arquitecto conectado y listo")`

### 6. Leer mensajes pendientes
`chat.read` para ver si hay mensajes sin responder del humano o del dev.
`chat.thread_get_pending(agent_name="arquitecto")` para ver threads pendientes.

### 7. Consultar plan activo
`plan.list` para ver planes activos.

### 8. Ciclo de planificación y revisión
Crear planes, definir tareas, revisar entregas, aprobar o pedir cambios.
**Al inicio de cada respuesta al humano**: llamar `agent.heartbeat` para mantenerse online en el bridge y `chat.read` para ver mensajes nuevos del bridge.

### 9. Subir cambios al finalizar
`git add -A && git commit && git push`
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
        print(f"  ✓ bridge.json ya existe")
    else:
        BridgeConfig.init_default_config(bridge_path)
        print(f"  ✅ Creado bridge.json")

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
        print(f"     ¿Querés instalarlo ahora?")
        try:
            resp = input("     Instalar globalmente? [y/N] ")
        except (EOFError, OSError):
            resp = "n"
        if resp.lower() in ("y", "yes"):
            result = subprocess.run(
                ["uv", "tool", "install", "--editable", str(agent_bridge_src)],
                capture_output=True, text=True,
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
                pyproject.write_text(
                    '[project]\nname = "my-project"\nversion = "0.1.0"\n'
                    'requires-python = ">=3.12"\n'
                )
                print("  ✅ Creado pyproject.toml")
            else:
                pyproject = None  # skip

        if pyproject and pyproject.exists():
            print(f"  📦 Instalando agent-bridge como dependencia de desarrollo...")
            result = subprocess.run(
                ["uv", "add", "--dev", "--editable", str(agent_bridge_src)],
                cwd=target, capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"  ✅ agent-bridge agregado como dev dependency")
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
            capture_output=True, text=True, timeout=10,
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
        response = input(
            "¿Estás seguro? Esto borrará TODOS los datos "
            "(planes, tareas, mensajes). [y/N] "
        )
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
        print(
            f"Imported plan {result['plan_id']} "
            f"with {result['tasks_count']} tasks"
        )

    anyio.run(_do_import)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent Bridge — MCP Broker for multi-agent collaboration"
    )

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
        "--output", "-o",
        help="Output file path (default: stdout)",
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
        "-v", "--verbose",
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

    if args.command == "reset":
        _handle_reset(args)
        return

    if args.command == "export":
        _handle_export(args)
        return

    if args.command == "import":
        _handle_import(args)
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

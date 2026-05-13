"""Agent Bridge — CLI entry point."""

import argparse
import json
import logging
import os
import subprocess
import sys

import anyio

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


# ── Reset subcommand ────────────────────────────────────────────────


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

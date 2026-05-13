"""Agent Bridge MCP server — core setup, permission layer, and tool registration."""

import asyncio
import json
import logging
import time
import uuid

import mcp.types as types
from mcp.server import Server

from agent_bridge.config import BridgeConfig
from agent_bridge.state.database import Database
from agent_bridge.tools.agents import AGENT_TOOLS, handle_agent_tool
from agent_bridge.tools.chat import CHAT_TOOLS, handle_chat_tool
from agent_bridge.tools.planner import PLAN_TOOLS, handle_plan_tool
from agent_bridge.tools.review import REVIEW_TOOLS, handle_review_tool
from agent_bridge.tools.skills import SKILL_TOOLS, handle_skill_tool
from agent_bridge.tools.tasks import TASK_TOOLS, handle_task_tool

logger = logging.getLogger(__name__)

# ── Hello-world tool ──────────────────────────────────────────────
HELLO_TOOL = types.Tool(
    name="hello",
    description="Health check — returns pong from the bridge",
    inputSchema={"type": "object", "properties": {}},
)

# ── All tools registry ───────────────────────────────────────────
ALL_TOOLS: list[types.Tool] = [
    HELLO_TOOL,
    *PLAN_TOOLS,
    *TASK_TOOLS,
    *REVIEW_TOOLS,
    *CHAT_TOOLS,
    *AGENT_TOOLS,
    *SKILL_TOOLS,
]


# ── Permission layer ──────────────────────────────────────────────

async def _check_permission(
    tool_name: str, agent_id: str | None, config: BridgeConfig, db: Database
) -> str | None:
    """Check if the tool is allowed for the agent's role.
    
    Returns None if allowed, or an error message string if denied.

    Identity resolution (in order):
    1. bridge.json: agent_id → role mapping (static config)
    2. SQLite agents table: role from last heartbeat (dynamic override)
    3. Fallback: 'default' role (= chat-only)
    """
    # Public tools (always allowed)
    if tool_name in ("hello", "agent.heartbeat", "skill.list", "skill.get", "agent.whoami"):
        return None

    # Agent must be identified via env var
    if not agent_id:
        return json.dumps({
            "error": "agent_not_identified",
            "detail": "Set AGENT_BRIDGE_ID environment variable in this terminal "
                      "(e.g. AGENT_BRIDGE_ID=claude-code-1 or AGENT_BRIDGE_ID=opencode-1). "
                      "See bridge.json for available agent IDs.",
        })

    # Resolve role: bridge.json first, then SQLite from heartbeat
    role = config.get_role_for_agent(agent_id)
    if role == "default":
        row = await db.execute_one(
            "SELECT role FROM agents WHERE agent_id = ?", (agent_id,)
        )
        if row:
            role = row["role"]

    skill = config.get_skill_for_role(role)

    if tool_name not in skill.allowed_tools:
        return json.dumps({
            "error": "permission_denied",
            "detail": f"Tool '{tool_name}' no está permitida para el rol '{role}'.",
            "your_role": role,
            "skill": skill.name,
            "allowed_tools": skill.allowed_tools,
        })

    return None


# ── Stale agent reassignment ──────────────────────────────────────

STALE_AGENT_THRESHOLD_MINUTES = 5
REASSIGN_INTERVAL_SECONDS = 60


async def _reassign_stale_tasks(db: Database) -> dict:
    """Find stale agents, mark them offline, reassign their in_progress tasks.

    Returns summary dict with stale agent IDs and reassign count.
    """
    stale = await db.get_stale_agents(STALE_AGENT_THRESHOLD_MINUTES)
    if not stale:
        return {"stale_agents": [], "reassigned_count": 0}

    agent_ids = [r["agent_id"] for r in stale]
    total_reassigned = 0

    for agent_id in agent_ids:
        await db.mark_agent_offline(agent_id)
        count = await db.reassign_tasks_from_agent(agent_id)
        total_reassigned += count

    if agent_ids:
        logger.info(
            "Reassigned %d stale task(s) from %d agent(s): %s",
            total_reassigned, len(agent_ids), agent_ids,
        )

    return {"stale_agents": agent_ids, "reassigned_count": total_reassigned}


async def _reassign_loop(db: Database) -> None:
    """Background task: periodically check for and reassign stale agents."""
    logger.info(
        "Starting reassign loop (interval=%ds, threshold=%dmin)",
        REASSIGN_INTERVAL_SECONDS, STALE_AGENT_THRESHOLD_MINUTES,
    )
    while True:
        try:
            await asyncio.sleep(REASSIGN_INTERVAL_SECONDS)
            await _reassign_stale_tasks(db)
        except asyncio.CancelledError:
            logger.info("Reassign loop cancelled")
            break
        except Exception:
            logger.exception("Error in reassign loop")


# ── Server factory ────────────────────────────────────────────────

def create_server(
    db_path: str = "bridge.db",
    agent_id: str | None = None,
    dry_run: bool = False,
) -> tuple[Server, callable]:
    """Create and configure the Agent Bridge MCP server.

    Args:
        db_path: Path to SQLite database file
        agent_id: Agent identifier (from AGENT_BRIDGE_ID env var).
                  Used for permission checks.
        dry_run: If True, Database runs in dry-run mode (:memory:,
                 writes logged and skipped).

    Returns (server, init_coroutine) tuple.
    """
    db = Database(db_path, dry_run=dry_run)
    config = BridgeConfig.load()
    server = Server("agent-bridge")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return ALL_TOOLS

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent]:
        request_id = str(uuid.uuid4())
        args = arguments or {}
        start_time = time.monotonic()

        try:
            # ── Permission check ────────────────────────────────
            error = await _check_permission(name, agent_id, config, db)
            if error is not None:
                return [types.TextContent(type="text", text=error)]

            # ── Tool dispatch ───────────────────────────────────
            if name == "hello":
                return [types.TextContent(type="text", text="¡Agent Bridge alive! 👋")]

            # Domain handlers (plan, task, review, chat)
            for handler in [
                handle_plan_tool,
                handle_task_tool,
                handle_review_tool,
                handle_chat_tool,
            ]:
                result = await handler(db, name, args)
                if result is not None:
                    return result

            # Agent presence tools
            result = await handle_agent_tool(db, config, name, args)
            if result is not None:
                return result

            # Skill discovery tools
            result = await handle_skill_tool(config, name, args)
            if result is not None:
                return result

            raise ValueError(f"Unknown tool: {name}")

        except Exception:
            logger.exception(
                "request_id=%s tool=%s Internal error", request_id, name
            )
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "internal_error",
                        "detail": f"Error en tool '{name}': ver logs del servidor",
                        "request_id": request_id,
                    }),
                )
            ]

        finally:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "request_id=%s tool=%s agent=%s duration=%.0fms",
                request_id, name, agent_id or "anonymous", duration_ms,
            )

    async def init() -> None:
        """Initialize database on server start."""
        await db.initialize()
        # Start background task for stale agent reassignment
        asyncio.create_task(_reassign_loop(db))
        logger.info(
            "Server initialized (db=%s, agent=%s)",
            db.db_path,
            agent_id or "anonymous",
        )

    return server, init

"""Agent presence tools — heartbeat, list, get, set_status, whoami."""

import json
import logging
from datetime import datetime, timezone

import mcp.types as types

from agent_bridge.config import BridgeConfig
from agent_bridge.state.database import Database

logger = logging.getLogger(__name__)

AGENT_TOOLS = [
    types.Tool(
        name="agent.heartbeat",
        description="Register or update agent presence. Call this periodically (every 30s) to stay online.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Unique agent identifier (e.g. claude-code-1, opencode-1)",
                },
                "role": {
                    "type": "string",
                    "description": "Role hint (override from bridge.json)",
                },
                "status": {
                    "type": "string",
                    "description": "Current status (online, busy)",
                    "default": "online",
                },
            },
            "required": ["agent_id"],
        },
    ),
    types.Tool(
        name="agent.list",
        description="List all registered agents and their status",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="agent.get",
        description="Get details for a specific agent",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent identifier"},
            },
            "required": ["agent_id"],
        },
    ),
    types.Tool(
        name="agent.set_status",
        description="Update an agent's status (online, busy, away, offline)",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent identifier"},
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["online", "busy", "away", "offline"],
                },
            },
            "required": ["agent_id", "status"],
        },
    ),
    types.Tool(
        name="agent.whoami",
        description="Get your own role, skill, and allowed tools",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Your agent identifier"},
            },
            "required": ["agent_id"],
        },
    ),
]


async def handle_agent_tool(
    db: Database, config: BridgeConfig, name: str, args: dict
) -> list[types.TextContent] | None:
    if name == "agent.heartbeat":
        return await _heartbeat(db, config, args)
    elif name == "agent.list":
        return await _list_agents(db)
    elif name == "agent.get":
        return await _get_agent(db, args)
    elif name == "agent.set_status":
        return await _set_status(db, args)
    elif name == "agent.whoami":
        return await _whoami(db, config, args)
    return None


async def _heartbeat(
    db: Database, config: BridgeConfig, args: dict
) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    role_hint = args.get("role")
    status = args.get("status", "online")

    if not agent_id:
        return [types.TextContent(type="text", text='{"error": "agent_id required"}')]

    # Resolve role: bridge.json takes precedence, then role_hint, then default
    role = config.get_role_for_agent(agent_id)
    if role == "default" and role_hint:
        role = role_hint

    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        """INSERT OR REPLACE INTO agents (agent_id, role, status, last_seen, connected_since)
           VALUES (?, ?, ?, ?,
               COALESCE((SELECT connected_since FROM agents WHERE agent_id = ?), ?)
           )""",
        (agent_id, role, status, now, agent_id, now),
    )

    skill = config.get_skill_for_role(role)

    logger.info("Heartbeat from %s (role=%s, status=%s)", agent_id, role, status)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "agent_id": agent_id,
                "role": role,
                "status": status,
                "allowed_tools": skill.allowed_tools,
                "last_seen": now,
            }),
        )
    ]


async def _list_agents(db: Database) -> list[types.TextContent]:
    rows = await db.execute(
        "SELECT agent_id, role, status, last_seen, connected_since FROM agents ORDER BY last_seen DESC"
    )
    agents = [
        {
            "agent_id": r["agent_id"],
            "role": r["role"],
            "status": r["status"],
            "last_seen": r["last_seen"],
            "connected_since": r["connected_since"],
        }
        for r in rows
    ]
    return [types.TextContent(type="text", text=json.dumps(agents))]


async def _get_agent(
    db: Database, args: dict
) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    if not agent_id:
        return [types.TextContent(type="text", text='{"error": "agent_id required"}')]

    row = await db.execute_one(
        "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
    )
    if row is None:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent not found"}))]

    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "agent_id": row["agent_id"],
                "role": row["role"],
                "status": row["status"],
                "last_seen": row["last_seen"],
                "connected_since": row["connected_since"],
            }),
        )
    ]


async def _set_status(
    db: Database, args: dict
) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    status = args.get("status")

    if not agent_id or not status:
        return [
            types.TextContent(
                type="text", text='{"error": "agent_id and status required"}'
            )
        ]

    await db.execute(
        "UPDATE agents SET status = ?, last_seen = datetime('now') WHERE agent_id = ?",
        (status, agent_id),
    )

    return [
        types.TextContent(
            type="text",
            text=json.dumps({"agent_id": agent_id, "status": status}),
        )
    ]


async def _whoami(
    db: Database, config: BridgeConfig, args: dict
) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    if not agent_id:
        return [types.TextContent(type="text", text='{"error": "agent_id required"}')]

    row = await db.execute_one(
        "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
    )

    if row is None:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({
                    "error": "agent not registered",
                    "hint": "Call agent.heartbeat first to register",
                }),
            )
        ]

    role = row["role"]
    skill = config.get_skill_for_role(role)

    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "agent_id": row["agent_id"],
                "role": role,
                "status": row["status"],
                "skill": skill.name,
                "allowed_tools": skill.allowed_tools,
                "instructions": skill.instructions,
                "restrictions": skill.restrictions,
            }, indent=2),
        )
    ]

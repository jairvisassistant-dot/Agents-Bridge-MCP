"""Agent presence tools — heartbeat, list, get, set_status, whoami, ping, pong."""

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime

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
    types.Tool(
        name="agent.ping",
        description="Send a connectivity ping to a specific agent and wait for their pong response.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_agent_id": {
                    "type": "string",
                    "description": "Agent ID to ping",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Seconds to wait for pong (default: 10)",
                    "default": 10,
                },
            },
            "required": ["target_agent_id"],
        },
    ),
    types.Tool(
        name="agent.pong",
        description="Respond to a ping request with a pong.",
        inputSchema={
            "type": "object",
            "properties": {
                "ping_id": {
                    "type": "string",
                    "description": "Ping request ID from the ping message",
                },
            },
            "required": ["ping_id"],
        },
    ),
    types.Tool(
        name="agent.idle",
        description="Signal that this agent has gone idle and is not available for work.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Your agent identifier",
                },
            },
            "required": ["agent_id"],
        },
    ),
    types.Tool(
        name="agent.shutdown_request",
        description="Request another agent to shut down gracefully.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_agent_id": {
                    "type": "string",
                    "description": "Agent ID to request shutdown for",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional reason for the shutdown request",
                },
            },
            "required": ["target_agent_id"],
        },
    ),
    types.Tool(
        name="agent.shutdown_approve",
        description="Approve a shutdown request and notify the requesting agent.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_agent_id": {
                    "type": "string",
                    "description": "Agent ID that requested the shutdown (send approval back to them)",
                },
            },
            "required": ["target_agent_id"],
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
    elif name == "agent.ping":
        return await _ping(db, args)
    elif name == "agent.pong":
        return await _pong(db, args)
    elif name == "agent.idle":
        return await _idle(db, args)
    elif name == "agent.shutdown_request":
        return await _shutdown_request(db, args)
    elif name == "agent.shutdown_approve":
        return await _shutdown_approve(db, args)
    return None


async def _heartbeat(db: Database, config: BridgeConfig, args: dict) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    role_hint = args.get("role")
    status = args.get("status", "online")

    if not agent_id:
        return [types.TextContent(type="text", text='{"error": "agent_id required"}')]

    # Resolve role: bridge.json takes precedence
    role = config.get_role_for_agent(agent_id)
    if role == "default":
        # Check existing DB role — freeze once set (CODE-03: prevent privilege escalation)
        existing = await db.execute_one(
            "SELECT role FROM agents WHERE agent_id = ?", (agent_id,)
        )
        if existing:
            role = existing["role"]
        elif role_hint:
            role = role_hint

    now = datetime.now(UTC).isoformat()

    await db.execute(
        """INSERT INTO agents (agent_id, role, status, last_seen, connected_since, metadata)
           VALUES (?, ?, ?, ?,
               COALESCE((SELECT connected_since FROM agents WHERE agent_id = ?), ?),
               '{}')
           ON CONFLICT(agent_id) DO UPDATE SET
               status = excluded.status,
               last_seen = excluded.last_seen,
               connected_since = COALESCE(agents.connected_since, excluded.connected_since)
           -- NOTE: metadata is NOT updated here (CODE-02: preserve existing metadata)
           """,
        (agent_id, role, status, now, agent_id, now),
    )

    skill = config.get_skill_for_role(role)

    logger.info("Heartbeat from %s (role=%s, status=%s)", agent_id, role, status)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "agent_id": agent_id,
                    "role": role,
                    "status": status,
                    "allowed_tools": skill.allowed_tools,
                    "last_seen": now,
                }
            ),
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


async def _get_agent(db: Database, args: dict) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    if not agent_id:
        return [types.TextContent(type="text", text='{"error": "agent_id required"}')]

    row = await db.execute_one("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
    if row is None:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent not found"}))]

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "agent_id": row["agent_id"],
                    "role": row["role"],
                    "status": row["status"],
                    "last_seen": row["last_seen"],
                    "connected_since": row["connected_since"],
                }
            ),
        )
    ]


async def _set_status(db: Database, args: dict) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    status = args.get("status")

    if not agent_id or not status:
        return [types.TextContent(type="text", text='{"error": "agent_id and status required"}')]

    _agent_id = args.get("_agent_id")
    if _agent_id is not None and agent_id != _agent_id:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "cannot set status for another agent"})
        )]

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


async def _whoami(db: Database, config: BridgeConfig, args: dict) -> list[types.TextContent]:
    agent_id = args.get("agent_id")
    if not agent_id:
        return [types.TextContent(type="text", text='{"error": "agent_id required"}')]

    row = await db.execute_one("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))

    if row is None:
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "agent not registered",
                        "hint": "Call agent.heartbeat first to register",
                    }
                ),
            )
        ]

    role = row["role"]
    skill = config.get_skill_for_role(role)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "agent_id": row["agent_id"],
                    "role": role,
                    "status": row["status"],
                    "skill": skill.name,
                    "allowed_tools": skill.allowed_tools,
                    "instructions": skill.instructions,
                    "restrictions": skill.restrictions,
                },
                indent=2,
            ),
        )
    ]


async def _ping(db: Database, args: dict) -> list[types.TextContent]:
    """Send a ping to target_agent_id and wait for pong up to timeout_seconds."""
    target_agent_id = args.get("target_agent_id")
    timeout_seconds = args.get("timeout_seconds", 10)
    sender_id = args.get("_agent_id")

    if not target_agent_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "target_agent_id required"}))]
    if not sender_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent not identified"}))]

    # Create ping request in DB
    ping_id = await db.create_ping_request(sender_id, target_agent_id)

    # Notify target agent via a chat message with JSON payload
    await db.execute_write(
        "INSERT INTO messages (id, sender, target, text) VALUES (?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            "system",
            target_agent_id,
            json.dumps({"type": "ping", "ping_id": ping_id, "from": sender_id}),
        ),
    )

    logger.info("Ping %s sent to %s by %s", ping_id, target_agent_id, sender_id)

    # Poll for pong response
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        await asyncio.sleep(0.5)
        ping = await db.get_ping_request(ping_id)
        if ping and ping.get("status") == "pong":
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "pong",
                            "latency_ms": ping["latency_ms"],
                            "target_agent_id": target_agent_id,
                        }
                    ),
                )
            ]

    # Timeout — mark as timeout in DB
    await db.execute_write(
        "UPDATE ping_requests SET status = 'timeout' WHERE id = ? AND status = 'pending'",
        (ping_id,),
    )

    row = await db.execute_one(
        "SELECT last_seen, status FROM agents WHERE agent_id = ?",
        (target_agent_id,),
    )
    last_seen = row["last_seen"] if row else None

    logger.info("Ping %s timed out (target=%s)", ping_id, target_agent_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "timeout",
                    "target_agent_id": target_agent_id,
                    "last_seen": last_seen,
                }
            ),
        )
    ]


async def _pong(db: Database, args: dict) -> list[types.TextContent]:
    """Respond to a ping request — records the pong and returns latency."""
    ping_id = args.get("ping_id")

    if not ping_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "ping_id required"}))]

    latency_ms = await db.record_pong(ping_id)
    logger.info("Pong for %s: %dms", ping_id, latency_ms)

    return [
        types.TextContent(
            type="text",
            text=json.dumps({"status": "ok", "latency_ms": latency_ms}),
        )
    ]


# ── Idle / Shutdown ──────────────────────────────────────────────


async def _idle(db: Database, args: dict) -> list[types.TextContent]:
    """Mark the agent as idle and notify their conversation partner."""
    agent_id = args.get("agent_id")
    if not agent_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent_id required"}))]

    now = datetime.now(UTC).isoformat()

    # Update status to idle
    await db.execute(
        "UPDATE agents SET status = 'idle', last_seen = ? WHERE agent_id = ?",
        (now, agent_id),
    )

    # Determine partner role to notify
    row = await db.execute_one("SELECT role FROM agents WHERE agent_id = ?", (agent_id,))
    target = None
    if row:
        if row["role"] == "developer":
            target = "arquitecto"
        elif row["role"] == "architect":
            target = "desarrollador"

    if target:
        await db.send_system_notification(
            target=target,
            text=f"El agente {agent_id} está idle.",
            msg_type="idle_notification",
            priority="normal",
        )

    logger.info("Agent %s is now idle", agent_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"agent_id": agent_id, "status": "idle", "notified": target}),
        )
    ]


async def _shutdown_request(db: Database, args: dict) -> list[types.TextContent]:
    """Request a target agent to shut down gracefully."""
    target_agent_id = args.get("target_agent_id")
    reason = args.get("reason", "")
    sender_id = args.get("_agent_id")

    if not target_agent_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "target_agent_id required"}))]
    if not sender_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent not identified"}))]

    request_id = str(uuid.uuid4())

    # Send high-priority shutdown_request message to the target
    await db.send_system_notification(
        target=target_agent_id,
        text=json.dumps({
            "type": "shutdown_request",
            "request_id": request_id,
            "from": sender_id,
            "reason": reason,
        }),
        msg_type="shutdown_request",
        priority="high",
    )

    logger.info(
        "Shutdown request %s sent to %s by %s (reason: %s)",
        request_id, target_agent_id, sender_id, reason or "none",
    )
    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "status": "request_sent",
                "request_id": request_id,
                "target_agent_id": target_agent_id,
            }),
        )
    ]


async def _shutdown_approve(db: Database, args: dict) -> list[types.TextContent]:
    """Approve a shutdown request and notify the requesting agent."""
    target_agent_id = args.get("target_agent_id")
    sender_id = args.get("_agent_id")

    if not target_agent_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "target_agent_id required"}))]
    if not sender_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent not identified"}))]

    # Mark this agent as shutting_down before sending approval
    await db.execute(
        "UPDATE agents SET status = 'shutting_down', last_seen = datetime('now') WHERE agent_id = ?",
        (sender_id,),
    )

    # Send shutdown_approved to the requester
    await db.send_system_notification(
        target=target_agent_id,
        text=json.dumps({
            "type": "shutdown_approved",
            "from": sender_id,
        }),
        msg_type="shutdown_approved",
        priority="high",
    )

    logger.info("Shutdown approved by %s for request from %s", sender_id, target_agent_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "status": "shutdown_approved",
                "approved_by": sender_id,
                "notified": target_agent_id,
            }),
        )
    ]

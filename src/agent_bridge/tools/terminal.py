"""Cross-terminal notification tools — queued messages for agent terminals.

Allows agents to send messages that appear in another agent's VS Code
terminal. Messages are queued in the DB and delivered by the extension
on its next poll cycle (typically every 5 seconds).

Flow:
  1. Agent A calls ``terminal.send("desarrollador", "Revisá esto")``
  2. Backend stores in ``terminal_messages`` table
  3. Extension polls ``terminal.get_pending(target_role)``
  4. Extension routes to the correct terminal via ``TerminalManager``
"""

import json
import logging

import mcp.types as types

from agent_bridge.state.database import Database

logger = logging.getLogger(__name__)

TERMINAL_TOOLS = [
    types.Tool(
        name="terminal.send",
        description="Queue a message for another agent's terminal. "
                    "The message will appear in the target agent's terminal "
                    "within seconds.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_role": {
                    "type": "string",
                    "description": "Target role (e.g. 'desarrollador', 'arquitecto', 'humano')",
                },
                "text": {
                    "type": "string",
                    "description": "Message text to display in the target's terminal",
                },
            },
            "required": ["target_role", "text"],
        },
    ),
    types.Tool(
        name="terminal.send_to_agent_id",
        description="Queue a message for a specific agent's terminal by agent ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_agent_id": {
                    "type": "string",
                    "description": "Target agent ID (e.g. 'claude-code-1')",
                },
                "text": {
                    "type": "string",
                    "description": "Message text to display in the target's terminal",
                },
            },
            "required": ["target_agent_id", "text"],
        },
    ),
    types.Tool(
        name="terminal.get_pending",
        description="Get undelivered terminal messages for the calling agent's role. "
                    "Marked as delivered after reading.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_role": {
                    "type": "string",
                    "description": "Role to check (defaults to caller's role)",
                },
            },
        },
    ),
]

# ── Dispatch ────────────────────────────────────────────────────────


async def handle_terminal_tool(
    db: Database,
    config: object,  # BridgeConfig — kept generic to avoid circular import
    name: str,
    args: dict,
) -> list[types.TextContent] | None:
    """Dispatch terminal tool calls to the appropriate handler."""
    if name == "terminal.send":
        return await _send_terminal_message(db, args)
    if name == "terminal.send_to_agent_id":
        return await _send_to_agent_id(db, args, config)
    if name == "terminal.get_pending":
        return await _get_pending_terminal(db, args)
    return None


# ── Handlers ────────────────────────────────────────────────────────


async def _send_terminal_message(
    db: Database,
    args: dict,
) -> list[types.TextContent]:
    target_role = args.get("target_role", "").strip()
    text = args.get("text", "").strip()
    sender = args.get("_sender_name") or args.get("_agent_id") or "unknown"

    if not target_role:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "missing_target_role", "detail": "target_role is required"}),
        )]
    if not text:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "missing_text", "detail": "text is required"}),
        )]

    msg_id = await db.queue_terminal_message(target_role, sender, text)
    logger.info("Terminal message %s queued for role '%s' from '%s'", msg_id, target_role, sender)

    return [types.TextContent(
        type="text",
        text=json.dumps({"status": "queued", "message_id": msg_id, "target_role": target_role}),
    )]


async def _send_to_agent_id(
    db: Database,
    args: dict,
    config: object,
) -> list[types.TextContent]:
    target_agent_id = args.get("target_agent_id", "").strip()
    text = args.get("text", "").strip()
    sender = args.get("_sender_name") or args.get("_agent_id") or "unknown"

    if not target_agent_id:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "missing_target_agent_id", "detail": "target_agent_id is required"}),
        )]
    if not text:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "missing_text", "detail": "text is required"}),
        )]

    # Resolve agent_id → role
    row = await db.execute_one(
        "SELECT role FROM agents WHERE agent_id = ?", (target_agent_id,),
    )
    if row:
        target_role = row["role"]
    else:
        # Try bridge.json fallback
        from agent_bridge.config import BridgeConfig  # noqa: PLC0415
        if isinstance(config, BridgeConfig):
            target_role = config.get_role_for_agent(target_agent_id)
        else:
            target_role = "default"

    if target_role == "default":
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "error": "agent_not_found",
                "detail": f"No agent found with ID '{target_agent_id}'",
            }),
        )]

    msg_id = await db.queue_terminal_message(target_role, sender, text)
    logger.info(
        "Terminal message %s queued for agent '%s' (role '%s') from '%s'",
        msg_id, target_agent_id, target_role, sender,
    )

    return [types.TextContent(
        type="text",
        text=json.dumps({
            "status": "queued",
            "message_id": msg_id,
            "target_agent_id": target_agent_id,
            "target_role": target_role,
        }),
    )]


async def _get_pending_terminal(
    db: Database,
    args: dict,
) -> list[types.TextContent]:
    target_role = args.get("target_role", "")
    if not target_role:
        target_role = args.get("_agent_role", "")
    if not target_role:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "missing_role", "detail": "target_role or _agent_role is required"}),
        )]

    # Deliver and fetch in one atomic operation
    delivered = await db.deliver_terminal_messages_for_role(target_role)

    return [types.TextContent(
        type="text",
        text=json.dumps({
            "status": "ok",
            "messages": [
                {
                    "id": m["id"],
                    "sender": m["sender"],
                    "text": m["text"],
                    "created_at": m["created_at"],
                }
                for m in delivered
            ],
        }),
    )]

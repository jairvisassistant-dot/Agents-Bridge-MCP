"""Chat tools — send/receive messages, thread management.

Includes @mention presence routing: when a message targets 'arquitecto' or
'desarrollador', the server checks if at least one agent with that role is
online or busy. If all are offline/nonexistent, a warning is returned.
"""

import json
import logging
import uuid
from datetime import datetime

import mcp.types as types

from agent_bridge.state.database import Database

logger = logging.getLogger(__name__)

# Maps chat @mention targets to agent DB roles for presence checking
TARGET_ROLE_MAP: dict[str, str] = {
    "arquitecto": "architect",
    "desarrollador": "developer",
}

CHAT_TOOLS = [
    types.Tool(
        name="chat.send",
        description="Send a message to the chat",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Message text"},
                "sender": {
                    "type": "string",
                    "description": "Sender name (human, arquitecto, desarrollador)",
                    "default": "human",
                },
                "target": {
                    "type": "string",
                    "description": "@mention target (arquitecto, desarrollador, all)",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID for replies",
                },
            },
            "required": ["text"],
        },
    ),
    types.Tool(
        name="chat.read",
        description="Read messages from the chat",
        inputSchema={
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Filter by thread"},
                "since": {"type": "string", "description": "Message ID to start from"},
                "target": {
                    "type": "string",
                    "description": "Filter by @mention target",
                },
            },
        },
    ),
    types.Tool(
        name="chat.thread_create",
        description="Create a new discussion thread",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Thread title"},
            },
            "required": ["title"],
        },
    ),
    types.Tool(
        name="chat.thread_list",
        description="List all discussion threads",
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def handle_chat_tool(
    db: Database, name: str, args: dict
) -> list[types.TextContent] | None:
    if name == "chat.send":
        return await _send_message(db, args)
    elif name == "chat.read":
        return await _read_messages(db, args)
    elif name == "chat.thread_create":
        return await _create_thread(db, args)
    elif name == "chat.thread_list":
        return await _list_threads(db)
    return None


def _format_timestamp(iso_str: str | None) -> str:
    """Format an ISO timestamp to HH:MM for warning messages."""
    if not iso_str:
        return "desconocida"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return str(iso_str)[:19]


async def _send_message(
    db: Database, args: dict
) -> list[types.TextContent]:
    text = args.get("text", "")
    sender = args.get("sender", "human")
    target = args.get("target")
    thread_id = args.get("thread_id")

    if not text:
        return [types.TextContent(type="text", text='{"error": "text required"}')]

    msg_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, thread_id, sender, target, text) VALUES (?, ?, ?, ?, ?)",
        (msg_id, thread_id, sender, target, text),
    )

    # ── @mention presence routing ──────────────────────────────────
    warning = None
    if target in TARGET_ROLE_MAP:
        role = TARGET_ROLE_MAP[target]
        online = await db.execute_one(
            "SELECT 1 FROM agents WHERE role = ? AND status IN ('online', 'busy') LIMIT 1",
            (role,),
        )
        if online is None:
            any_agent = await db.execute_one(
                "SELECT status, last_seen FROM agents WHERE role = ? LIMIT 1",
                (role,),
            )
            if any_agent:
                status = any_agent["status"]
                last_seen = _format_timestamp(any_agent["last_seen"])
                warning = (
                    f"El {target} está {status} desde las {last_seen}. "
                    "El mensaje quedó en su inbox."
                )
            else:
                warning = (
                    f"El {target} no está registrado. "
                    "El mensaje quedó en su inbox."
                )

    logger.info("Message from %s: %s", sender, text[:60])

    response: dict[str, str] = {"message_id": msg_id}
    if warning:
        response["warning"] = warning

    return [types.TextContent(type="text", text=json.dumps(response))]


async def _read_messages(
    db: Database, args: dict
) -> list[types.TextContent]:
    thread_id = args.get("thread_id")
    since = args.get("since")
    target = args.get("target")

    query = "SELECT * FROM messages WHERE 1=1"
    params: list = []

    if thread_id:
        query += " AND thread_id = ?"
        params.append(thread_id)

    if since:
        query += " AND id > ?"
        params.append(since)

    if target:
        # Include messages directed TO target PLUS public messages (no target)
        query += " AND (target = ? OR target IS NULL)"
        params.append(target)

    query += " ORDER BY created_at ASC"

    rows = await db.execute(query, tuple(params))
    messages = [
        {
            "id": r["id"],
            "thread_id": r["thread_id"],
            "sender": r["sender"],
            "target": r["target"],
            "text": r["text"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return [types.TextContent(type="text", text=json.dumps(messages))]


async def _create_thread(
    db: Database, args: dict
) -> list[types.TextContent]:
    title = args.get("title", "Untitled Thread")
    thread_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO threads (id, title) VALUES (?, ?)",
        (thread_id, title),
    )

    return [
        types.TextContent(
            type="text",
            text=json.dumps({"thread_id": thread_id, "title": title}),
        )
    ]


async def _list_threads(db: Database) -> list[types.TextContent]:
    rows = await db.execute(
        "SELECT id, title, status, created_at FROM threads ORDER BY created_at DESC"
    )
    threads = [
        {"id": r["id"], "title": r["title"], "status": r["status"]}
        for r in rows
    ]
    return [types.TextContent(type="text", text=json.dumps(threads))]

"""Chat tools — send/receive messages, thread management, discussion threads.

Includes @mention presence routing: when a message targets 'arquitecto' or
'desarrollador', the server checks if at least one agent with that role is
online or busy. If all are offline/nonexistent, a warning is returned.

Discussion threads support:
- Participants list (turn-taking enforced when present)
- Automatic turn advancement after each message
- chat.thread_get_pending(agent_name) — pending threads per agent
- chat.thread_resolve(thread_id) — manual resolution
- Auto-resolution by timeout in background maintenance loop
- Full backward compatibility for threads without participants
"""

import json
import logging
import uuid
from datetime import datetime

import mcp.types as types

from agent_bridge.state.database import Database


# Exceptions raised inside with_transaction() callbacks to signal *why* a
# send was rejected.  Catch order: _ThreadResolvedError → _TurnClaimError,
# so callers can return the correct error message.
class _TurnClaimError(Exception):
    """Turn was not available — wrong sender (current_turn didn't match)."""


class _ThreadResolvedError(_TurnClaimError):
    """Thread was already resolved — more specific than generic turn failure."""


logger = logging.getLogger(__name__)

# Maps chat @mention targets to agent DB roles for presence checking
TARGET_ROLE_MAP: dict[str, str] = {
    "arquitecto": "architect",
    "desarrollador": "developer",
}

# Valid message types for the enhanced messaging schema
VALID_MSG_TYPES = [
    "chat", "task_assignment", "status_update", "dependency_notification",
    "idle_notification", "shutdown_request", "shutdown_approved", "system", "ping",
]

VALID_PRIORITIES = ["normal", "high", "urgent"]

MAX_MESSAGE_LENGTH = 4000

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
                "msg_type": {
                    "type": "string",
                    "description": "Message type (chat, status_update, ping, etc.)",
                    "default": "chat",
                },
                "priority": {
                    "type": "string",
                    "description": "Priority (normal, high, urgent)",
                    "default": "normal",
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
                "since_rowid": {
                    "type": "integer",
                    "description": "Message rowid to start from (preferred — avoids UUID ambiguity)",
                },
                "since": {
                    "type": "string",
                    "description": "Legacy: message UUID to start from. Prefer since_rowid instead.",
                },
                "target": {
                    "type": "string",
                    "description": "Filter by @mention target",
                },
                "msg_type": {
                    "type": "string",
                    "description": "Filter by message type (chat, status_update, etc.)",
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Show only unread messages",
                    "default": False,
                },
                "priority_first": {
                    "type": "boolean",
                    "description": "Show urgent/high priority messages first",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default: no limit)",
                },
            },
        },
    ),
    types.Tool(
        name="chat.mark_read",
        description="Mark a specific message as read",
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message ID to mark as read"},
            },
            "required": ["message_id"],
        },
    ),
    types.Tool(
        name="chat.thread_create",
        description="Create a new discussion thread",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Thread title"},
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Participants (e.g. ["arquitecto", "desarrollador"]). Empty = public thread.',
                },
            },
            "required": ["title"],
        },
    ),
    types.Tool(
        name="chat.thread_list",
        description="List all discussion threads",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="chat.thread_get_pending",
        description="Get threads pending attention for a specific agent",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Agent name (e.g. arquitecto, desarrollador)",
                },
            },
        },
    ),
    types.Tool(
        name="chat.thread_resolve",
        description="Manually resolve (close) a discussion thread",
        inputSchema={
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Thread ID to resolve"},
            },
            "required": ["thread_id"],
        },
    ),
]


async def handle_chat_tool(db: Database, name: str, args: dict) -> list[types.TextContent] | None:
    if name == "chat.send":
        return await _send_message(db, args)
    elif name == "chat.read":
        return await _read_messages(db, args)
    elif name == "chat.mark_read":
        return await _mark_read(db, args)
    elif name == "chat.thread_create":
        return await _create_thread(db, args)
    elif name == "chat.thread_list":
        return await _list_threads(db)
    elif name == "chat.thread_get_pending":
        return await _thread_get_pending(db, args)
    elif name == "chat.thread_resolve":
        return await _resolve_thread(db, args)
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


def _parse_participants(row) -> list[str]:
    """Parse the participants JSON column into a list."""
    raw = row["participants"] if row else "[]"
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _advance_turn(participants: list[str], current_sender: str) -> str | None:
    """Return the next participant to speak, or None if no participants."""
    if not participants:
        return None
    if current_sender in participants:
        idx = participants.index(current_sender)
        next_idx = (idx + 1) % len(participants)
        return participants[next_idx]
    # Sender not in participants — don't change turn
    return None  # caller interprets None as "don't change"


async def _send_message(db: Database, args: dict) -> list[types.TextContent]:
    text = args.get("text", "")
    sender = args.get("sender") or args.get("_sender_name") or "human"
    target = args.get("target")
    thread_id = args.get("thread_id")
    msg_type = args.get("msg_type", "chat")
    priority = args.get("priority", "normal")

    if not text:
        return [types.TextContent(type="text", text=json.dumps({"error": "text required"}))]

    if len(text) > MAX_MESSAGE_LENGTH:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": "message_too_long", "max_length": MAX_MESSAGE_LENGTH}),
            )
        ]

    if msg_type not in VALID_MSG_TYPES:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": "invalid_msg_type", "valid_types": VALID_MSG_TYPES}),
            )
        ]

    if priority not in VALID_PRIORITIES:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": "invalid_priority", "valid_priorities": VALID_PRIORITIES}),
            )
        ]

    # ── Thread validation (pre-check — fast path, may be stale) ─────
    has_participants = False
    participants: list[str] = []
    if thread_id:
        thread = await db.execute_one("SELECT * FROM threads WHERE id = ?", (thread_id,))
        if thread is None:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": "thread_not_found", "detail": "El thread no existe"}),
                )
            ]

        if thread["status"] == "resolved":
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": "thread_resolved", "detail": "El thread ya está resuelto"}),
                )
            ]

        participants = _parse_participants(thread)
        if participants:
            has_participants = True
            # Snapshot the turn at request time, used inside the write lock to
            # reject line-cutting: a participant who did NOT have the turn at
            # request time cannot sneak through when the turn cycles back to
            # them while they wait for the write lock.
            pre_check_turn = thread["current_turn"]

    msg_id = str(uuid.uuid4())
    turn_number = None

    # ── Atomic send (ALL three paths use with_transaction) ───────────
    # LOCK-WINNER SEMANTICS for send-vs-resolve races
    # ─────────────────────────────────────────────────────────
    # Every path re-checks thread status FROM INSIDE the write lock
    # (BEGIN IMMEDIATE) so that a concurrent resolve cannot sneak past
    # our pre-check.  The operation that acquires the lock *first*
    # decides the outcome:
    #
    #   • resolve wins  → send sees status='resolved' → rejected
    #   • send wins     → message is persisted, resolve commits after
    #
    # Both outcomes leave the system in a consistent state — no orphaned
    # messages, no resolved-while-open contradiction.

    if has_participants and sender in participants:
        next_turn = _advance_turn(participants, sender)

        def _participant_sync(conn):
            # Re-check thread status inside the write lock to catch
            # concurrent resolves that snuck past the pre-check.
            cur = conn.execute("SELECT status FROM threads WHERE id = ?", (thread_id,))
            row = cur.fetchone()
            if row is None:
                raise _TurnClaimError()
            if row["status"] == "resolved":
                raise _ThreadResolvedError()

            # Atomically claim the turn.
            # The pre_check_turn prevents TWO distinct races:
            #   (i)  Send-vs-resolve:   status = 'open' catches this.
            #   (ii) Cross-participant: current_turn must match the
            #        *pre-check* value AND the sender must have been
            #        that turn-holder.  This stops a participant who
            #        did NOT have the turn at request time from
            #        "cutting in line" when the turn cycles back to
            #        them while they waited for the write lock.
            cur = conn.execute(
                """UPDATE threads
                   SET current_turn = ?, last_activity_at = datetime('now')
                   WHERE id = ?
                     AND status = 'open'
                     AND (? IS NULL OR (current_turn = ? AND ? = ?))""",
                (next_turn, thread_id,
                 pre_check_turn,           # NULL → first-message free-for-all
                 pre_check_turn, sender, pre_check_turn),  # strict match
            )
            if cur.rowcount == 0:
                raise _TurnClaimError()

            # 1c. Insert the message
            conn.execute(
                """INSERT INTO messages
                       (id, thread_id, sender, target, text, msg_type, priority, turn_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?,
                     (SELECT COALESCE(MAX(turn_number), 0) + 1
                        FROM messages WHERE thread_id = ?)
                   )""",
                (msg_id, thread_id, sender, target, text, msg_type, priority, thread_id),
            )

            # 1d. Read back the assigned turn_number
            cur = conn.execute("SELECT turn_number FROM messages WHERE id = ?", (msg_id,))
            row = cur.fetchone()
            return row[0] if row is not None else None

        try:
            turn_number = await db.with_transaction(_participant_sync)
        except _ThreadResolvedError:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": "thread_resolved", "detail": "El thread fue resuelto concurrentemente"}),
                )
            ]
        except _TurnClaimError:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "not_your_turn",
                            "detail": "El turno ya fue tomado por otro mensaje concurrente",
                        }
                    ),
                )
            ]

    elif has_participants:
        # Non-participant (e.g. human) — allow without changing turn.
        def _non_participant_sync(conn):
            cur = conn.execute("SELECT status FROM threads WHERE id = ?", (thread_id,))
            row = cur.fetchone()
            if row is None:
                raise _TurnClaimError()
            if row["status"] == "resolved":
                raise _ThreadResolvedError()

            conn.execute(
                "UPDATE threads SET last_activity_at = datetime('now') WHERE id = ? AND status = 'open'",
                (thread_id,),
            )
            conn.execute(
                "INSERT INTO messages (id, thread_id, sender, target, text, "
                "msg_type, priority) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, thread_id, sender, target, text, msg_type, priority),
            )
            return None

        try:
            await db.with_transaction(_non_participant_sync)
        except _ThreadResolvedError:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": "thread_resolved", "detail": "El thread fue resuelto concurrentemente"}),
                )
            ]

    else:
        # Thread without participants — no turn-taking.
        def _public_sync(conn):
            if thread_id:
                cur = conn.execute("SELECT status FROM threads WHERE id = ?", (thread_id,))
                row = cur.fetchone()
                if row is None:
                    raise _TurnClaimError()
                if row["status"] == "resolved":
                    raise _ThreadResolvedError()

            conn.execute(
                "INSERT INTO messages (id, thread_id, sender, target, text, "
                "msg_type, priority) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, thread_id, sender, target, text, msg_type, priority),
            )
            if thread_id:
                conn.execute(
                    "UPDATE threads SET last_activity_at = datetime('now') WHERE id = ? AND status = 'open'",
                    (thread_id,),
                )
            return None

        try:
            await db.with_transaction(_public_sync)
        except _ThreadResolvedError:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": "thread_resolved", "detail": "El thread fue resuelto concurrentemente"}),
                )
            ]

    # ── @mention presence routing ──────────────────────────────────
    # PROD-04: reject message + register pending mention for auto-delivery
    # when the agent reconnects.
    if target in TARGET_ROLE_MAP:
        role = TARGET_ROLE_MAP[target]
        online = await db.execute_one(
            "SELECT 1 FROM agents WHERE role = ? AND status IN ('online', 'busy') LIMIT 1",
            (role,),
        )
        if online is None:
            # Register the pending mention for auto-delivery on reconnect
            await db.add_pending_mention(role, sender, text, thread_id)

            # Diagnose: platform vs agent problem
            any_agent = await db.execute_one(
                "SELECT status, last_seen FROM agents WHERE role = ? LIMIT 1",
                (role,),
            )

            # Check if ANY agents are online (platform health)
            any_online = await db.execute_one(
                "SELECT 1 FROM agents WHERE status IN ('online', 'busy') LIMIT 1",
            )

            if any_agent is None:
                error = (
                    f"El agente '{target}' no está registrado en el sistema. "
                    "Verificá la configuración en bridge.json y asegurate de "
                    "que el agente esté corriendo con AGENT_BRIDGE_ID correcto. "
                    "El mensaje quedó pendiente y se entregará automáticamente "
                    "cuando el agente se conecte."
                )
            else:
                status = any_agent["status"]
                last_seen = _format_timestamp(any_agent["last_seen"])
                if status == "offline":
                    base = (
                        f"El agente '{target}' está desconectado desde las {last_seen}."
                    )
                elif status == "away":
                    base = (
                        f"El agente '{target}' está ausente desde las {last_seen}."
                    )
                else:
                    base = f"El agente '{target}' no está disponible ({status})."

                if any_online:
                    diag = (
                        " Otros agentes están conectados — el problema es específico de "
                        f"'{target}'. Revisá su terminal y asegurate de que el proceso "
                        "del agente esté corriendo."
                    )
                else:
                    diag = (
                        " No hay ningún agente conectado — puede haber un problema de "
                        "plataforma. Verificá que el servidor SSE esté funcionando "
                        "y que los agentes estén configurados correctamente."
                    )
                error = base + diag

            error += (
                f" El mensaje quedó registrado y se entregará automáticamente "
                f"cuando {target} se reconecte."
            )

            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "agent_not_available", "detail": error}),
            )]

    # PROD-02: notify in-process listeners for immediate TUI refresh
    db.signal_new_message()

    logger.info("Message from %s: %s", sender, text[:60])

    response: dict[str, str] = {"message_id": msg_id}
    if turn_number is not None:
        response["turn_number"] = turn_number

    return [types.TextContent(type="text", text=json.dumps(response))]


async def _read_messages(db: Database, args: dict) -> list[types.TextContent]:
    thread_id = args.get("thread_id")
    since_rowid = args.get("since_rowid")
    since = args.get("since")
    target = args.get("target")
    msg_type_filter = args.get("msg_type")
    unread_only = args.get("unread_only", False)
    priority_first = args.get("priority_first", False)
    limit = args.get("limit")

    query = "SELECT rowid, * FROM messages WHERE 1=1"
    params: list = []

    if thread_id:
        query += " AND thread_id = ?"
        params.append(thread_id)

    # since_rowid (int) is the preferred parameter for polling — avoids
    # ambiguity with UUIDs that happen to be parseable as integers.
    # since (string UUID) is kept for backward compatibility.
    if since_rowid is not None:
        query += " AND rowid > ?"
        params.append(since_rowid)
    elif since:
        try:
            since_rowid_int = int(since)
            query += " AND rowid > ?"
            params.append(since_rowid_int)
        except ValueError:
            # Backward-compat: lookup rowid by UUID
            query += " AND rowid > COALESCE((SELECT rowid FROM messages WHERE id = ?), -1)"
            params.append(since)

    if target:
        # Include messages directed TO target PLUS public messages (no target)
        query += " AND (target = ? OR target IS NULL)"
        params.append(target)

    if msg_type_filter:
        query += " AND msg_type = ?"
        params.append(msg_type_filter)

    if unread_only:
        query += " AND read = 0"

    # Ordering: priority_first then causal
    if priority_first:
        query += (
            " ORDER BY"
            "   CASE priority"
            "     WHEN 'urgent' THEN 0"
            "     WHEN 'high' THEN 1"
            "     ELSE 2"
            "   END,"
            "   rowid ASC"
        )
    else:
        query += " ORDER BY rowid ASC"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    rows = await db.execute(query, tuple(params))
    messages = []
    for r in rows:
        messages.append(
            {
                "rowid": r["rowid"],
                "id": r["id"],
                "thread_id": r["thread_id"],
                "sender": r["sender"],
                "target": r["target"],
                "text": r["text"],
                "msg_type": r["msg_type"],
                "priority": r["priority"],
                "read": bool(r["read"]),
                "turn_number": r["turn_number"],
                "created_at": r["created_at"],
            }
        )

    return [types.TextContent(type="text", text=json.dumps(messages))]


async def _create_thread(db: Database, args: dict) -> list[types.TextContent]:
    title = args.get("title", "Untitled Thread")
    participants = args.get("participants", [])
    thread_id = str(uuid.uuid4())

    participants_json = json.dumps(participants)
    await db.execute(
        "INSERT INTO threads (id, title, participants, last_activity_at) VALUES (?, ?, ?, datetime('now'))",
        (thread_id, title, participants_json),
    )

    response = {"thread_id": thread_id, "title": title}
    if participants:
        response["participants"] = participants

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def _list_threads(db: Database) -> list[types.TextContent]:
    rows = await db.execute(
        "SELECT id, title, status, participants, current_turn, last_activity_at, created_at "
        "FROM threads ORDER BY created_at DESC"
    )
    threads = []
    for r in rows:
        t = {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "participants": _parse_participants(r),
            "current_turn": r["current_turn"],
            "last_activity_at": r["last_activity_at"],
        }
        threads.append(t)
    return [types.TextContent(type="text", text=json.dumps(threads))]


async def _thread_get_pending(db: Database, args: dict) -> list[types.TextContent]:
    """Return open threads where the given agent's participation is expected."""
    agent_name = args.get("agent_name")
    if not agent_name:
        return [types.TextContent(type="text", text=json.dumps({"error": "agent_name required"}))]

    # Pending = open thread with participants that include agent_name,
    #           AND (it's their turn OR the thread just started)
    rows = await db.execute(
        """SELECT * FROM threads
           WHERE status = 'open'
             AND participants != '[]'
           ORDER BY last_activity_at DESC"""
    )

    pending = []
    for r in rows:
        p = _parse_participants(r)
        if agent_name not in p:
            continue
        turn = r["current_turn"]

        # When current_turn is NULL, distinguish "just created (no activity)"
        # from "activity without turn assignment".  A thread whose
        # last_activity_at equals its created_at has no messages yet.
        if turn is None and r["last_activity_at"] == r["created_at"]:
            continue

        if turn is not None and turn != agent_name:
            continue
        pending.append(
            {
                "id": r["id"],
                "title": r["title"],
                "participants": p,
                "current_turn": turn,
                "last_activity_at": r["last_activity_at"],
            }
        )

    return [types.TextContent(type="text", text=json.dumps(pending))]


async def _resolve_thread(db: Database, args: dict) -> list[types.TextContent]:
    """Manually resolve (close) a discussion thread."""
    thread_id = args.get("thread_id")
    if not thread_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "thread_id required"}))]

    thread = await db.execute_one("SELECT * FROM threads WHERE id = ?", (thread_id,))
    if thread is None:
        return [types.TextContent(type="text", text=json.dumps({"error": "thread not found"}))]

    if thread["status"] == "resolved":
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"thread_id": thread_id, "status": "resolved", "note": "Thread was already resolved"}),
            )
        ]

    won = await db.resolve_thread_atomic(thread_id, "Thread resolved by participant.")

    if won:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"thread_id": thread_id, "status": "resolved"}),
            )
        ]
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "thread_id": thread_id,
                    "status": "resolved",
                    "note": "Thread was already resolved (concurrent resolve won)",
                }
            ),
        )
    ]


async def _mark_read(db: Database, args: dict) -> list[types.TextContent]:
    """Mark a specific message as read."""
    message_id = args.get("message_id")
    if not message_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "message_id required"}))]

    await db.mark_message_read(message_id)
    return [types.TextContent(type="text", text=json.dumps({"message_id": message_id, "status": "marked_read"}))]

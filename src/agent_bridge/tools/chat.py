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
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of participants (e.g. [\"arquitecto\", \"desarrollador\"]). Empty = public thread.",
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


async def _send_message(
    db: Database, args: dict
) -> list[types.TextContent]:
    text = args.get("text", "")
    sender = args.get("sender", "human")
    target = args.get("target")
    thread_id = args.get("thread_id")

    if not text:
        return [types.TextContent(type="text", text='{"error": "text required"}')]

    # ── Thread validation (pre-check — fast path, may be stale) ─────
    has_participants = False
    participants: list[str] = []
    if thread_id:
        thread = await db.execute_one(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        )
        if thread is None:
            return [types.TextContent(type="text", text=json.dumps({"error": "thread_not_found", "detail": "El thread no existe"}))]

        # Pre-check for resolved — catches the common case before any write.
        # A concurrent resolve that lands after this point is detected inside
        # the atomic transaction via _ThreadResolvedError.
        if thread["status"] == "resolved":
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "thread_resolved", "detail": "El thread ya está resuelto"}),
            )]

        participants = _parse_participants(thread)
        if participants:
            has_participants = True
            # Snapshot the turn value at pre-check time, before any write.
            # Used inside the transaction to reject cross-participant races
            # where the sender didn't hold the turn at request time.
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
            # 1a. Re-check thread status inside the write lock
            cur = conn.execute(
                "SELECT status FROM threads WHERE id = ?", (thread_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise _TurnClaimError()
            if row["status"] == "resolved":
                raise _ThreadResolvedError()

            # 1b. Atomically claim the turn.
            #
            # The WHERE clause prevents TWO distinct races:
            #   (i)  Send-vs-resolve:   status = 'open' catches this.
            #   (ii) Cross-participant: current_turn must match the
            #        *pre-check* value AND the sender must have been
            #        that turn-holder.  This stops a participant who
            #        did NOT have the turn at request time from
            #        "cutting in line" when the turn cycles back to
            #        them while they waited for the write lock.
            #
            # Semantics:
            #   ? IS NULL
            #     → pre_check_turn was NULL → first message → anyone can
            #       start (benign race, both participants get through).
            #   current_turn = ? AND ? = ?
            #     → turn hasn't changed SINCE pre-check AND the sender
            #       was the expected speaker at pre-check time.  This
            #       prevents a participant from "cutting in line" when
            #       the turn cycles back to them while they waited.
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
                       (id, thread_id, sender, target, text, turn_number)
                   VALUES (?, ?, ?, ?, ?,
                     (SELECT COALESCE(MAX(turn_number), 0) + 1
                        FROM messages WHERE thread_id = ?)
                   )""",
                (msg_id, thread_id, sender, target, text, thread_id),
            )

            # 1d. Read back the assigned turn_number
            cur = conn.execute(
                "SELECT turn_number FROM messages WHERE id = ?", (msg_id,)
            )
            row = cur.fetchone()
            return row[0] if row is not None else None

        try:
            turn_number = await db.with_transaction(_participant_sync)
        except _ThreadResolvedError:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "thread_resolved", "detail": "El thread fue resuelto concurrentemente"}),
            )]
        except _TurnClaimError:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "error": "not_your_turn",
                    "detail": "El turno ya fue tomado por otro mensaje concurrente",
                }),
            )]

    elif has_participants:
        # Non-participant (e.g. human) — allow without changing turn.
        def _non_participant_sync(conn):
            cur = conn.execute(
                "SELECT status FROM threads WHERE id = ?", (thread_id,)
            )
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
                "INSERT INTO messages (id, thread_id, sender, target, text) VALUES (?, ?, ?, ?, ?)",
                (msg_id, thread_id, sender, target, text),
            )
            return None

        try:
            await db.with_transaction(_non_participant_sync)
        except _ThreadResolvedError:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "thread_resolved", "detail": "El thread fue resuelto concurrentemente"}),
            )]

    else:
        # Thread without participants — no turn-taking.
        def _public_sync(conn):
            if thread_id:
                cur = conn.execute(
                    "SELECT status FROM threads WHERE id = ?", (thread_id,)
                )
                row = cur.fetchone()
                if row is None:
                    raise _TurnClaimError()
                if row["status"] == "resolved":
                    raise _ThreadResolvedError()

            conn.execute(
                "INSERT INTO messages (id, thread_id, sender, target, text) VALUES (?, ?, ?, ?, ?)",
                (msg_id, thread_id, sender, target, text),
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
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "thread_resolved", "detail": "El thread fue resuelto concurrentemente"}),
            )]

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
    if turn_number is not None:
        response["turn_number"] = turn_number

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

    # Causal ordering by rowid (insertion order).  Every INSERT runs inside
    # with_transaction (or a serialized write), so rowid reflects the true
    # causal sequence regardless of sender type (participant / human / system)
    # or whether the message has a turn_number.
    query += " ORDER BY rowid ASC"

    rows = await db.execute(query, tuple(params))
    messages = [
        {
            "id": r["id"],
            "thread_id": r["thread_id"],
            "sender": r["sender"],
            "target": r["target"],
            "text": r["text"],
            "turn_number": r["turn_number"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return [types.TextContent(type="text", text=json.dumps(messages))]


async def _create_thread(
    db: Database, args: dict
) -> list[types.TextContent]:
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
        "SELECT id, title, status, participants, current_turn, last_activity_at, created_at FROM threads ORDER BY created_at DESC"
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


async def _thread_get_pending(
    db: Database, args: dict
) -> list[types.TextContent]:
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
             AND INSTR(participants, ?) > 0
             AND (current_turn IS NULL OR current_turn = ?)
           ORDER BY last_activity_at DESC""",
        (json.dumps(agent_name), agent_name),
    )

    pending = []
    for r in rows:
        pending.append({
            "id": r["id"],
            "title": r["title"],
            "participants": _parse_participants(r),
            "current_turn": r["current_turn"],
            "last_activity_at": r["last_activity_at"],
        })

    return [types.TextContent(type="text", text=json.dumps(pending))]


async def _resolve_thread(
    db: Database, args: dict
) -> list[types.TextContent]:
    """Manually resolve (close) a discussion thread."""
    thread_id = args.get("thread_id")
    if not thread_id:
        return [types.TextContent(type="text", text=json.dumps({"error": "thread_id required"}))]

    thread = await db.execute_one(
        "SELECT * FROM threads WHERE id = ?", (thread_id,)
    )
    if thread is None:
        return [types.TextContent(type="text", text=json.dumps({"error": "thread not found"}))]

    if thread["status"] == "resolved":
        return [types.TextContent(
            type="text",
            text=json.dumps({"thread_id": thread_id, "status": "resolved", "note": "Thread was already resolved"}),
        )]

    won = await db.resolve_thread_atomic(thread_id, "Thread resolved by participant.")

    if won:
        return [types.TextContent(
            type="text",
            text=json.dumps({"thread_id": thread_id, "status": "resolved"}),
        )]
    return [types.TextContent(
        type="text",
        text=json.dumps({
            "thread_id": thread_id, "status": "resolved",
            "note": "Thread was already resolved (concurrent resolve won)",
        }),
    )]

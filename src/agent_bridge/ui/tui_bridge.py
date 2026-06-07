"""In-process bridge between the TUI and the shared Database.

No MCP subprocess needed — imports Database directly.
All operations are async via anyio.to_thread.run_sync on the Database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from agent_bridge.state.database import Database

# ── Exceptions ─────────────────────────────────────────────────────────────────


class TaskValidationError(ValueError):
    """Raised when task data fails validation (e.g. empty title)."""


class TuiBridge:
    """In-process bridge between TUI and the shared Database.

    Wraps Database with convenience methods for the kanban and chat UIs.
    All DB operations run in a worker thread via anyio.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Tasks ──────────────────────────────────────────────────────

    async def get_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """Return tasks, optionally filtered by status.

        Results are ordered by created_at ascending.
        """
        if status:
            rows = await self._db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at ASC",
                (status,),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM tasks ORDER BY created_at ASC",
            )
        return [dict(r) for r in rows]

    async def get_task_counts(self) -> dict[str, int]:
        """Return a dict mapping each status to its task count."""
        rows = await self._db.execute(
            "SELECT status, COUNT(*) AS cnt FROM tasks GROUP BY status",
        )
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = r["cnt"]
        return counts

    async def move_task(self, task_id: str, new_status: str) -> bool:
        """Change a task's status. Uses state machine validation.

        Returns True if the update was applied, False if the transition
        is not allowed (terminal state, invalid transition) or the task
        was not found.
        Validates atomically inside with_transaction so a concurrent
        status change cannot bypass the state machine check.
        """
        from agent_bridge.state.state_machine import can_transition

        def _do_move(conn):
            cur = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if row is None:
                return False
            current = row["status"]
            if not can_transition("task", current, new_status):
                return False
            cur = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ? AND status = ?",
                (new_status, task_id, current),
            )
            return cur.rowcount > 0

        return await self._db.with_transaction(_do_move)

    async def create_task(
        self,
        title: str,
        description: str = "",
        plan_id: str | None = None,
    ) -> str:
        """Create a new task and return its id.

        Auto-generates UUID, sets status='pending', created_at=now.

        Raises:
            TaskValidationError: if title is empty or only whitespace.
            Exception: DB-level errors (FK constraint, etc.) propagate.
        """
        if not title or not title.strip():
            raise TaskValidationError("Title cannot be empty")
        task_id = str(uuid.uuid4())
        await self._db.execute_write(
            "INSERT INTO tasks (id, plan_id, title, description, status) VALUES (?, ?, ?, ?, 'pending')",
            (task_id, plan_id or "", title.strip(), description),
        )
        return task_id

    # ── Plans ──────────────────────────────────────────────────────

    async def get_plans(self) -> list[dict[str, Any]]:
        """Return all plans ordered by created_at descending."""
        rows = await self._db.execute(
            "SELECT * FROM plans ORDER BY created_at DESC",
        )
        return [dict(r) for r in rows]

    # ── Agents ─────────────────────────────────────────────────────

    async def get_agents(self) -> list[dict[str, Any]]:
        """Return all registered agents."""
        rows = await self._db.execute("SELECT * FROM agents")
        return [dict(r) for r in rows]

    async def get_agent_statuses(self) -> dict[str, str]:
        """Return a dict of agent_id → status for quick display."""
        rows = await self._db.execute(
            "SELECT agent_id, status FROM agents WHERE status != 'offline'",
        )
        return {r["agent_id"]: r["status"] for r in rows}

    # ── Messages ───────────────────────────────────────────────────

    async def get_messages_for_task(self, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return messages where thread_id = task_id, ordered by created_at asc.

        Args:
            task_id: The task id to filter by (maps to thread_id column).
            limit: Maximum number of messages (default 50).
        """
        rows = await self._db.execute(
            "SELECT rowid, * FROM messages WHERE thread_id = ? ORDER BY created_at ASC LIMIT ?",
            (task_id, limit),
        )
        return [dict(r) for r in rows]

    async def send_message(
        self,
        text: str,
        sender: str = "human",
        target: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Insert a chat message and return its id.

        The caller should validate text is non-empty before calling.
        """
        msg_id = str(uuid.uuid4())
        await self._db.execute_write(
            "INSERT INTO messages (id, sender, target, text, thread_id) VALUES (?, ?, ?, ?, ?)",
            (msg_id, sender, target, text, thread_id),
        )
        return msg_id

    async def get_messages(
        self,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return messages ordered by rowid ascending.

        Args:
            since: If given, return only messages with rowid > since.
            limit: Maximum number of messages (default 100).
        """
        if since:
            rows = await self._db.execute(
                "SELECT rowid, * FROM messages WHERE rowid > ? ORDER BY rowid ASC LIMIT ?",
                (since, limit),
            )
        else:
            rows = await self._db.execute(
                "SELECT rowid, * FROM messages ORDER BY rowid ASC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    async def get_connection_status(self) -> str:
        """Return a human-readable connection status summary.

        Checks agent count and last activity.
        """
        agent_count = await self._db.execute_one("SELECT COUNT(*) AS cnt FROM agents")
        total = agent_count["cnt"] if agent_count else 0
        online = await self._db.execute_one(
            "SELECT COUNT(*) AS cnt FROM agents WHERE status != 'offline'",
        )
        online_count = online["cnt"] if online else 0
        if total == 0:
            return "⚫ Sin conexiones"
        return f"🟢 {online_count}/{total} agentes conectados"

    async def get_unread_message_count(self) -> int:
        """Return count of unread messages (read=0) for general chat.

        General chat messages have no target (target IS NULL) and no
        thread_id (i.e. they are not scoped to a specific task).
        Contextual messages (with thread_id set) are not included.
        """
        row = await self._db.execute_one(
            "SELECT COUNT(*) AS cnt FROM messages WHERE read = 0 AND target IS NULL AND thread_id IS NULL"
        )
        return row["cnt"] if row else 0

    @staticmethod
    def _format_time(iso_str: str) -> str:
        """Format ISO timestamp to HH:MM in local time."""
        from datetime import timezone

        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone()
            return dt.strftime("%H:%M")
        except (ValueError, TypeError):
            return iso_str[:5] if len(iso_str) >= 5 else iso_str

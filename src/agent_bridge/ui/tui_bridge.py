"""In-process bridge between the TUI and the shared Database.

No MCP subprocess needed — imports Database directly.
All operations are async via anyio.to_thread.run_sync on the Database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
        """Change a task's status via the centralized guard.

        Delegates to ``Database.transition_task()`` which validates the
        state machine transition and applies it atomically with
        optimistic locking.

        Returns:
            True if the transition was applied, False otherwise.
        """
        return await self._db.transition_task(task_id, new_status)

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

    async def update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> bool:
        """Update a task's title and/or description.

        Only tasks with status ``pending`` or ``in_progress`` can be
        updated.  If neither *title* nor *description* is provided the
        method returns ``False`` immediately.

        Returns:
            True if the task was updated, False if the task was not
            found, is in a non-updatable status, or nothing to update.
        """
        if not title and not description:
            return False

        row = await self._db.execute_one(
            "SELECT status FROM tasks WHERE id = ?", (task_id,),
        )
        if row is None:
            return False
        if row["status"] not in ("pending", "in_progress"):
            return False

        updates: list[str] = []
        params: list[str] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        updates.append("updated_at = datetime('now')")
        params.append(task_id)

        await self._db.execute_write(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        return True

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task permanently.

        Only tasks with status ``pending`` or ``in_progress`` can be
        deleted.  Associated review rows are removed first.

        Returns:
            True if the task was deleted, False if the task was not
            found or is in a non-deletable status.
        """
        row = await self._db.execute_one(
            "SELECT status FROM tasks WHERE id = ?", (task_id,),
        )
        if row is None:
            return False
        if row["status"] not in ("pending", "in_progress"):
            return False

        def _do_delete(conn):
            conn.execute("DELETE FROM reviews WHERE task_id = ?", (task_id,))
            conn.execute(
                "DELETE FROM tasks WHERE id = ? AND status IN ('pending','in_progress')",
                (task_id,),
            )

        await self._db.with_transaction(_do_delete)
        return True

    # ── Plans ──────────────────────────────────────────────────────

    async def get_plans(self) -> list[dict[str, Any]]:
        """Return all plans ordered by created_at descending."""
        rows = await self._db.execute(
            "SELECT * FROM plans ORDER BY created_at DESC",
        )
        return [dict(r) for r in rows]

    # ── Agents ─────────────────────────────────────────────────────

    async def get_available_agents(self) -> list[dict[str, Any]]:
        """Return agents whose status is not 'offline'.

        Used by the assign-task modal to show available assignees.
        """
        rows = await self._db.execute(
            "SELECT * FROM agents WHERE status != 'offline'",
        )
        return [dict(r) for r in rows]

    async def assign_task(self, task_id: str, agent_id: str) -> bool:
        """Assign a pending task to an agent.

        Checks the agent exists, then atomically sets the task's
        ``assignee`` and transitions its status to ``in_progress``.
        Only tasks in ``pending`` status can be assigned.

        Returns:
            True if the task was assigned, False if the agent does not
            exist, the task was not found, or its status is not
            ``pending``.
        """
        agent = await self._db.execute_one(
            "SELECT agent_id FROM agents WHERE agent_id = ?",
            (agent_id,),
        )
        if agent is None:
            return False

        def _do_assign(conn):
            cur = conn.execute(
                "UPDATE tasks SET assignee = ?, status = 'in_progress', updated_at = datetime('now') "
                "WHERE id = ? AND status = 'pending'",
                (agent_id, task_id),
            )
            return cur.rowcount > 0

        return await self._db.with_transaction(_do_assign)

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
        # PROD-02: wake up in-process listeners for immediate refresh
        self._db.signal_new_message()
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

        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            dt = dt.astimezone()
            return dt.strftime("%H:%M")
        except (ValueError, TypeError):
            return iso_str[:5] if len(iso_str) >= 5 else iso_str

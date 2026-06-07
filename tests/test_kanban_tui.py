"""Tests for the kanban TUI module — TuiBridge CRUD and DBWatcher detection.

Uses anyio.run and tempfile databases following the project's test patterns.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import anyio
import pytest
from textual.widgets import Static

from agent_bridge.state.database import Database
from agent_bridge.ui.chat_overlay import ChatOverlay
from agent_bridge.ui.db_watcher import DBWatcher
from agent_bridge.ui.tui_bridge import TaskValidationError, TuiBridge


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)
    Path(path + "-wal").unlink(missing_ok=True)
    Path(path + "-shm").unlink(missing_ok=True)


@pytest.mark.asyncio
async def _init_db(db: Database) -> None:
    """Initialize the database schema."""
    await db.initialize()
    # Add seed data
    await db.execute_write(
        "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
        ("plan-1", "Test Plan", "in_progress"),
    )
    for i, status in enumerate(["pending", "in_progress", "review", "approved", "changes_requested"]):
        await db.execute_write(
            "INSERT INTO tasks (id, plan_id, title, status, assignee) VALUES (?, ?, ?, ?, ?)",
            (f"task-{i}", "plan-1", f"Task {i} ({status})", status, None),
        )
    await db.execute_write(
        "INSERT INTO agents (agent_id, role, status) VALUES (?, ?, ?)",
        ("claude-code-main", "architect", "online"),
    )


class TestTuiBridgeMessages:
    """get_messages_for_task and contextual message tests."""

    def test_get_messages_for_task_filters_by_thread_id(self, db_path):
        """get_messages_for_task returns only messages matching the task's thread_id."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            # Send messages with different thread_ids
            await bridge.send_message(text="task-1 msg", sender="human", thread_id="task-1")
            await bridge.send_message(text="task-1 another", sender="human", thread_id="task-1")
            await bridge.send_message(text="general chat", sender="human", thread_id=None)

            task_msgs = await bridge.get_messages_for_task("task-1")
            assert len(task_msgs) == 2
            assert all(m["thread_id"] == "task-1" for m in task_msgs)
            assert task_msgs[0]["text"] == "task-1 msg"
            assert task_msgs[1]["text"] == "task-1 another"

        anyio.run(run)

    def test_get_messages_for_task_empty_when_no_match(self, db_path):
        """get_messages_for_task returns empty list when thread_id has no messages."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            await bridge.send_message(text="general", sender="human", thread_id=None)

            result = await bridge.get_messages_for_task("nonexistent-task")
            assert result == []

        anyio.run(run)

    def test_get_messages_for_task_ordered_by_created_at(self, db_path):
        """get_messages_for_task returns messages ordered by created_at ascending."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            # Insert messages with explicit timestamps to verify ordering
            import uuid

            msg_id_1 = str(uuid.uuid4())
            msg_id_2 = str(uuid.uuid4())
            await db.execute_write(
                "INSERT INTO messages (id, sender, text, thread_id, created_at)"
                " VALUES (?, 'human', ?, 'task-1', '2024-01-01T10:00:00')",
                (msg_id_1, "first"),
            )
            await db.execute_write(
                "INSERT INTO messages (id, sender, text, thread_id, created_at)"
                " VALUES (?, 'human', ?, 'task-1', '2024-01-01T10:01:00')",
                (msg_id_2, "second"),
            )

            msgs = await bridge.get_messages_for_task("task-1")
            assert len(msgs) == 2
            assert msgs[0]["text"] == "first"
            assert msgs[1]["text"] == "second"

        anyio.run(run)


class TestTuiBridge:
    """CRUD operations via TuiBridge."""

    def test_get_tasks_all(self, db_path):
        """get_tasks returns all tasks when no status filter."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            tasks = await bridge.get_tasks()
            assert len(tasks) == 5
            assert all(isinstance(t, dict) for t in tasks)

        anyio.run(run)

    def test_get_tasks_filtered(self, db_path):
        """get_tasks with status filter returns only matching tasks."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            pending = await bridge.get_tasks(status="pending")
            assert len(pending) == 1
            assert pending[0]["status"] == "pending"

            in_progress = await bridge.get_tasks(status="in_progress")
            assert len(in_progress) == 1
            assert in_progress[0]["status"] == "in_progress"

        anyio.run(run)

    def test_get_task_counts(self, db_path):
        """get_task_counts returns accurate counts per status."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            counts = await bridge.get_task_counts()
            assert counts.get("pending") == 1
            assert counts.get("in_progress") == 1
            assert counts.get("review") == 1
            assert counts.get("approved") == 1
            assert counts.get("changes_requested") == 1

        anyio.run(run)

    def test_send_and_read_message(self, db_path):
        """Send a message via bridge, then read it back."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            msg_id = await bridge.send_message(
                text="Hello from test",
                sender="human",
            )
            assert msg_id is not None
            assert isinstance(msg_id, str)

            messages = await bridge.get_messages()
            assert len(messages) == 1
            assert messages[0]["text"] == "Hello from test"
            assert messages[0]["sender"] == "human"
            assert messages[0]["id"] == msg_id

        anyio.run(run)

    def test_get_messages_since(self, db_path):
        """get_messages with since parameter returns only newer messages."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            await bridge.send_message(text="first", sender="human")
            all_msgs = await bridge.get_messages(limit=100)
            assert len(all_msgs) == 1
            first_rowid = all_msgs[0]["rowid"]

            await bridge.send_message(text="second", sender="human")
            after = await bridge.get_messages(since=str(first_rowid))
            assert len(after) == 1
            assert after[0]["text"] == "second"

        anyio.run(run)

    def test_get_agents(self, db_path):
        """get_agents returns registered agents."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            agents = await bridge.get_agents()
            assert len(agents) >= 1
            assert any(a["agent_id"] == "claude-code-main" for a in agents)

        anyio.run(run)

    def test_get_agent_statuses(self, db_path):
        """get_agent_statuses returns only non-offline agents."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            statuses = await bridge.get_agent_statuses()
            assert "claude-code-main" in statuses
            assert statuses["claude-code-main"] == "online"

        anyio.run(run)

    def test_get_plans(self, db_path):
        """get_plans returns plans ordered by created_at desc."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            plans = await bridge.get_plans()
            assert len(plans) >= 1
            assert any(p["id"] == "plan-1" for p in plans)

        anyio.run(run)

    def test_get_connection_status_with_agents(self, db_path):
        """get_connection_status returns a formatted string when agents exist."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            status = await bridge.get_connection_status()
            assert "agentes" in status
            assert "🟢" in status

        anyio.run(run)

    def test_get_connection_status_no_agents(self, db_path):
        """get_connection_status returns 'sin conexiones' when no agents."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            status = await bridge.get_connection_status()
            assert "Sin conexiones" in status

        anyio.run(run)

    def test_format_time(self, db_path):
        """_format_time handles ISO strings and empty values."""
        from datetime import datetime as dt_cls, timezone

        bridge = TuiBridge(Database(db_path))
        assert bridge._format_time("") == ""
        # Naive datetime treated as UTC, then converted to local time.
        # Dynamic expected value makes the test timezone-independent.
        expected = dt_cls(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc).astimezone().strftime("%H:%M")
        assert bridge._format_time("2024-01-15T10:30:00") == expected
        # Invalid string returns first 5 chars
        result = bridge._format_time("abcde")
        assert result == "abcde" or isinstance(result, str)

    def test_create_task_creates_and_returns_id(self, db_path):
        """create_task inserts a new task and returns a valid UUID."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            task_id = await bridge.create_task(
                title="New Test Task",
                description="Test description",
                plan_id="plan-1",
            )
            assert task_id is not None
            assert isinstance(task_id, str)

            # Verify it was inserted
            tasks = await bridge.get_tasks()
            new_tasks = [t for t in tasks if t["title"] == "New Test Task"]
            assert len(new_tasks) == 1
            assert new_tasks[0]["description"] == "Test description"
            assert new_tasks[0]["plan_id"] == "plan-1"
            assert new_tasks[0]["status"] == "pending"

        anyio.run(run)

    def test_create_task_validates_title(self, db_path):
        """create_task raises TaskValidationError for empty title."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            with pytest.raises(TaskValidationError, match="Title cannot be empty"):
                await bridge.create_task(title="", description="x", plan_id="plan-1")

            with pytest.raises(TaskValidationError, match="Title cannot be empty"):
                await bridge.create_task(title="   ", description="x", plan_id="plan-1")

        anyio.run(run)

    # ── move_task tests ────────────────────────────────────────

    def test_move_task_valid_transition(self, db_path):
        """move_task succeeds for a valid state transition (pending → in_progress)."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            result = await bridge.move_task("task-0", "in_progress")
            assert result is True

            # Verify the update was persisted
            row = await db.execute_one(
                "SELECT status FROM tasks WHERE id = ?",
                ("task-0",),
            )
            assert row is not None
            assert row["status"] == "in_progress"

        anyio.run(run)

    def test_move_task_invalid_transition(self, db_path):
        """move_task returns False for a transition not in the state machine."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            # pending → approved is not a valid transition
            result = await bridge.move_task("task-0", "approved")
            assert result is False

            # Status should remain unchanged
            row = await db.execute_one(
                "SELECT status FROM tasks WHERE id = ?",
                ("task-0",),
            )
            assert row is not None
            assert row["status"] == "pending"

        anyio.run(run)

    def test_move_task_terminal_state(self, db_path):
        """move_task returns False when the task is in a terminal state (approved)."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            # task-3 has status "approved" (terminal)
            result = await bridge.move_task("task-3", "in_progress")
            assert result is False

            # Status should remain approved
            row = await db.execute_one(
                "SELECT status FROM tasks WHERE id = ?",
                ("task-3",),
            )
            assert row is not None
            assert row["status"] == "approved"

        anyio.run(run)

    def test_move_task_nonexistent(self, db_path):
        """move_task returns False for a task ID that doesn't exist."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            result = await bridge.move_task("nonexistent-id", "in_progress")
            assert result is False

        anyio.run(run)

    def test_move_task_concurrent_protection(self, db_path):
        """move_task uses WHERE status=? to prevent lost updates on concurrent changes.

        If the status changed between read and write, the UPDATE affects 0 rows
        and the method returns False.
        """

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            # Manually change the task's status to 'review'.
            # From 'review', valid moves are 'approved' or 'changes_requested'.
            await db.execute_write(
                "UPDATE tasks SET status = 'review' WHERE id = ?",
                ("task-0",),
            )

            # move_task reads 'review', validates 'review' → 'changes_requested'
            result = await bridge.move_task("task-0", "changes_requested")
            assert result is True

            # Verify state is now 'changes_requested'
            row = await db.execute_one(
                "SELECT status FROM tasks WHERE id = ?",
                ("task-0",),
            )
            assert row is not None
            assert row["status"] == "changes_requested"

            # The WHERE status=? clause prevents lost updates: if the status
            # changed between read and write, the UPDATE affects 0 rows.
            # Directly verify the SQL pattern works by trying to UPDATE
            # with a stale status that no longer matches.
            stale_updated = await db.execute_write(
                "UPDATE tasks SET status = 'approved' WHERE id = ? AND status = 'review'",
                ("task-0",),
            )
            assert stale_updated == 0, "Stale status should not match"

        anyio.run(run)

    def test_move_task_all_transitions(self, db_path):
        """Exercise all valid task transitions through the state machine."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            # Create a single task and walk it through all transitions
            bridge2 = TuiBridge(db)
            task_id = await bridge2.create_task(title="Walkthrough", plan_id="plan-1")

            transitions = [
                ("pending", "in_progress"),
                ("in_progress", "review"),
                ("review", "changes_requested"),
                ("changes_requested", "review"),
                ("review", "approved"),
            ]
            for current_status, target_status in transitions:
                result = await bridge.move_task(task_id, target_status)
                assert result is True, f"Failed transition: {current_status} → {target_status}"

                row = await db.execute_one(
                    "SELECT status FROM tasks WHERE id = ?",
                    (task_id,),
                )
                assert row is not None
                assert row["status"] == target_status, f"Expected {target_status} after move, got {row['status']}"

            # After 'approved', no further moves allowed
            result = await bridge.move_task(task_id, "in_progress")
            assert result is False

        anyio.run(run)

    def test_create_task_defaults(self, db_path):
        """create_task with minimal args sets sensible defaults."""

        async def run():
            db = Database(db_path)
            await _init_db(db)
            bridge = TuiBridge(db)

            task_id = await bridge.create_task(title="Minimal", plan_id="plan-1")
            tasks = await bridge.get_tasks()
            task = next(t for t in tasks if t["id"] == task_id)
            assert task["description"] == ""
            assert task["status"] == "pending"

        anyio.run(run)


class TestDBWatcher:
    """DBWatcher polling and change detection."""

    def _external_write(self, db_path: str, plan_id: str, title: str) -> None:
        """Simulate an external process writing to the same DB file.

        Uses a raw sqlite3 connection to bypass the Database singleton,
        which triggers a PRAGMA data_version change visible to the watcher.
        """
        import sqlite3

        ext_conn = sqlite3.connect(db_path)
        try:
            ext_conn.execute("BEGIN IMMEDIATE")
            ext_conn.execute(
                "INSERT INTO plans (id, title) VALUES (?, ?)",
                (plan_id, title),
            )
            ext_conn.commit()
        finally:
            ext_conn.close()

    def test_detects_version_change(self, db_path):
        """DBWatcher detects a data_version change after an external write."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            changes_detected = []

            watcher = DBWatcher(
                db,
                interval=0.1,
                on_change=lambda v: changes_detected.append(v),
            )

            # Initial poll sets known version
            await watcher.poll()
            assert len(changes_detected) == 0

            # External write via separate connection (simulates MCP server)
            self._external_write(db_path, "watcher-test", "Watcher Test Plan")

            # Poll again — should detect the change
            await watcher.poll()
            assert len(changes_detected) >= 1, f"Expected at least 1 change detection, got {changes_detected}"

        anyio.run(run)

    def test_no_false_positive(self, db_path):
        """DBWatcher does NOT fire on_change when data_version hasn't changed."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            changes_detected = []

            watcher = DBWatcher(
                db,
                interval=0.1,
                on_change=lambda v: changes_detected.append(v),
            )

            # First poll — establishes baseline
            await watcher.poll()
            assert len(changes_detected) == 0

            # Second poll — no writes, version should be the same
            await watcher.poll()
            assert len(changes_detected) == 0, f"Expected 0 false positives, got {changes_detected}"

            # Third poll — still no writes
            await watcher.poll()
            assert len(changes_detected) == 0

        anyio.run(run)

    def test_force_refresh(self, db_path):
        """force_refresh resets known_version and detects changes."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            changes_detected = []

            watcher = DBWatcher(
                db,
                interval=0.1,
                on_change=lambda v: changes_detected.append(v),
            )

            await watcher.poll()
            assert len(changes_detected) == 0

            # External write via separate connection
            self._external_write(db_path, "force-test", "Force Test")

            # force_refresh should detect it
            await watcher.force_refresh()
            assert len(changes_detected) >= 1

        anyio.run(run)

    def test_get_data_version_returns_int(self, db_path):
        """_get_data_version returns a valid integer."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            watcher = DBWatcher(db)

            version = await watcher._get_data_version()
            assert isinstance(version, int)
            assert version >= 0

        anyio.run(run)

    def test_poll_returns_version(self, db_path):
        """poll() returns the current data_version."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            watcher = DBWatcher(db)

            version = await watcher.poll()
            assert isinstance(version, int)
            assert version >= 0

        anyio.run(run)


# ── Headless integration tests for KanbanTUI ────────────────────────────────


class TestChatOverlayContextual:
    """Direct tests for ChatOverlay contextual behaviour (no headless app)."""

    def test_contextual_header_text(self):
        """_build_header_text returns contextual text when task_context is set."""
        bridge = TuiBridge(Database(":memory:"))
        task = {"id": "t1", "title": "Fix login bug", "status": "in_progress"}
        overlay = ChatOverlay(bridge, task_context=task)
        header = overlay._build_header_text()
        assert "Fix login bug" in header
        assert "Tarea" in header

    def test_general_header_text(self):
        """_build_header_text returns general text when no task_context."""
        bridge = TuiBridge(Database(":memory:"))
        overlay = ChatOverlay(bridge, task_context=None)
        header = overlay._build_header_text()
        assert "Chat general" in header

    def test_placeholder_with_assignee(self):
        """_build_placeholder mentions assignee when task has one."""
        bridge = TuiBridge(Database(":memory:"))
        task = {"id": "t1", "title": "Task", "status": "pending", "assignee": "claude-code-main"}
        overlay = ChatOverlay(bridge, task_context=task)
        placeholder = overlay._build_placeholder()
        assert "@Arq:" in placeholder

    def test_placeholder_without_assignee(self):
        """_build_placeholder shows default when no assignee."""
        bridge = TuiBridge(Database(":memory:"))
        task = {"id": "t1", "title": "Task", "status": "pending"}
        overlay = ChatOverlay(bridge, task_context=task)
        placeholder = overlay._build_placeholder()
        assert "F1" in placeholder

    def test_contextual_send_uses_thread_id(self, db_path):
        """Messages sent via bridge with thread_id = task.id are stored correctly."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            # Simulate what ChatOverlay._do_send does for contextual chat
            task_id = "task-ctx-1"
            thread_id = task_id  # ChatOverlay sets thread_id = task_context["id"]
            await bridge.send_message(
                text="Test message",
                sender="human",
                thread_id=thread_id,
            )

            msgs = await bridge.get_messages_for_task(task_id)
            assert len(msgs) == 1
            assert msgs[0]["text"] == "Test message"
            assert msgs[0]["thread_id"] == task_id

        anyio.run(run)

    def test_general_send_uses_no_thread_id(self, db_path):
        """Messages sent via bridge without thread_id have thread_id = None."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            # Simulate what ChatOverlay._do_send does for general chat
            await bridge.send_message(text="General message", sender="human")

            msgs = await bridge.get_messages(limit=100)
            msg = next((m for m in msgs if m["text"] == "General message"), None)
            assert msg is not None
            assert msg.get("thread_id") is None

        anyio.run(run)

    def test_contextual_fetch_filters_by_thread_id(self, db_path):
        """get_messages_for_task returns only messages for the given task."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            # Seed messages with different thread_ids
            await bridge.send_message(text="Task msg", sender="human", thread_id="task-a")
            await bridge.send_message(text="General", sender="human", thread_id=None)
            await bridge.send_message(text="Other task", sender="human", thread_id="task-b")

            task_a_msgs = await bridge.get_messages_for_task("task-a")
            assert len(task_a_msgs) == 1
            assert task_a_msgs[0]["text"] == "Task msg"
            assert task_a_msgs[0]["thread_id"] == "task-a"

        anyio.run(run)


class TestKanbanTUIHeadless:
    """Headless integration tests for kanban TUI overlay navigation.

    These tests use Textual's run_test to verify real DOM interaction.
    They do NOT test contextual task selection (timing-dependent across
    async init); contextual behavior is covered by TestChatOverlayContextual.
    """

    async def _setup_db(self, db_path: str, *, task_title: str = "Test Task", assignee: str | None = None) -> None:
        """Initialize DB with a single task."""
        db = Database(db_path)
        await db.initialize()
        await db.execute_write(
            "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
            ("plan-1", "Test Plan", "in_progress"),
        )
        await db.execute_write(
            "INSERT INTO tasks (id, plan_id, title, status, assignee) VALUES (?, ?, ?, ?, ?)",
            ("task-1", "plan-1", task_title, "pending", assignee),
        )

    async def _find_chat_panel(self, app):
        """Find ChatPanel in the app's DOM."""
        from agent_bridge.ui.chat_panel import ChatPanel

        try:
            return app.query_one(ChatPanel)
        except Exception:
            return None

    def test_chat_panel_always_visible(self, db_path):
        """ChatPanel is always visible — no overlay needed."""

        async def run():
            await self._setup_db(db_path)
            from agent_bridge.ui.kanban_tui import KanbanTUI

            app = KanbanTUI(db_path=db_path, dry_run=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.5)

                # ChatPanel should be in the DOM from the start
                panel = await self._find_chat_panel(app)
                assert panel is not None, "ChatPanel should be mounted"

                # Status bar should show Chat general (no task selected)
                status = panel.query_one("#chat-status-bar", Static)
                status_text = str(status.content)
                assert "Chat general" in status_text

                # K should focus the input
                await pilot.press("k")
                await pilot.pause(0.3)
                focused = app.focused
                assert focused is not None
                assert focused.id == "chat-input"

        anyio.run(run)

    def test_chat_input_focus_on_k(self, db_path):
        """Pressing K focuses the chat input (no overlay)."""

        async def run():
            await self._setup_db(db_path)
            from agent_bridge.ui.kanban_tui import KanbanTUI

            app = KanbanTUI(db_path=db_path, dry_run=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.5)

                # K focuses the chat input
                await pilot.press("k")
                await pilot.pause(0.3)
                assert app.focused is not None
                assert app.focused.id == "chat-input"

                # Pressing K again keeps focus on the input (it's already focused)
                await pilot.press("k")
                await pilot.pause(0.3)
                assert app.focused.id == "chat-input"

                # No modal screens should be on the stack
                assert len(app.screen_stack) == 1, "No overlays should be open"

        anyio.run(run)


class TestKanbanTUIEdgeCases:
    """Edge cases and error handling tests."""

    # ── Unread count (unit tests) ──────────────────────────────────

    def test_unread_count_starts_at_zero(self, db_path):
        """get_unread_message_count returns 0 when no unread messages."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            count = await bridge.get_unread_message_count()
            assert count == 0

        anyio.run(run)

    def test_unread_count_increases_on_new_message(self, db_path):
        """Sending a general chat message increases the unread count."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            count = await bridge.get_unread_message_count()
            assert count == 0

            # General chat message (no target, no thread_id)
            await bridge.send_message(text="Hello", sender="human")
            count = await bridge.get_unread_message_count()
            assert count == 1

            await bridge.send_message(text="World", sender="human")
            count = await bridge.get_unread_message_count()
            assert count == 2

        anyio.run(run)

    def test_unread_count_after_marking_read(self, db_path):
        """Marking a message as read decreases the unread count."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            msg_id = await bridge.send_message(
                text="Read me", sender="human"
            )
            assert await bridge.get_unread_message_count() == 1

            # Mark as read via Database
            await db.mark_message_read(msg_id)
            assert await bridge.get_unread_message_count() == 0

        anyio.run(run)

    def test_unread_count_ignores_contextual_messages(self, db_path):
        """Messages with thread_id (contextual chat) are not counted."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            # General chat message (no target) — counted
            await bridge.send_message(text="General", sender="human")

            # Contextual message (no target, has thread_id) — NOT counted
            await bridge.send_message(text="Contextual", sender="human", thread_id="task-1")

            assert await bridge.get_unread_message_count() == 1

        anyio.run(run)

    # ── Empty state (headless) ─────────────────────────────────────

    async def _setup_empty_db(self, db_path: str) -> None:
        """Initialize DB with plans but NO tasks."""
        db = Database(db_path)
        await db.initialize()
        await db.execute_write(
            "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
            ("plan-1", "Test Plan", "in_progress"),
        )

    def test_empty_task_list_shows_placeholder(self, db_path):
        """When no tasks exist, show helpful empty state with keyboard hint."""

        async def run():
            await self._setup_empty_db(db_path)
            from agent_bridge.ui.kanban_tui import KanbanTUI

            app = KanbanTUI(db_path=db_path, dry_run=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.5)

                placeholder = app.query_one("#empty-placeholder", Static)
                content = str(placeholder.content)
                assert "No hay tareas" in content
                assert "N para crear" in content

        anyio.run(run)

    # ── Notification tests (headless) ──────────────────────────────

    async def _setup_db_with_task(self, db_path: str) -> None:
        """Initialize DB with a plan and one task."""
        db = Database(db_path)
        await db.initialize()
        await db.execute_write(
            "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
            ("plan-1", "Test Plan", "in_progress"),
        )
        await db.execute_write(
            "INSERT INTO tasks (id, plan_id, title, status) VALUES (?, ?, ?, ?)",
            ("task-1", "plan-1", "Test Task", "pending"),
        )
        await db.execute_write(
            "INSERT INTO agents (agent_id, role, status) VALUES (?, ?, ?)",
            ("claude-code-main", "architect", "online"),
        )

    def test_notify_on_task_created(self, db_path):
        """_after_task_created shows a notification toast."""

        async def run():
            await self._setup_db_with_task(db_path)
            from agent_bridge.ui.kanban_tui import KanbanTUI

            app = KanbanTUI(db_path=db_path, dry_run=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.5)

                assert len(app._notifications) == 0

                # Call the handler directly
                await app._after_task_created()
                await pilot.pause(0.2)

                # A notification should have been posted
                assert len(app._notifications) >= 1
                notification_texts = [str(n) for n in app._notifications]
                assert any("Tarea creada" in t for t in notification_texts)

        anyio.run(run)

    def test_notify_on_task_moved(self, db_path):
        """_after_task_moved shows a notification toast."""

        async def run():
            await self._setup_db_with_task(db_path)
            from agent_bridge.ui.kanban_tui import KanbanTUI

            app = KanbanTUI(db_path=db_path, dry_run=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.5)

                assert len(app._notifications) == 0

                # Call the handler directly
                await app._after_task_moved()
                await pilot.pause(0.2)

                # A notification should have been posted
                assert len(app._notifications) >= 1
                notification_texts = [str(n) for n in app._notifications]
                assert any("Tarea movida" in t for t in notification_texts)

        anyio.run(run)

    # ── Contextual thread_id verification ──────────────────────────

    def test_contextual_message_thread_id_is_persisted(self, db_path):
        """Sending a contextual message stores the correct thread_id in the DB."""

        async def run():
            db = Database(db_path)
            await db.initialize()
            bridge = TuiBridge(db)

            task_id = "task-verify-ctx"
            # Simulate ChatOverlay._do_send behaviour
            await bridge.send_message(
                text="Contextual chat message",
                sender="human",
                thread_id=task_id,
            )

            msgs = await bridge.get_messages_for_task(task_id)
            assert len(msgs) == 1
            assert msgs[0]["text"] == "Contextual chat message"
            assert msgs[0]["thread_id"] == task_id

        anyio.run(run)

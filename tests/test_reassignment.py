"""Tests for stale agent detection and task reassignment."""
import json
import tempfile
from pathlib import Path

import anyio
import pytest

from agent_bridge.server import create_server, _reassign_stale_tasks


class TestTaskReassignment:
    """Tests for the stale agent reassignment logic."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    async def _call(self, server, tool: str, args: dict | None = None):
        """Helper: call an MCP tool and return the parsed JSON response."""
        from mcp.types import CallToolRequest

        req = CallToolRequest(
            method="tools/call",
            params={"name": tool, "arguments": args or {}},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    # ── Stale agent detection ─────────────────────────────────────

    def test_stale_agent_is_detected(self, db_path):
        """An agent with old last_seen and not offline should be stale."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-agent")
            await init()

            # Register agent with an old last_seen
            from agent_bridge.tools.agents import _heartbeat
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                """INSERT OR REPLACE INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now', '-10 minutes'))""",
                ("stale-agent", "developer", "online"),
            )

            # Should be detected as stale
            stale = await db.get_stale_agents(threshold_minutes=5)
            ids = [r["agent_id"] for r in stale]
            assert "stale-agent" in ids

        anyio.run(run)

    def test_active_agent_is_not_stale(self, db_path):
        """An agent with recent last_seen should NOT be stale."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                """INSERT INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now'))""",
                ("active-agent", "developer", "online"),
            )

            stale = await db.get_stale_agents(threshold_minutes=5)
            ids = [r["agent_id"] for r in stale]
            assert "active-agent" not in ids

        anyio.run(run)

    def test_offline_agent_is_not_stale(self, db_path):
        """An agent already marked offline should NOT be stale."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                """INSERT INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now', '-10 minutes'))""",
                ("offline-agent", "developer", "offline"),
            )

            stale = await db.get_stale_agents(threshold_minutes=5)
            ids = [r["agent_id"] for r in stale]
            assert "offline-agent" not in ids

        anyio.run(run)

    # ── Task reassignment ─────────────────────────────────────────

    def test_tasks_reassigned_for_stale_agent(self, db_path):
        """In-progress tasks for a stale agent should be reassigned to pending."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            # Register stale agent and an active one
            await db.execute(
                """INSERT INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now', '-10 minutes'))""",
                ("stale-dev", "developer", "online"),
            )

            # Create a plan and task assigned to the stale agent
            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES ('plan-1', 'Test', 'in_progress')"
            )
            await db.execute(
                """INSERT INTO tasks (id, plan_id, title, status, assignee)
                   VALUES ('task-1', 'plan-1', 'Feature X', 'in_progress', 'stale-dev')"""
            )

            # Run reassignment
            result = await _reassign_stale_tasks(db)
            assert "stale-dev" in result["stale_agents"]
            assert result["reassigned_count"] == 1

            # Verify task was reassigned
            task = await db.execute_one("SELECT status, assignee FROM tasks WHERE id = 'task-1'")
            assert task["status"] == "pending"
            assert task["assignee"] is None

            # Verify agent was marked offline
            agent = await db.execute_one(
                "SELECT status FROM agents WHERE agent_id = 'stale-dev'"
            )
            assert agent["status"] == "offline"

        anyio.run(run)

    def test_active_agent_tasks_not_reassigned(self, db_path):
        """Tasks for an active agent should NOT be reassigned."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            # Register active agent (recent last_seen)
            await db.execute(
                """INSERT INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now'))""",
                ("active-dev", "developer", "online"),
            )

            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES ('plan-2', 'Test', 'in_progress')"
            )
            await db.execute(
                """INSERT INTO tasks (id, plan_id, title, status, assignee)
                   VALUES ('task-2', 'plan-2', 'Feature Y', 'in_progress', 'active-dev')"""
            )

            # Run reassignment
            result = await _reassign_stale_tasks(db)
            assert "active-dev" not in result["stale_agents"]
            assert result["reassigned_count"] == 0

            # Verify task was NOT reassigned
            task = await db.execute_one("SELECT status FROM tasks WHERE id = 'task-2'")
            assert task["status"] == "in_progress"

        anyio.run(run)

    def test_reassign_no_stale_agents(self, db_path):
        """Reassignment with no stale agents returns empty result."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            result = await _reassign_stale_tasks(db)
            assert result["stale_agents"] == []
            assert result["reassigned_count"] == 0

        anyio.run(run)

    def test_reassign_only_in_progress_tasks(self, db_path):
        """Only in_progress tasks should be reassigned, not completed ones."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                """INSERT INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now', '-10 minutes'))""",
                ("stale-dev-2", "developer", "online"),
            )

            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES ('plan-3', 'Test', 'in_progress')"
            )
            # In-progress task — should be reassigned
            await db.execute(
                """INSERT INTO tasks (id, plan_id, title, status, assignee)
                   VALUES ('task-3', 'plan-3', 'WIP', 'in_progress', 'stale-dev-2')"""
            )
            # Approved task — should NOT be reassigned
            await db.execute(
                """INSERT INTO tasks (id, plan_id, title, status, assignee)
                   VALUES ('task-4', 'plan-3', 'Done', 'approved', 'stale-dev-2')"""
            )
            # Pending task — should NOT be reassigned (not in_progress)
            await db.execute(
                """INSERT INTO tasks (id, plan_id, title, status, assignee)
                   VALUES ('task-5', 'plan-3', 'Waiting', 'pending', 'stale-dev-2')"""
            )

            result = await _reassign_stale_tasks(db)
            assert result["reassigned_count"] == 1

            # Only task-3 should be pending now
            t3 = await db.execute_one("SELECT status FROM tasks WHERE id = 'task-3'")
            assert t3["status"] == "pending"

            # Others unchanged
            t4 = await db.execute_one("SELECT status FROM tasks WHERE id = 'task-4'")
            assert t4["status"] == "approved"
            t5 = await db.execute_one("SELECT status FROM tasks WHERE id = 'task-5'")
            assert t5["status"] == "pending"

        anyio.run(run)

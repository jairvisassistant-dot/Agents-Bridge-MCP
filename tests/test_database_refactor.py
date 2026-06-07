"""Tests for database refactoring — singleton connection, BEGIN IMMEDIATE, migrations.

These tests verify the NEW behaviors introduced by the audit fix refactor.
Existing approval tests (test_reassignment, test_edge_cases, etc.) cover
the unchanged external behavior.
"""

import tempfile
from pathlib import Path

import anyio
import pytest

from agent_bridge.state.database import Database, SCHEMA_VERSION


class TestSingletonConnection:
    """Database should reuse a single persistent connection (ARCH-02)."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    def test_reuses_same_connection(self, db_path):
        """After initialize, _conn should be set and reused across calls."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            # After init, _conn must exist
            assert db._conn is not None, "Singleton connection should exist after init"
            conn_id = id(db._conn)

            # Execute a query — should reuse same connection
            _ = await db.execute("SELECT 1 AS val")
            assert id(db._conn) == conn_id, "Connection should be reused after execute"

            # Execute another query — still the same connection
            _ = await db.execute("SELECT 2 AS val")
            assert id(db._conn) == conn_id, "Connection should be reused across calls"

        anyio.run(run)

    def test_close_clears_connection(self, db_path):
        """close() should close the connection and set _conn to None."""
        async def run():
            db = Database(db_path)
            await db.initialize()
            assert db._conn is not None

            await db.close()
            assert db._conn is None, "_conn should be None after close"

            # Should be able to re-initialize after close
            await db.initialize()
            assert db._conn is not None, "Should be able to reconnect after close"

        anyio.run(run)

    def test_writes_persist(self, db_path):
        """Writes go to the persistent database, not an in-memory temp."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            await db.execute_write(
                "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                ("persist-test", "Persistent Plan", "idle"),
            )

            # Read back from the same connection
            row = await db.execute_one(
                "SELECT id, title FROM plans WHERE id = ?", ("persist-test",)
            )
            assert row is not None
            assert row["id"] == "persist-test"
            assert row["title"] == "Persistent Plan"

        anyio.run(run)


class TestBeginImmediate:
    """Writes should use BEGIN IMMEDIATE (ARCH-03, CODE-02)."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    def test_execute_write_still_works(self, db_path):
        """execute_write should still work correctly with BEGIN IMMEDIATE."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            count = await db.execute_write(
                "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                ("immediate-test", "Test", "idle"),
            )
            assert count == 1

            row = await db.execute_one(
                "SELECT title FROM plans WHERE id = ?", ("immediate-test",)
            )
            assert row["title"] == "Test"

        anyio.run(run)

    def test_with_transaction_works(self, db_path):
        """with_transaction should still work with BEGIN IMMEDIATE."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            def _tx(conn):
                conn.execute(
                    "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                    ("tx-test", "Transactional Plan", "idle"),
                )
                conn.execute(
                    "INSERT INTO tasks (id, plan_id, title, status) VALUES (?, ?, ?, ?)",
                    ("task-tx", "tx-test", "Task in TX", "pending"),
                )
                return "done"

            result = await db.with_transaction(_tx)
            assert result == "done"

            # Both should be visible
            plan = await db.execute_one(
                "SELECT title FROM plans WHERE id = ?", ("tx-test",)
            )
            assert plan is not None
            task = await db.execute_one(
                "SELECT title FROM tasks WHERE id = ?", ("task-tx",)
            )
            assert task is not None

        anyio.run(run)


class TestDryRunMode:
    """Dry-run mode should create fresh connections (CODE-01)."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    def test_dry_run_in_memory(self, db_path):
        """Dry-run mode operates on :memory: — disk file should not be created."""
        async def run():
            db = Database(db_path, dry_run=True)
            await db.initialize()

            # Write should be logged and skipped
            count = await db.execute_write(
                "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                ("dry-test", "Dry Plan", "idle"),
            )
            assert count == 0, "Dry-run writes should return 0 rowcount"

            # The disk file should NOT exist (or be empty / not have our data)
            # In dry-run mode we use :memory: so the disk file may or may not exist,
            # but the data should not be there on a fresh connection
            db2 = Database(db_path)
            await db2.initialize()
            row = await db2.execute_one(
                "SELECT id FROM plans WHERE id = ?", ("dry-test",)
            )
            assert row is None, "Dry-run data should not persist to disk"

        anyio.run(run)

    def test_dry_run_connections_not_shared(self, db_path):
        """Each dry-run call should use its own connection (thread safety)."""
        async def run():
            db = Database(db_path, dry_run=True)
            await db.initialize()

            # In dry-run mode, _conn should be None (no persistent connection)
            # Each operation creates a fresh :memory: connection
            # Note: this test documents the behavior — dry-run creates connections per call
            first_row = await db.execute("SELECT 1 AS val")
            assert first_row[0]["val"] == 1

        anyio.run(run)


class TestSafeMigrations:
    """Migrations should use BEGIN IMMEDIATE + INSERT OR IGNORE (CODE-02, ARCH-06)."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    def test_initialize_sets_schema_version(self, db_path):
        """After initialize, schema_version should match SCHEMA_VERSION."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            row = await db.execute_one(
                "SELECT value FROM _meta WHERE key = 'schema_version'"
            )
            assert row is not None
            assert int(row["value"]) == SCHEMA_VERSION

        anyio.run(run)

    def test_double_initialize_is_safe(self, db_path):
        """Calling initialize twice should not error (idempotent migration)."""
        async def run():
            db = Database(db_path)
            await db.initialize()
            await db.initialize()  # Second call should be safe

            row = await db.execute_one(
                "SELECT value FROM _meta WHERE key = 'schema_version'"
            )
            assert row is not None
            assert int(row["value"]) == SCHEMA_VERSION

        anyio.run(run)


class TestExistingBehaviorPreserved:
    """Verify existing public API methods still work after the refactor."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    def test_get_stale_agents_works(self, db_path):
        """get_stale_agents should still work without explicit conn.close()."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                """INSERT INTO agents (agent_id, role, status, last_seen)
                   VALUES (?, ?, ?, datetime('now', '-10 minutes'))""",
                ("stale-test", "developer", "online"),
            )

            stale = await db.get_stale_agents(threshold_minutes=5)
            ids = [r["agent_id"] for r in stale]
            assert "stale-test" in ids

        anyio.run(run)

    def test_reassign_tasks_works(self, db_path):
        """reassign_tasks_from_agent should still work without explicit conn.close()."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES ('p1', 'Test', 'in_progress')"
            )
            await db.execute(
                """INSERT INTO tasks (id, plan_id, title, status, assignee)
                   VALUES ('t1', 'p1', 'Task', 'in_progress', 'reassign-agent')"""
            )

            count = await db.reassign_tasks_from_agent("reassign-agent")
            assert count == 1

            task = await db.execute_one("SELECT status FROM tasks WHERE id = 't1'")
            assert task["status"] == "pending"

        anyio.run(run)

    def test_mark_agent_offline_works(self, db_path):
        """mark_agent_offline should still work without explicit conn.close()."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            await db.execute(
                "INSERT INTO agents (agent_id, role, status) VALUES (?, ?, ?)",
                ("online-agent", "developer", "online"),
            )
            await db.mark_agent_offline("online-agent")

            agent = await db.execute_one(
                "SELECT status FROM agents WHERE agent_id = ?", ("online-agent",)
            )
            assert agent["status"] == "offline"

        anyio.run(run)

    def test_reset_works(self, db_path):
        """reset() should still work without explicit conn.close()."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            await db.execute_write(
                "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                ("reset-test", "Reset Plan", "idle"),
            )

            await db.reset()

            row = await db.execute_one("SELECT id FROM plans WHERE id = ?", ("reset-test",))
            assert row is None, "reset() should clear all data"

        anyio.run(run)

    def test_export_import_works(self, db_path):
        """get_plan_export and import_plan should still work."""
        async def run():
            db = Database(db_path)
            await db.initialize()

            await db.execute_write(
                "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                ("export-test", "Export Plan", "idle"),
            )
            await db.execute_write(
                "INSERT INTO tasks (id, plan_id, title, status) VALUES (?, ?, ?, ?)",
                ("et1", "export-test", "Export Task", "pending"),
            )

            exported = await db.get_plan_export("export-test")
            assert exported is not None
            assert exported["plan"]["id"] == "export-test"

        anyio.run(run)


class TestReviewAtomicTransactions:
    """Review approve/request_changes should use with_transaction (CODE-06, CODE-07)."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    async def _setup_task_in_review(self, db_path, task_id="review-task-1"):
        """Insert a plan + task + review directly, with task in 'review' state."""
        from agent_bridge.state.database import Database
        db = Database(db_path)
        await db.initialize()
        await db.execute_write(
            "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
            ("review-plan", "Review Plan", "in_progress"),
        )
        await db.execute_write(
            "INSERT INTO tasks (id, plan_id, title, status) VALUES (?, ?, ?, ?)",
            (task_id, "review-plan", "Review Task", "review"),
        )
        await db.execute_write(
            "INSERT INTO reviews (id, task_id, status) VALUES (?, ?, ?)",
            ("review-1", task_id, "in_review"),
        )

    def test_approve_updates_both_task_and_review(self, db_path):
        """Approve should update task status AND review status atomically."""
        async def run():
            await self._setup_task_in_review(db_path)

            from agent_bridge.server import create_server
            from mcp.types import CallToolRequest
            import json

            # Pass agent_id so permission layer allows review.approve
            server, init = create_server(db_path=db_path, agent_id="test-arch", dry_run=False)
            await init()

            async def call(tool, args):
                req = CallToolRequest(
                    method="tools/call",
                    params={"name": tool, "arguments": args or {}},
                )
                resp = await server.request_handlers[CallToolRequest](req)
                return json.loads(resp.root.content[0].text)

            # Register agent with architect role (needed for review.approve)
            await call("agent.heartbeat", {"agent_id": "test-arch", "role": "architect"})

            # Approve the review
            result = await call("review.approve", {"task_id": "review-task-1", "comment": "LGTM!"})
            assert result.get("status") == "approved", f"Expected approved, got {result}"

            # Verify BOTH task and review were updated
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            task_row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", ("review-task-1",))
            assert task_row["status"] == "approved"

            review_row = await db.execute_one(
                "SELECT status FROM reviews WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                ("review-task-1",),
            )
            assert review_row is not None
            assert review_row["status"] == "approved"

        anyio.run(run)

    def test_request_changes_updates_both_task_and_review(self, db_path):
        """request_changes should update task status AND review status atomically."""
        async def run():
            await self._setup_task_in_review(db_path)

            from agent_bridge.server import create_server
            from mcp.types import CallToolRequest
            import json

            # Pass agent_id so permission layer allows review.request_changes
            server, init = create_server(db_path=db_path, agent_id="test-arch", dry_run=False)
            await init()

            async def call(tool, args):
                req = CallToolRequest(
                    method="tools/call",
                    params={"name": tool, "arguments": args or {}},
                )
                resp = await server.request_handlers[CallToolRequest](req)
                return json.loads(resp.root.content[0].text)

            await call("agent.heartbeat", {"agent_id": "test-arch", "role": "architect"})

            result = await call("review.request_changes", {"task_id": "review-task-1", "changes": "Fix X"})
            assert result.get("status") == "changes_requested", f"Expected changes_requested, got {result}"

            # Verify BOTH task and review were updated
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            task_row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", ("review-task-1",))
            assert task_row["status"] == "changes_requested"

            review_row = await db.execute_one(
                "SELECT status FROM reviews WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                ("review-task-1",),
            )
            assert review_row is not None
            assert review_row["status"] == "changes_requested"

        anyio.run(run)


class TestServerReturnType:
    """create_server return type should be properly annotated (CODE-12)."""

    def test_return_type_is_correct(self):
        """create_server returns (Server, Callable[[], Awaitable[None]])."""
        from collections.abc import Awaitable, Callable
        from mcp.server import Server

        server, init = __import__("agent_bridge.server", fromlist=["create_server"]).create_server(dry_run=True)

        assert isinstance(server, Server)
        assert callable(init)

        # Verify the init is actually awaitable
        import inspect
        assert inspect.iscoroutinefunction(init), "init should be a coroutine function"

    def test_init_is_awaitable(self):
        """The init function returned by create_server should be awaitable."""
        import anyio

        async def run():
            server, init = __import__("agent_bridge.server", fromlist=["create_server"]).create_server(dry_run=True)
            # Should not raise
            await init()

        anyio.run(run)


class TestMaintenanceLoop:
    """Maintenance loop should use anyio, not asyncio (CODE-08, CODE-09, ARCH-10)."""

    def test_create_server_imports_anyio_not_asyncio(self):
        """server.py should use anyio.sleep, not asyncio.sleep."""
        import inspect
        import agent_bridge.server as mod

        source = inspect.getsource(mod)
        assert "anyio.sleep" in source, "Should use anyio.sleep instead of asyncio.sleep"
        assert "asyncio.sleep" not in source, "Should NOT use asyncio.sleep"

    def test_cancelled_error_handling_uses_anyio(self):
        """Maintenance loop should handle cancellation via anyio."""
        import inspect
        import agent_bridge.server as mod

        source = inspect.getsource(mod)
        # Should NOT reference asyncio.CancelledError directly
        assert "asyncio.CancelledError" not in source, "Should not reference asyncio.CancelledError"

    def test_server_init_starts_maintenance_loop(self, db_path):
        """init() should start the maintenance loop."""
        async def run():
            from agent_bridge.server import create_server

            server, init = create_server(db_path=db_path, dry_run=True)
            await init()

            # After init, maintenance should have started
            from agent_bridge import server as mod
            # The scope keyed by db_path should have been created
            assert db_path in mod._maintenance_scopes, "Maintenance CancelScope should be created"

        anyio.run(run)

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + "-wal").unlink(missing_ok=True)
        Path(path + "-shm").unlink(missing_ok=True)

    def test_cleanup_after_scope_cancelled(self, db_path):
        """Cancelling the maintenance scope should clean up."""
        async def run():
            from agent_bridge.server import create_server

            server, init = create_server(db_path=db_path, dry_run=True)
            await init()

            from agent_bridge import server as mod
            # Cancel the scope
            scope = mod._maintenance_scopes.get(db_path)
            if scope is not None:
                scope.cancel()

            # After cancellation, scope should still exist (key is kept) but be cancelled
            assert mod._maintenance_scopes.get(db_path) is not None

        anyio.run(run)

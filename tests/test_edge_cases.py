"""Edge case tests — concurrent claims, reviews, and invalid operations.

These tests use the full MCP server handler (same pattern as test_permissions.py)
to verify that SQLite's atomic UPDATE prevents race conditions.
"""

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import anyio
import pytest

from agent_bridge.server import create_server


class TestEdgeCases:
    """Edge case tests using the full MCP server handler."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    async def _call(self, server, tool: str, args: dict | None = None):
        from mcp.types import CallToolRequest

        req = CallToolRequest(
            method="tools/call",
            params={"name": tool, "arguments": args or {}},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    def _setup_plan_with_task(self, db_path, plan_status: str = "tasks_ready") -> tuple:
        """Helper: create a plan + a pending task directly in the DB.
        Returns (plan_id, task_id).
        """
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()
            plan_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO plans (id, title, description, status) VALUES (?, ?, ?, ?)",
                (plan_id, "Edge Test Plan", "", plan_status),
            )
            await db.execute(
                "INSERT INTO tasks (id, plan_id, title, description, status) VALUES (?, ?, ?, ?, 'pending')",
                (task_id, plan_id, "Edge Test Task", ""),
            )
            return plan_id, task_id

        return anyio.run(run)

    async def _make_dev_server(self, db_path, agent_id: str):
        """Create and initialize a server for a developer agent."""
        server, init = create_server(db_path=db_path, agent_id=agent_id)
        await init()
        await self._call(server, "agent.heartbeat", {
            "agent_id": agent_id, "role": "developer",
        })
        return server

    # ── Concurrent claim ───────────────────────────────────────

    def test_concurrent_claim_only_one_succeeds(self, db_path):
        """Two agents claim the same task concurrently — only one should win."""
        _pid, task_id = self._setup_plan_with_task(db_path)

        async def run():
            dev1 = await self._make_dev_server(db_path, "dev-1")
            dev2 = await self._make_dev_server(db_path, "dev-2")

            results = await asyncio.gather(
                self._call(dev1, "task.claim",
                           {"task_id": task_id, "agent": "dev-1"}),
                self._call(dev2, "task.claim",
                           {"task_id": task_id, "agent": "dev-2"}),
            )

            successes = [r for r in results if r.get("status") == "in_progress"]
            failures = [r for r in results if r.get("error") is not None]

            assert len(successes) == 1, (
                f"Expected exactly 1 successful claim, got {len(successes)}: {results}"
            )
            assert len(failures) == 1, (
                f"Expected exactly 1 failed claim, got {len(failures)}: {results}"
            )

        anyio.run(run)

    def test_claim_already_claimed_fails(self, db_path):
        """A task already in in_progress cannot be claimed again."""
        _pid, task_id = self._setup_plan_with_task(db_path)

        async def run():
            dev = await self._make_dev_server(db_path, "dev-1")

            # First claim succeeds
            first = await self._call(dev, "task.claim",
                                     {"task_id": task_id, "agent": "dev-1"})
            assert first.get("status") == "in_progress"

            # Second claim must fail
            second = await self._call(dev, "task.claim",
                                      {"task_id": task_id, "agent": "dev-2"})
            assert "error" in second, f"Expected error, got {second}"

        anyio.run(run)

    # ── Concurrent review ──────────────────────────────────────

    def test_concurrent_review_and_changes(self, db_path):
        """review.approve and review.request_changes at the same time — only one wins."""
        _pid, task_id = self._setup_plan_with_task(db_path)

        async def run():
            dev = await self._make_dev_server(db_path, "dev-1")
            arch_server, arch_init = create_server(
                db_path=db_path, agent_id="test-arch",
            )
            await arch_init()
            await self._call(arch_server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            # Claim + submit work so task is in 'review' state
            await self._call(dev, "task.claim",
                             {"task_id": task_id, "agent": "dev-1"})
            await self._call(dev, "task.submit_work", {
                "task_id": task_id,
                "summary": "Done",
                "diff": "changes",
            })

            # Fire approve and request_changes concurrently from the architect
            results = await asyncio.gather(
                self._call(arch_server, "review.approve",
                           {"task_id": task_id, "comment": "LGTM!"}),
                self._call(arch_server, "review.request_changes",
                           {"task_id": task_id, "changes": "Fix X"}),
            )

            # Exactly one should have changed the task state
            approved = [r for r in results if r.get("status") == "approved"]
            changes_req = [r for r in results if r.get("status") == "changes_requested"]

            total_changed = len(approved) + len(changes_req)
            assert total_changed == 1, (
                f"Expected exactly 1 state change, got {total_changed}: {results}"
            )

            # The losing operation should return an error
            errors = [r for r in results if r.get("error") is not None]
            assert len(errors) == 1, (
                f"Expected exactly 1 error, got {len(errors)}: {results}"
            )

        anyio.run(run)

    # ── Submit already submitted ────────────────────────────────

    def test_submit_work_already_submitted(self, db_path):
        """A task already in review cannot be submitted again."""
        _pid, task_id = self._setup_plan_with_task(db_path)

        async def run():
            dev = await self._make_dev_server(db_path, "dev-1")

            # Claim + first submit
            await self._call(dev, "task.claim",
                             {"task_id": task_id, "agent": "dev-1"})
            first = await self._call(dev, "task.submit_work", {
                "task_id": task_id,
                "summary": "First submission",
                "diff": "v1",
            })
            assert first.get("status") == "review"

            # Second submit must fail
            second = await self._call(dev, "task.submit_work", {
                "task_id": task_id,
                "summary": "Second submission",
                "diff": "v2",
            })
            assert "error" in second, f"Expected error, got {second}"

        anyio.run(run)

    # ── Claim nonexistent task ──────────────────────────────────

    def test_claim_nonexistent_task(self, db_path):
        """Claiming a non-existent task returns an error."""
        async def run():
            dev = await self._make_dev_server(db_path, "dev-1")

            result = await self._call(
                dev, "task.claim",
                {"task_id": "nonexistent-task-id", "agent": "dev-1"},
            )
            assert "error" in result, f"Expected error, got {result}"

        anyio.run(run)

    # ── Task create in completed/archived plan ─────────────────────

    def test_create_task_in_completed_plan(self, db_path):
        """Creating a task in a completed plan should fail."""
        async def run():
            arch_server, arch_init = create_server(db_path=db_path, agent_id="test-arch")
            await arch_init()
            await self._call(arch_server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await self._call(arch_server, "plan.create", {"title": "Completed Plan"})
            pid = plan["plan_id"]

            # Walk to completed
            await self._call(arch_server, "plan.update", {"plan_id": pid, "status": "tasks_ready"})
            await self._call(arch_server, "plan.update", {"plan_id": pid, "status": "in_progress"})
            await self._call(arch_server, "plan.update", {"plan_id": pid, "status": "completed"})

            # Try to create a task
            r = await self._call(arch_server, "task.create", {"plan_id": pid, "title": "Late Task"})
            assert "error" in r, f"Expected error, got {r}"

        anyio.run(run)

    def test_create_task_in_archived_plan(self, db_path):
        """Creating a task in an archived plan should fail."""
        async def run():
            arch_server, arch_init = create_server(db_path=db_path, agent_id="test-arch")
            await arch_init()
            await self._call(arch_server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await self._call(arch_server, "plan.create", {"title": "Archived Plan"})
            pid = plan["plan_id"]

            # Transition to a status that can be archived, then archive
            await self._call(arch_server, "plan.update", {"plan_id": pid, "status": "tasks_ready"})
            await self._call(arch_server, "plan.archive", {"plan_id": pid})

            # Try to create a task
            r = await self._call(arch_server, "task.create", {"plan_id": pid, "title": "Late Task"})
            assert "error" in r, f"Expected error, got {r}"

        anyio.run(run)

    # ── Review enforcement tests ──────────────────────────────────

    def test_review_approve_invalid_state(self, db_path):
        """Approving a task that is NOT in 'review' should fail."""
        _pid, task_id = self._setup_plan_with_task(db_path)

        async def run():
            arch_server, arch_init = create_server(db_path=db_path, agent_id="test-arch")
            await arch_init()
            await self._call(arch_server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            # Task is 'pending' — approve should fail via state machine
            r = await self._call(arch_server, "review.approve", {
                "task_id": task_id, "comment": "LGTM!",
            })
            assert "error" in r, f"Expected error, got {r}"

        anyio.run(run)

    def test_review_request_changes_invalid_state(self, db_path):
        """Requesting changes on an approved task should fail."""
        _pid, task_id = self._setup_plan_with_task(db_path)

        async def run():
            dev = await self._make_dev_server(db_path, "dev-1")
            arch_server, arch_init = create_server(db_path=db_path, agent_id="test-arch")
            await arch_init()
            await self._call(arch_server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            # Walk task to review → approved
            await self._call(dev, "task.claim", {"task_id": task_id, "agent": "dev-1"})
            await self._call(dev, "task.submit_work", {
                "task_id": task_id, "summary": "Done", "diff": "v1",
            })
            await self._call(arch_server, "review.approve", {
                "task_id": task_id, "comment": "LGTM!",
            })

            # Task is 'approved' — request_changes should fail
            r = await self._call(arch_server, "review.request_changes", {
                "task_id": task_id, "changes": "Fix it",
            })
            assert "error" in r, f"Expected error, got {r}"

        anyio.run(run)

    # ── Import validation tests ───────────────────────────────────

    def test_plan_import_invalid_status(self, db_path):
        """Importing a plan with an invalid status should raise."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            import pytest
            with pytest.raises(ValueError, match="Invalid plan status"):
                await db.import_plan({
                    "plan": {"id": "bad-plan", "title": "Bad", "status": "invalid_status"},
                    "tasks": [],
                    "reviews": [],
                })

        anyio.run(run)

    def test_plan_import_valid_data(self, db_path):
        """Importing a plan with valid statuses should succeed."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            result = await db.import_plan({
                "plan": {"id": "good-plan", "title": "Good", "status": "planning"},
                "tasks": [
                    {"id": "task-1", "title": "Task 1", "status": "pending"},
                ],
                "reviews": [
                    {"id": "rev-1", "task_id": "task-1", "status": "pending"},
                ],
            })
            assert result["plan_id"] == "good-plan"
            assert result["tasks_count"] == 1

        anyio.run(run)

    # ── Cascade delete with messages ──────────────────────────────

    def test_plan_delete_cascade_messages(self, db_path):
        """Deleting a plan should remove associated messages too."""
        async def run():
            from agent_bridge.state.database import Database
            db = Database(db_path)
            await db.initialize()

            # Insert plan + task + contextual message directly
            plan_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES (?, ?, ?)",
                (plan_id, "Cascade Msg", "idle"),
            )
            await db.execute(
                "INSERT INTO tasks (id, plan_id, title, status) VALUES (?, ?, ?, ?)",
                (task_id, plan_id, "Task", "pending"),
            )
            await db.execute(
                "INSERT INTO messages (id, thread_id, sender, text) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), task_id, "arquitecto", "Cascade test msg"),
            )

            # Verify message exists
            remaining = await db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE thread_id = ?", (task_id,),
            )
            assert remaining[0]["cnt"] == 1, "Message should exist before delete"

            # Delete the plan via handler
            from agent_bridge.tools.planner import _delete_plan
            r = await _delete_plan(db, {"plan_id": plan_id})
            result = json.loads(r[0].text)
            assert result["deleted"] is True

            # Messages should be gone after cascade
            remaining = await db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE thread_id = ?", (task_id,),
            )
            assert remaining[0]["cnt"] == 0, "Messages should be cascaded on plan delete"

        anyio.run(run)

    # ── Chat.read since_rowid ─────────────────────────────────────

    def test_chat_read_since_rowid(self, db_path):
        """chat.read with since_rowid should filter by rowid correctly."""
        async def run():
            arch_server, arch_init = create_server(db_path=db_path, agent_id="test-arch")
            await arch_init()
            await self._call(arch_server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            # Send a few messages
            ids = []
            for i in range(3):
                r = await self._call(arch_server, "chat.send", {
                    "text": f"Message {i}",
                    "sender": "arquitecto",
                })
                ids.append(r["message_id"])

            # Read with since_rowid=1 (skip first message's rowid)
            msgs = await self._call(arch_server, "chat.read", {"since_rowid": 1})
            assert len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}"
            # The first returned message should be Message 1 (not Message 0)
            assert msgs[0]["text"] == "Message 1", f"Expected 'Message 1', got {msgs[0]['text']}"

        anyio.run(run)

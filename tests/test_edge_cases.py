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

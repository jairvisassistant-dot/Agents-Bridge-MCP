"""Stress tests — concurrent claims under load.

Verifies that SQLite's atomic UPDATE with WHERE condition correctly
serialises concurrent claim operations even under high contention.
"""

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import anyio
import pytest

from agent_bridge.server import create_server


class TestStress:
    """Stress test for the lock system under concurrent load."""

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

    async def _make_dev_server(self, db_path, agent_id: str):
        """Create and initialize a server for a developer agent."""
        server, init = create_server(db_path=db_path, agent_id=agent_id)
        await init()
        await self._call(server, "agent.heartbeat", {
            "agent_id": agent_id, "role": "developer",
        })
        return server

    def test_10_concurrent_claims(self, db_path):
        """10 agents try to claim 5 tasks simultaneously.

        Verifies:
        - Each task is claimed exactly once
        - No task is double-claimed
        - Exactly 5 claims succeed, 5 are rejected
        """
        async def run():
            from agent_bridge.state.database import Database

            # Seed DB with 5 tasks
            db = Database(db_path)
            await db.initialize()
            task_ids = []
            for i in range(5):
                tid = str(uuid.uuid4())
                task_ids.append(tid)
                pid = str(uuid.uuid4())
                await db.execute(
                    "INSERT INTO plans (id, title, description, status) VALUES (?, ?, ?, 'tasks_ready')",
                    (pid, f"Stress Plan {i}", ""),
                )
                await db.execute(
                    "INSERT INTO tasks (id, plan_id, title, description, status) VALUES (?, ?, ?, ?, 'pending')",
                    (tid, pid, f"Task {i}", ""),
                )

            # Create 10 developer agent servers (each agent gets its own server)
            servers = []
            for i in range(10):
                srv = await self._make_dev_server(db_path, f"agent-{i}")
                servers.append(srv)

            # 10 agents claim these 5 tasks concurrently
            claim_calls = []
            for i, srv in enumerate(servers):
                target_task = task_ids[i % 5]  # cycle through 5 tasks
                claim_calls.append(
                    self._call(srv, "task.claim", {
                        "task_id": target_task,
                        "agent": f"agent-{i}",
                    })
                )

            results = await asyncio.gather(*claim_calls)

            # Analyse results
            success_by_task: dict[str, list[str]] = {tid: [] for tid in task_ids}
            for r in results:
                if r.get("status") == "in_progress":
                    tid = r.get("task_id")
                    success_by_task[tid].append(r.get("assignee", "unknown"))

            # Each task must be claimed exactly once
            for tid, claimers in success_by_task.items():
                assert len(claimers) == 1, (
                    f"Task {tid} claimed {len(claimers)} times: {claimers}"
                )

            # Total successes must equal number of tasks
            total_successes = sum(len(v) for v in success_by_task.values())
            assert total_successes == 5, (
                f"Expected 5 successful claims, got {total_successes}"
            )

            # Total failures must be 5 (10 attempts - 5 successes)
            total_failures = sum(
                1 for r in results if r.get("error") is not None
            )
            assert total_failures == 5, (
                f"Expected 5 failed claims, got {total_failures}"
            )

            # Verify no task was claimed by two agents (double-check)
            all_claimers = []
            for tid, claimers in success_by_task.items():
                all_claimers.extend(claimers)
            assert len(all_claimers) == len(set(all_claimers)), (
                f"Duplicate claimers detected: {all_claimers}"
            )

        anyio.run(run, backend="asyncio")

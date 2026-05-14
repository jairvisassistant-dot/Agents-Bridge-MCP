"""Tests for permission layer — agent identity enforcement and tool access control."""

import json
import tempfile
from pathlib import Path

import anyio
import pytest

from agent_bridge.server import create_server


class TestPermissionLayer:
    """Integration tests using the full MCP server handler."""

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

    def test_public_tools_work_without_heartbeat(self, db_path):
        async def run():
            from mcp.types import CallToolRequest
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            req = CallToolRequest(method="tools/call", params={"name": "hello", "arguments": {}})
            resp = await server.request_handlers[CallToolRequest](req)
            assert "alive" in resp.root.content[0].text
        anyio.run(run)

    def test_agent_heartbeat_registers_role(self, db_path):
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            result = await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            assert result["role"] == "architect"
        anyio.run(run)

    def test_architect_can_create_plan(self, db_path):
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            result = await self._call(server, "plan.create", {"title": "Test"})
            assert "plan_id" in result
        anyio.run(run)

    def test_developer_cannot_approve_review(self, db_path):
        async def run():
            dev_server, init = create_server(db_path=db_path, agent_id="test-dev")
            await init()
            await self._call(dev_server, "agent.heartbeat", {
                "agent_id": "test-dev", "role": "developer",
            })
            result = await self._call(dev_server, "review.approve", {"task_id": "fake"})
            assert result["error"] == "permission_denied"
        anyio.run(run)

    def test_anonymous_cannot_create_plan(self, db_path):
        async def run():
            anon_server, init = create_server(db_path=db_path, agent_id=None)
            await init()
            result = await self._call(anon_server, "plan.create", {"title": "fail"})
            assert result["error"] == "agent_not_identified"
        anyio.run(run)

    def test_agent_whoami_returns_allowed_tools(self, db_path):
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            result = await self._call(server, "agent.whoami", {"agent_id": "test-arch"})
            assert "plan.create" in result["allowed_tools"]
        anyio.run(run)

    def test_agent_list_includes_registered_agents(self, db_path):
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            result = await self._call(server, "agent.list")
            assert any(a["agent_id"] == "test-arch" for a in result)
        anyio.run(run)

    # ── Bug 1: archtect permission for discussion tools ────────────

    def test_architect_can_call_thread_get_pending(self, db_path):
        """Architect role is allowed to call chat.thread_get_pending."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            # Must not return permission_denied
            result = await self._call(server, "chat.thread_get_pending", {
                "agent_name": "arquitecto",
            })
            assert isinstance(result, list)  # empty list = success, no permission error

        anyio.run(run)

    def test_architect_can_call_thread_resolve(self, db_path):
        """Architect role is allowed to call chat.thread_resolve."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            # Create a thread first, then resolve it
            thread = await self._call(server, "chat.thread_create", {
                "title": "Architect resolve",
                "participants": ["arquitecto", "desarrollador"],
            })
            result = await self._call(server, "chat.thread_resolve", {
                "thread_id": thread["thread_id"],
            })
            assert "error" not in result
            assert result["status"] == "resolved"

        anyio.run(run)

    def test_default_role_can_call_discussion_tools(self, db_path):
        """Default role (no heartbeat) can call discussion tools."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-default")
            await init()
            # No heartbeat — default role

            # thread_get_pending works
            result = await self._call(server, "chat.thread_get_pending", {
                "agent_name": "arquitecto",
            })
            assert isinstance(result, list)

        anyio.run(run)

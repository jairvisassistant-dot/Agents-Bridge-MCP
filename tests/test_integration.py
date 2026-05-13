"""Integration tests — full MCP stdio request/response cycle.

These tests spawn the actual MCP server and communicate via stdio
JSON-RPC messages, simulating how Claude Code and OpenCode interact.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Path to the agent-bridge CLI
BRIDGE_CLI = [sys.executable, "-m", "agent_bridge"]


def _send_request(proc, request: dict) -> dict | None:
    """Send a JSON-RPC request to stdin and read one response from stdout."""
    line = json.dumps(request) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()

    # Read response line
    response_line = proc.stdout.readline()
    if not response_line:
        return None
    return json.loads(response_line)


class TestStdioIntegration:
    """Full MCP integration via stdio transport."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    def test_initialize_and_list_tools(self, db_path):
        """MCP handshake: initialize → tools/list returns all tools."""
        env = {"AGENT_BRIDGE_ID": "test-agent"}
        proc = subprocess.Popen(
            [*BRIDGE_CLI, "--db-path", db_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**__import__("os").environ, **env},
        )

        try:
            # Initialize
            resp = _send_request(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1.0"},
                },
            })
            assert resp is not None
            assert resp["id"] == 1
            assert "serverInfo" in resp["result"]

            # tools/list
            resp = _send_request(proc, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/list",
                "params": {},
            })
            assert resp is not None
            tools = resp["result"]["tools"]
            tool_names = [t["name"] for t in tools]
            assert "hello" in tool_names
            assert "plan.create" in tool_names
            assert "task.claim" in tool_names
            assert "review.approve" in tool_names
            assert "chat.send" in tool_names
            assert "agent.heartbeat" in tool_names
            assert "skill.list" in tool_names
            assert "task.get_diff" in tool_names
        finally:
            proc.terminate()
            proc.wait()

    def test_plan_create_and_list(self, db_path):
        """Full workflow: plan.create → plan.list."""
        env = {"AGENT_BRIDGE_ID": "test-architect"}
        proc = subprocess.Popen(
            [*BRIDGE_CLI, "--db-path", db_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**__import__("os").environ, **env},
        )

        try:
            # Initialize
            _send_request(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1.0"},
                },
            })

            # Heartbeat (public tool, sets role)
            resp = _send_request(proc, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "agent.heartbeat",
                    "arguments": {"agent_id": "test-architect", "role": "architect"},
                },
            })
            assert resp["result"]["content"][0]["text"] is not None

            # plan.create
            resp = _send_request(proc, {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {
                    "name": "plan.create",
                    "arguments": {"title": "Integration Test Plan"},
                },
            })
            result = json.loads(resp["result"]["content"][0]["text"])
            assert "plan_id" in result
            plan_id = result["plan_id"]

            # plan.list
            resp = _send_request(proc, {
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "plan.list", "arguments": {}},
            })
            plans = json.loads(resp["result"]["content"][0]["text"])
            assert any(p["id"] == plan_id for p in plans)

        finally:
            proc.terminate()
            proc.wait()

    def test_full_workflow_via_stdio(self, db_path):
        """Complete cycle: plan → task → claim → submit → review → approve.

        Uses two subprocesses (architect + developer) to verify the full
        cross-process workflow. Each process identifies via AGENT_BRIDGE_ID.
        """
        import time

        env_arch = {**__import__("os").environ, "AGENT_BRIDGE_ID": "arch-1"}
        env_dev = {**__import__("os").environ, "AGENT_BRIDGE_ID": "dev-1"}

        arch_proc = subprocess.Popen(
            [*BRIDGE_CLI, "--db-path", db_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env_arch,
        )
        dev_proc = subprocess.Popen(
            [*BRIDGE_CLI, "--db-path", db_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env_dev,
        )

        def init(proc):
            _send_request(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1.0"},
                },
            })

        def call(proc, n, a, msg_id=2):
            resp = _send_request(proc, {
                "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                "params": {"name": n, "arguments": a},
            })
            if resp is None:
                return {"error": "no_response"}
            if "result" in resp and "content" in resp["result"]:
                try:
                    text = resp["result"]["content"][0]["text"]
                    return json.loads(text)
                except (json.JSONDecodeError, KeyError):
                    return {"error": "parse_failed", "raw": text[:200]}
            if "error" in resp:
                return {"error": resp["error"]["message"]}
            return resp

        try:
            init(arch_proc)
            init(dev_proc)

            # Register both agents
            arch = call(arch_proc, "agent.heartbeat",
                       {"agent_id": "arch-1", "role": "architect"}, 2)
            assert arch.get("role") == "architect", f"arch heartbeat: {arch}"

            dev = call(dev_proc, "agent.heartbeat",
                      {"agent_id": "dev-1", "role": "developer"}, 2)
            assert dev.get("role") == "developer", f"dev heartbeat: {dev}"

            # Arch creates plan + task
            plan = call(arch_proc, "plan.create", {"title": "Full Test"}, 3)
            assert "plan_id" in plan, f"plan.create: {plan}"

            task = call(arch_proc, "task.create",
                       {"plan_id": plan["plan_id"], "title": "Feature X"}, 4)
            assert "task_id" in task, f"task.create: {task}"

            # Dev claims and submits (needs lock — wait briefly for release)
            time.sleep(0.2)  # let arch process release any locks

            claimed = call(dev_proc, "task.claim",
                          {"task_id": task["task_id"]}, 3)
            assert claimed.get("status") == "in_progress", f"claim: {claimed}"

            submit = call(dev_proc, "task.submit_work", {
                "task_id": task["task_id"],
                "summary": "Implemented Feature X",
                "diff": "diff --git a/feature.py b/feature.py\n+def feature():\n+    return 42",
            }, 4)
            assert submit.get("status") == "review", f"submit: {submit}"

            # Arch reviews and approves
            diff = call(arch_proc, "task.get_diff",
                       {"task_id": task["task_id"]}, 5)
            assert "feature" in str(diff.get("diff", "")), f"get_diff: {diff}"

            approve = call(arch_proc, "review.approve",
                          {"task_id": task["task_id"], "comment": "LGTM!"}, 6)
            assert approve.get("status") == "approved", f"approve: {approve}"

        finally:
            for p in (arch_proc, dev_proc):
                p.terminate()
                p.wait()

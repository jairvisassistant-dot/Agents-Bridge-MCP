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


class TestSSEIntegration:
    """Integration tests via SSE transport (HTTP)."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    def test_sse_initialize_and_list_tools(self, db_path):
        """SSE handshake: connect → initialize → tools/list via async SSE."""
        import time

        import anyio

        # Write stderr to a file so the subprocess never blocks on pipe buffer
        err_path = db_path + ".sse.err"
        proc = subprocess.Popen(
            [*BRIDGE_CLI, "start", "--headless", "--db-path", db_path, "--port", "9877"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=open(err_path, "w"),
        )

        try:
            time.sleep(3)
            if proc.poll() is not None:
                with open(err_path) as f:
                    err = f.read()
                pytest.fail(f"SSE server exited early. stderr:\n{err[:1000]}")

            # Debug: verify process is running before test
            with open(err_path) as f:
                startup_log = f.read()
            assert proc.poll() is None, f"Process died after 3s. Log:\n{startup_log[:500]}"

            anyio.run(self._sse_run_test, db_path, err_path)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            # Clean up stderr log
            try:
                Path(err_path).unlink(missing_ok=True)
            except OSError:
                pass

    async def _sse_run_test(self, db_path, err_path=None):
        """Async SSE test: connect → initialize → tools/list."""
        import anyio
        import httpx

        url = "http://127.0.0.1:9877"
        session_id: str | None = None
        responses: dict[int, dict] = {}

        # Wait for server to be live — use streaming to avoid blocking
        # on the infinite SSE stream.
        async with httpx.AsyncClient(timeout=5) as c:
            for _ in range(30):
                try:
                    async with c.stream("GET", f"{url}/sse") as sse:
                        # If we got here without exception, server is alive
                        # and returned 200. We don't need to read anything yet.
                        break
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
                    await anyio.sleep(0.3)
            else:
                if err_path:
                    try:
                        with open(err_path) as f:
                            err = f.read()
                        pytest.fail(f"SSE server did not start. stderr:\n{err[:500]}")
                    except OSError:
                        pass
                pytest.fail("SSE server did not start in time")

        # SSE event reader — runs as a background task
        async def read_sse():
            nonlocal session_id
            async with httpx.AsyncClient(timeout=30) as c:
                async with c.stream("GET", f"{url}/sse") as sse:
                    async for line in sse.aiter_lines():
                        # SSE format: event + data lines.
                        # The session_id arrives as:
                        #   event: endpoint
                        #   data: /messages/?session_id=<id>
                        if line.startswith("data: ") and "session_id" in line:
                            # Extract session_id from path: /messages/?session_id=<id>
                            data_val = line[6:]
                            if "session_id=" in data_val:
                                session_id = data_val.split("session_id=")[1].split("&")[0]
                        elif line.startswith("data: "):
                            try:
                                msg = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            if "id" in msg:
                                responses[msg["id"]] = msg

        # Run SSE reader in background, POST in foreground
        async with anyio.create_task_group() as tg:
            tg.start_soon(read_sse)

            # Wait for session_id
            for _ in range(50):
                if session_id:
                    break
                await anyio.sleep(0.1)
            assert session_id is not None, "No session_id received"

            # POST initialize
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.post(
                    f"{url}/messages/?session_id={session_id}",
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {
                              "protocolVersion": "2024-11-05",
                              "capabilities": {},
                              "clientInfo": {"name": "test", "version": "0.1.0"},
                          }},
                )
                assert resp.status_code == 202

                # POST tools/list
                resp = await c.post(
                    f"{url}/messages/?session_id={session_id}",
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                assert resp.status_code == 202

            # Wait for tools/list response
            for _ in range(100):
                if 2 in responses:
                    break
                await anyio.sleep(0.1)

            # Cancel background reader
            tg.cancel_scope.cancel()

        assert 2 in responses, f"No tools/list response. Got IDs: {list(responses.keys())}"
        tools = responses[2]["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "hello" in tool_names
        assert "plan.create" in tool_names
        assert "chat.send" in tool_names
        assert "agent.heartbeat" in tool_names
        assert "agent.shutdown_request" in tool_names

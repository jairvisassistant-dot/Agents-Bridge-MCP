"""Chat TUI — Textual-based terminal UI for Agent Bridge.

Connects to the MCP server via stdio subprocess, sends JSON-RPC
requests, and displays messages and agent status with auto-refresh.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Any

from rich.markup import escape as rich_escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Input, RichLog, Static

logger = logging.getLogger(__name__)


class MCPClient:
    """Async stdio client to an MCP server subprocess.

    Wraps JSON-RPC request/response over stdin/stdout so the TUI can
    call chat.read, chat.send, and agent.list via the bridge server.

    Features automatic reconnection with exponential backoff:
    1s → 2s → 4s → 8s → 16s → 30s (max), then retries at 30s intervals.
    """

    MAX_BACKOFF = 30  # seconds

    def __init__(
        self,
        db_path: str = "bridge.db",
        on_reconnecting=None,
        on_reconnected=None,
    ) -> None:
        self.db_path = db_path
        self._process: asyncio.subprocess.Process | None = None
        self._msg_id = 1
        self._initialized = False
        self._lock = asyncio.Lock()  # one request in flight at a time
        self._on_reconnecting = on_reconnecting  # async callable(n_attempt)
        self._on_reconnected = on_reconnected    # async callable()

    async def connect(self) -> None:
        """Spawn the MCP server and perform the initialize handshake."""
        env = {**os.environ, "AGENT_BRIDGE_ID": "human-ui"}
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "agent_bridge",
            "--db-path",
            self.db_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        resp = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-bridge-ui", "version": "0.1.0"},
        })
        if resp is None or "result" not in resp:
            raise ConnectionError(
                f"MCP initialize failed: {resp}"
            )
        self._initialized = True

    async def close(self) -> None:
        """Terminate the subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

    async def _ensure_connected(self) -> bool:
        """Check connection and reconnect with exponential backoff if needed.

        Returns True if connected, False if reconnection failed.
        """
        if self._initialized and self._process and self._process.returncode is None:
            return True

        self._initialized = False
        attempt = 0
        backoff = 1.0

        while backoff <= self.MAX_BACKOFF:
            attempt += 1
            if self._on_reconnecting:
                await self._on_reconnecting(attempt)
            try:
                await self.close()
                await self.connect()
                if self._on_reconnected:
                    await self._on_reconnected()
                return True
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.MAX_BACKOFF)

        # Connection permanently lost after exhausting backoff
        return False

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call an MCP tool and return the parsed result content."""
        async with self._lock:
            return await self._call_tool_unsafe(name, arguments)

    async def _call_tool_unsafe(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Inner call_tool — must only be called while holding self._lock."""
        connected = await self._ensure_connected()
        if not connected:
            return None

        resp = await self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        if resp is None:
            return None
        if "result" in resp:
            content = resp["result"].get("content", [])
            if content:
                try:
                    return json.loads(content[0]["text"])
                except (json.JSONDecodeError, KeyError, IndexError):
                    return content[0].get("text", "")
            return None
        if "error" in resp:
            return {"error": resp["error"].get("message", "unknown")}
        return resp

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and read one response."""
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            self._initialized = False
            raise ConnectionError("Not connected")

        request = {
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params,
        }
        self._msg_id += 1

        try:
            data = json.dumps(request) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()

            response_bytes = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30
            )
            if not response_bytes:
                self._initialized = False
                return None
            return json.loads(response_bytes.decode("utf-8"))
        except (BrokenPipeError, OSError, asyncio.TimeoutError):
            self._initialized = False
            return None


class ChatTUI(App):
    """Agent Bridge Chat — Textual terminal UI.

    Layout:
      ┌──────────────────────────────────────────────────┐
      │  Agent Bridge Chat  [Agents: status indicators]  │
      ├──────────────────────────────────────────────────┤
      │  messages (chronological, RichLog)               │
      │                                                  │
      ├──────────────────────────────────────────────────┤
      │ > [Input]                                  [Send] │
      └──────────────────────────────────────────────────┘
    """

    CSS = """
    Screen {
        layout: vertical;
    }

    #status-bar {
        height: 1;
        background: $panel;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }

    #chat-log {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }

    #input-row {
        height: 3;
        dock: bottom;
        padding: 0 1;
    }

    Input {
        width: 1fr;
    }

    Button {
        width: 12;
        margin-left: 1;
    }

    .warning {
        color: $warning;
    }

    .timestamp {
        color: $text-disabled;
    }

    .mention {
        color: $accent;
        text-style: bold;
    }
    """

    BINDINGS = [Binding("ctrl+l", "clear_log", "Limpiar pantalla")]

    agent_status: reactive[dict[str, str]] = reactive({})

    def __init__(self, db_path: str = "bridge.db") -> None:
        super().__init__()
        self.db_path = db_path
        self._client = MCPClient(
            db_path,
            on_reconnecting=self._on_reconnecting,
            on_reconnected=self._on_reconnected,
        )
        self._known_id: str | None = None  # last message id seen

    def compose(self) -> ComposeResult:
        yield Static(id="status-bar")
        yield RichLog(id="chat-log", highlight=True, markup=True)
        with Horizontal(id="input-row"):
            yield Input(id="msg-input", placeholder="Escribí tu mensaje…")
            yield Button("Enviar", id="send-btn", variant="primary")

    async def on_mount(self) -> None:
        """Connect to MCP server and start polling."""
        try:
            await self._client.connect()
            log = self.query_one("#chat-log", RichLog)
            log.write("[green]✓ Conectado al Agent Bridge[/]")
        except Exception as exc:
            self._write_status("AGENT BRIDGE — ERROR DE CONEXIÓN")
            log = self.query_one("#chat-log", RichLog)
            log.write(f"[red]Error al conectar: {exc}[/]")
            return

        self._write_status("AGENT BRIDGE CHAT — Conectando…")
        # Start periodic refresh
        self.set_interval(5, self._poll)

    def _write_status(self, text: str) -> None:
        self.query_one("#status-bar", Static).update(text)

    async def _on_reconnecting(self, attempt: int) -> None:
        """Called by MCPClient when reconnection is in progress."""
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[red]⚠ Reconectando... (intento {attempt})[/]")

    async def _on_reconnected(self) -> None:
        """Called by MCPClient after successful reconnection."""
        log = self.query_one("#chat-log", RichLog)
        log.write("[green]✓ Reconectado[/]")

    def watch_agent_status(self, status: dict[str, str]) -> None:
        """Reactively update the status bar when agent status changes."""
        parts = []
        indicator = {"online": "🟢", "busy": "🟡", "away": "🟠", "offline": "⚫"}
        for agent_id, agent_status in sorted(status.items()):
            icon = indicator.get(agent_status, "⚫")
            short = agent_id.replace("claude-code-", "Arq").replace("opencode-", "Dev")
            parts.append(f"{icon} {short}")
        if parts:
            self._write_status(f"AGENT BRIDGE CHAT  |  Agentes: {' · '.join(parts)}")
        else:
            self._write_status("AGENT BRIDGE CHAT  |  Agentes: ⚫ (sin conexiones)")

    async def _poll(self) -> None:
        """Poll for new messages and agent status every 5 seconds."""
        try:
            await self._fetch_messages()
            await self._fetch_agents()
        except Exception as exc:
            logger.warning("Poll error: %s", exc)

    async def _fetch_messages(self) -> None:
        """Fetch new messages since the last known rowid."""
        params: dict[str, Any] = {}
        if self._known_id:
            params["since"] = self._known_id
        result = await self._client.call_tool("chat.read", params)
        if result is None:
            return
        if isinstance(result, list):
            messages = result
        elif isinstance(result, dict) and "error" in result:
            return
        else:
            messages = result if isinstance(result, list) else []

        log = self.query_one("#chat-log", RichLog)
        for msg in messages:
            if isinstance(msg, dict):
                # Use rowid for since filter (UUID strings don't sort chronologically)
                self._known_id = msg.get("rowid", msg.get("id", self._known_id))
                ts = self._format_time(msg.get("created_at", ""))
                sender = rich_escape(msg.get("sender", "?"))
                text = rich_escape(msg.get("text", ""))
                target = msg.get("target")

                line = f"[dim]{ts}[/dim] [bold]{sender}:[/bold]"
                if target:
                    line += f" [bold class=mention]@{rich_escape(target)}[/]"
                line += f" {text}"
                log.write(line)

    async def _fetch_agents(self) -> None:
        """Fetch registered agents and their statuses."""
        result = await self._client.call_tool("agent.list")
        if not isinstance(result, list):
            return
        new_status: dict[str, str] = {}
        for agent in result:
            if isinstance(agent, dict):
                agent_id = agent.get("agent_id", "")
                status = agent.get("status", "offline")
                new_status[agent_id] = status
        self.agent_status = new_status

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Send button press."""
        if event.button.id == "send-btn":
            await self._do_send()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input field."""
        if event.input.id == "msg-input":
            await self._do_send()

    def action_clear_log(self) -> None:
        """Clear the visible chat log without affecting the database."""
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write("[dim]— pantalla limpiada —[/dim]")

    async def _do_send(self) -> None:
        """Send the current input as a chat message, or handle /commands."""
        inp = self.query_one("#msg-input", Input)
        text = inp.value.strip()
        if not text:
            return

        if text == "/clear":
            inp.value = ""
            self.action_clear_log()
            return

        inp.value = ""
        result = await self._client.call_tool("chat.send", {"text": text, "sender": "human"})
        if result is None:
            log = self.query_one("#chat-log", RichLog)
            log.write("[red]Error: sin respuesta del servidor[/]")
        elif isinstance(result, dict) and "warning" in result:
            log = self.query_one("#chat-log", RichLog)
            log.write(f"[bold class=warning]⚠ {result['warning']}[/]")

    @staticmethod
    def _format_time(iso_str: str) -> str:
        """Format ISO timestamp to HH:MM in local time."""
        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone()  # UTC → local timezone
            return dt.strftime("%H:%M")
        except (ValueError, TypeError):
            return iso_str[:5] if len(iso_str) >= 5 else iso_str


def main(db_path: str = "bridge.db") -> None:
    """Launch the chat TUI."""
    app = ChatTUI(db_path=db_path)
    app.run()


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "bridge.db"
    main(db_path)

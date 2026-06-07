"""ChatOverlay — modal chat screen for the Kanban TUI.

Opens as a ModalScreen overlay with `K` from the kanban view.
Can be contextual (tied to a specific task) or general (all messages).

Contextual mode:
  - Header shows task title and status
  - Messages are filtered by thread_id = task.id
  - New messages get thread_id = task.id
  - Placeholder mentions @asignado when the task has an assignee

General mode:
  - Shows all messages (no thread_id filter)
  - Default placeholder with @mentions help
"""

from __future__ import annotations

import logging
import re

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Button, Input, RichLog, Static

from agent_bridge.ui.tui_bridge import TuiBridge

logger = logging.getLogger(__name__)

# ── Autocomplete ───────────────────────────────────────────────────────────────

_MENTIONS = ["@arquitecto", "@desarrollador", "@humano", "@all"]
_COMMANDS = ["/clear", "/help"]

_HELP_ROWS = [
    ("Mención", "@arquitecto", "Enviar mensaje al Arquitecto"),
    ("Mención", "@desarrollador", "Enviar mensaje al Desarrollador"),
    ("Mención", "@humano", "Enviar mensaje al humano"),
    ("Mención", "@all", "Enviar mensaje a todos"),
    ("Comando", "/clear", "Limpiar la pantalla (no borra la DB)"),
    ("Comando", "/help", "Mostrar esta tabla de ayuda"),
    ("Atajo", "Ctrl+L", "Limpiar la pantalla"),
    ("Atajo", "F1", "Mostrar / ocultar panel de ayuda rápida"),
    ("Atajo", "Tab / →", "Aceptar autocompletado"),
]


class AgentSuggester(Suggester):
    """Complete @mentions and /commands based on the last token in the input.

    Works mid-sentence: typing "hola @arq" suggests "hola @arquitecto".
    """

    async def get_suggestion(self, value: str) -> str | None:
        parts = value.rsplit(" ", 1)
        last = parts[-1]
        if not last.startswith(("@", "/")):
            return None
        prefix = parts[0] + " " if len(parts) > 1 else ""
        for candidate in _MENTIONS + _COMMANDS:
            if candidate.startswith(last) and candidate != last:
                return prefix + candidate
        return None


class ChatOverlay(ModalScreen[None]):
    """Modal overlay for chat messaging.

    Opens with `K` from the main kanban view.
    Has its own input, send button, message log, and commands.
    Translucent background shows the kanban underneath.

    When task_context is provided, chat is scoped to that task:
    messages are filtered by thread_id = task.id and the header
    shows the task title and status.
    """

    CSS = """
    ChatOverlay {
        align: center middle;
    }

    #chat-container {
        width: 80%;
        height: 80%;
        background: $panel;
        border: thick $accent;
        padding: 0 1;
    }

    #chat-header {
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $accent;
        color: $text;
    }

    #chat-log {
        height: 1fr;
        border: solid $primary;
        margin: 1 0;
        padding: 0 1;
    }

    #help-panel {
        height: auto;
        max-height: 14;
        border: solid $accent;
        padding: 0 1;
        display: none;
    }

    #help-panel.visible {
        display: block;
    }

    #input-row {
        height: 3;
        dock: bottom;
        padding: 0 0 1 0;
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

    BINDINGS = [
        Binding("escape", "dismiss", "Cerrar"),
        Binding("ctrl+l", "clear_log", "Limpiar pantalla"),
        Binding("f1", "toggle_help", "Ayuda"),
    ]

    agent_status: reactive[dict[str, str]] = reactive({})

    def __init__(self, bridge: TuiBridge, task_context: dict | None = None) -> None:
        """Initialise the chat overlay.

        Args:
            bridge: TuiBridge for DB operations.
            task_context: Optional task dict. When set, chat is scoped
                to that task (thread_id = task.id).
        """
        super().__init__()
        self._bridge = bridge
        # Store the context safely — guard against any Textual attr interference
        self._ctx: dict | None = task_context
        self._known_id: str | None = None  # last message rowid seen (general chat)
        self._rendered_ids: set[int] = set()  # rendered rowids (contextual chat)

    def compose(self) -> ComposeResult:
        """Build the chat overlay layout."""
        header_text = self._build_header_text()
        placeholder = self._build_placeholder()

        with Container(id="chat-container"):
            yield Static(header_text, id="chat-header")
            yield RichLog(id="chat-log", highlight=True, markup=True)
            yield Static(self._build_help_text(), id="help-panel", markup=True)
            with Horizontal(id="input-row"):
                yield Input(
                    id="msg-input",
                    placeholder=placeholder,
                    suggester=AgentSuggester(use_cache=False),
                )
                yield Button("Enviar", id="send-btn", variant="primary")

    @property
    def _task_context(self) -> dict | None:
        """Return the task context dict, or None."""
        ctx = getattr(self, "_ctx", None)
        if isinstance(ctx, dict):
            return ctx
        return None

    def _build_header_text(self) -> str:
        """Return the initial header text based on task context."""
        ctx = self._task_context
        if ctx is not None:
            title = rich_escape(ctx.get("title", "?"))
            status = ctx.get("status", "?")
            return f"💬 Tarea: {title}  |  Estado: {status}"
        return "💬 Chat general — Agent Bridge"

    def _build_placeholder(self) -> str:
        """Return the input placeholder based on task context."""
        ctx = self._task_context
        if ctx is not None and ctx.get("assignee"):
            # Pre-suggest @asignado when the task has an assignee
            assignee = ctx["assignee"]
            short = assignee.replace("claude-code-", "@Arq:").replace("opencode-", "@Dev:")
            return f"Escribí tu mensaje… (@arquitecto, {short}, /help)"
        return "Escribí tu mensaje… (@arquitecto, /help, F1)"

    async def on_mount(self) -> None:
        """Start polling messages when the overlay opens."""
        log = self.query_one("#chat-log", RichLog)
        log.write("[green]✓ Chat conectado (in-process)[/]")
        self.set_interval(5, self._poll)

    async def _poll(self) -> None:
        """Poll for new messages and agent status every 5 seconds."""
        try:
            await self._fetch_messages()
            await self._fetch_agents()
        except Exception as exc:
            logger.warning("ChatOverlay poll error: %s", exc)

    async def _fetch_messages(self) -> None:
        """Fetch messages and render them in the log.

        Contextual mode: fetches messages for the task via
        ``get_messages_for_task``, tracks rendered rowids to avoid
        duplicates.

        General mode: fetches messages since the last known rowid
        (incremental polling).
        """
        try:
            ctx = self._task_context
            if ctx is not None:
                messages = await self._bridge.get_messages_for_task(ctx["id"])
            elif self._known_id:
                messages = await self._bridge.get_messages(since=str(self._known_id))
            else:
                messages = await self._bridge.get_messages(limit=100)
        except Exception as exc:
            logger.warning("Failed to fetch messages: %s", exc)
            return

        log = self.query_one("#chat-log", RichLog)
        for msg in messages:
            rowid = msg.get("rowid")
            if rowid is not None:
                if rowid in self._rendered_ids:
                    continue
                self._rendered_ids.add(rowid)
                if self._task_context is None:
                    self._known_id = str(rowid)
            try:
                ts = self._bridge._format_time(msg.get("created_at", ""))
                sender = rich_escape(msg.get("sender", "?"))
                text = rich_escape(msg.get("text", ""))
                target = msg.get("target")

                line = f"[dim]{ts}[/dim] [bold]{sender}:[/bold]"
                if target:
                    line += f" [bold cyan]@{rich_escape(target)}[/bold cyan]"
                line += f" {text}"
                log.write(line)
            except Exception as exc:
                logger.warning("Failed to render message rowid=%s: %s", rowid, exc)

    async def _fetch_agents(self) -> None:
        """Fetch registered agents and their statuses."""
        try:
            agents = await self._bridge.get_agents()
        except Exception:
            return
        new_status: dict[str, str] = {}
        for agent in agents:
            agent_id = agent.get("agent_id", "")
            status = agent.get("status", "offline")
            new_status[agent_id] = status
        self.agent_status = new_status

    def watch_agent_status(self, status: dict[str, str]) -> None:
        """Reactively update the header when agent status changes.

        Preserves the contextual task prefix when task_context is set.
        """
        prefix = self._build_header_text()
        parts = []
        indicator = {"online": "🟢", "busy": "🟡", "away": "🟠", "offline": "⚫"}
        for agent_id, agent_status in sorted(status.items()):
            icon = indicator.get(agent_status, "⚫")
            short = agent_id.replace("claude-code-", "Arq").replace("opencode-", "Dev")
            parts.append(f"{icon} {short}")
        header = self.query_one("#chat-header", Static)
        if parts:
            header.update(f"{prefix}  |  {' · '.join(parts)}")
        else:
            header.update(f"{prefix}  |  ⚫ (sin conexiones)")

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

    def action_toggle_help(self) -> None:
        """Show or hide the quick-reference help panel."""
        panel = self.query_one("#help-panel", Static)
        if "visible" in panel.classes:
            panel.remove_class("visible")
        else:
            panel.add_class("visible")

    def action_dismiss(self) -> None:
        """Dismiss the overlay and return to the kanban view."""
        self.dismiss()

    @staticmethod
    def _build_help_text() -> str:
        """Build the quick-reference table as Rich markup."""
        lines = [
            "[bold]Referencia rápida[/bold]  [dim](F1 para cerrar)[/dim]",
            "",
            f"  [bold cyan]{'Tipo':<10}{'Token / Atajo':<18}Descripción[/bold cyan]",
            f"  [dim]{'─' * 10}{'─' * 18}{'─' * 32}[/dim]",
        ]
        type_color = {"Mención": "green", "Comando": "yellow", "Atajo": "blue"}
        for kind, token, desc in _HELP_ROWS:
            color = type_color.get(kind, "white")
            lines.append(f"  [{color}]{kind:<10}[/{color}][bold]{token:<18}[/bold]{desc}")
        return "\n".join(lines)

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

        if text == "/help":
            inp.value = ""
            self.action_toggle_help()
            return

        inp.value = ""
        # Extract first @mention from text to set the routing target
        mention = re.search(r"@(\w+)", text)
        target: str | None = None
        if mention:
            target = mention.group(1)

        try:
            ctx = self._task_context
            thread_id = ctx["id"] if ctx is not None else None
            await self._bridge.send_message(
                text=text,
                sender="human",
                target=target,
                thread_id=thread_id,
            )
        except Exception as exc:
            log = self.query_one("#chat-log", RichLog)
            log.write(f"[red]Error al enviar: {exc}[/]")
            return

        # Refresh immediately so the sent message appears without waiting for the next poll
        await self._fetch_messages()

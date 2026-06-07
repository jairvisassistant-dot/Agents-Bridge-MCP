"""ChatPanel — persistent chat widget for the Kanban TUI.

Unifies chat_tui.py (status bar, agent indicators, @mentions, /commands,
F1 help) with chat_overlay.py (contextual task awareness) into a single
Widget that lives at the bottom of the kanban layout.

Uses TuiBridge (direct DB) — no MCP subprocess.
"""

from __future__ import annotations

import logging
import re

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.suggester import Suggester
from textual.widgets import Button, Input, RichLog, Static
from textual.widget import Widget

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


# ── ChatPanel widget ────────────────────────────────────────────────────────────


class ChatPanel(Widget):
    """Persistent chat panel for the Kanban TUI.

    Lives at the bottom of the kanban layout — always visible, always
    ready. Shows agent connection status, a scrollable message log,
    and an input bar with @mention autocomplete.

    **General mode** (no task selected):
        Shows all messages with incremental polling by rowid.

    **Contextual mode** (task selected):
        Filters messages by ``thread_id = task.id`` so the human can
        discuss a specific task with the assigned agent.

    Switching between modes is automatic — just select a different task
    in the kanban board and the chat follows.

    Atajos:
        ``Ctrl+L`` — limpiar pantalla (no borra la DB)
        ``F1`` — mostrar / ocultar ayuda rápida
    """

    # ── Reactives ──────────────────────────────────────────────────

    task_context: reactive[dict | None] = reactive(None, init=False)
    """When set to a task dict, chat switches to contextual mode for that task.
    
    Set this from the kanban app whenever the selected task changes::
    
        chat_panel.task_context = selected_task  # or None for general chat
    
    The panel automatically clears its message cache and refetches.
    """

    agent_status: reactive[dict[str, str]] = reactive({}, init=False)
    """Mapping of agent_id → status, updated every poll cycle."""

    # ── Bindings (active when the chat panel or its children are focused) ──

    BINDINGS = [
        Binding("ctrl+l", "clear_log", "Limpiar", show=False),
        Binding("f1", "toggle_help", "Ayuda", show=False),
    ]

    # ── CSS ─────────────────────────────────────────────────────────

    DEFAULT_CSS = """
    ChatPanel {
        height: 12;
        border: solid $primary;
        margin: 0 1;
    }

    #chat-status-bar {
        height: 1;
        background: $surface;
        content-align: center middle;
        text-style: bold;
    }

    #chat-help-panel {
        height: auto;
        max-height: 14;
        border: solid $accent;
        padding: 0 1;
        display: none;
    }

    #chat-help-panel.visible {
        display: block;
    }

    #chat-log {
        height: 1fr;
        padding: 0 1;
        border: none;
    }

    #chat-input-row {
        height: 3;
        dock: bottom;
        padding: 0 1 1 1;
    }

    #chat-input {
        width: 1fr;
    }

    #chat-send-btn {
        width: 12;
        margin-left: 1;
    }
    """

    # ── Init ────────────────────────────────────────────────────────

    def __init__(self, bridge: TuiBridge) -> None:
        super().__init__()
        self._bridge = bridge

        # General-mode state: last rendered message rowid (incremental)
        self._known_id: str | None = None

        # Contextual-mode state: set of rendered rowids for the current task
        self._rendered_ids: set[int] = set()

    # ── Compose ─────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static(id="chat-status-bar")
        yield Static(self._build_help_text(), id="chat-help-panel")
        yield RichLog(id="chat-log", highlight=True, markup=True)
        with Horizontal(id="chat-input-row"):
            yield Input(
                id="chat-input",
                placeholder=self._build_placeholder(),
                suggester=AgentSuggester(use_cache=False),
            )
            yield Button("Enviar", id="chat-send-btn", variant="primary")

    # ── Lifecycle ───────────────────────────────────────────────────

    async def on_mount(self) -> None:
        """Start polling for messages and agent status."""
        # Initial status bar render (watchers have init=False)
        self._update_status_bar()
        # Start polling
        self.set_interval(5, self._poll)

    # ── Reactive watchers ───────────────────────────────────────────

    def watch_task_context(self, ctx: dict | None) -> None:
        """Switch between contextual and general mode when the task changes.

        Resets internal message tracking so the next poll fetches the
        correct set of messages without duplicates.
        """
        # Clear all tracking state
        self._known_id = None
        self._rendered_ids.clear()

        # Clear the log visually
        try:
            log = self.query_one("#chat-log", RichLog)
            log.clear()
        except Exception:
            pass

        # Update the input placeholder
        try:
            inp = self.query_one("#chat-input", Input)
            inp.placeholder = self._build_placeholder()
        except Exception:
            pass

        # Immediate fetch so the user sees messages without waiting 5s
        self.call_later(self._fetch_messages)

    def watch_agent_status(self, status: dict[str, str]) -> None:
        """Reactively update the status bar when agent status changes."""
        self._update_status_bar()

    # ── Status bar ──────────────────────────────────────────────────

    def _update_status_bar(self) -> None:
        """Rebuild the status bar text from current agent status + mode."""
        try:
            ctx = self.task_context
            # Mode prefix
            if ctx is not None:
                title = rich_escape(ctx.get("title", "?"))
                mode = f"💬 Tarea: [bold]{title}[/bold]"
            else:
                mode = "💬 Chat general"

            # Agent indicators
            parts: list[str] = []
            indicator = {"online": "🟢", "busy": "🟡", "away": "🟠", "offline": "⚫"}
            for agent_id, agent_st in sorted(self.agent_status.items()):
                icon = indicator.get(agent_st, "⚫")
                short = (
                    agent_id.replace("claude-code-", "Arq")
                    .replace("opencode-", "Dev")
                )
                parts.append(f"{icon} {short}")

            if parts:
                text = f"{mode}  |  {' · '.join(parts)}"
            else:
                text = f"{mode}  |  ⚫ (sin conexiones)"

            self.query_one("#chat-status-bar", Static).update(text)
        except Exception as exc:
            logger.warning("Failed to update status bar: %s", exc)

    def _build_placeholder(self) -> str:
        """Return the input placeholder based on current context."""
        ctx = self.task_context
        if ctx is not None and ctx.get("assignee"):
            assignee = ctx["assignee"]
            short = (
                assignee.replace("claude-code-", "@Arq:")
                .replace("opencode-", "@Dev:")
            )
            return f"Escribí tu mensaje… (@arquitecto, {short}, /help)"
        return "Escribí tu mensaje… (@arquitecto, /help, F1)"

    # ── Polling ─────────────────────────────────────────────────────

    async def _poll(self) -> None:
        """Periodic poll for new messages and agent status."""
        try:
            await self._fetch_messages()
            await self._fetch_agents()
        except Exception as exc:
            logger.warning("ChatPanel poll error: %s", exc)

    async def _fetch_messages(self) -> None:
        """Fetch messages and render them in the log.

        Contextual mode:
            Uses ``get_messages_for_task`` and deduplicates via
            ``_rendered_ids`` set.

        General mode:
            Incremental polling via ``since`` parameter using the
            last known rowid.
        """
        try:
            ctx = self.task_context
            if ctx is not None:
                # Contextual: always fetch ALL messages for the task
                messages = await self._bridge.get_messages_for_task(ctx["id"])
            elif self._known_id is not None:
                # General incremental
                messages = await self._bridge.get_messages(since=self._known_id)
            else:
                # First load — fetch latest 100
                messages = await self._bridge.get_messages(limit=100)
        except Exception as exc:
            logger.warning("Failed to fetch messages: %s", exc)
            return

        log = self.query_one("#chat-log", RichLog)
        for msg in messages:
            rowid = msg.get("rowid")
            if rowid is not None:
                if ctx is not None:
                    # Contextual dedup by rendered_ids set
                    if rowid in self._rendered_ids:
                        continue
                    self._rendered_ids.add(rowid)
                else:
                    # General dedup by since
                    self._known_id = str(rowid)

            try:
                ts = TuiBridge._format_time(msg.get("created_at", ""))
                sender = rich_escape(msg.get("sender", "?"))
                text = rich_escape(msg.get("text", ""))
                target = msg.get("target")

                line = f"[dim]{ts}[/dim] [bold]{sender}:[/bold]"
                if target:
                    line += f" [bold cyan]@{rich_escape(target)}[/bold cyan]"
                line += f" {text}"
                log.write(line)
            except Exception as exc:
                logger.warning(
                    "Failed to render message rowid=%s: %s", rowid, exc
                )

    async def _fetch_agents(self) -> None:
        """Fetch registered agents and update reactive status."""
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

    # ── Send ────────────────────────────────────────────────────────

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Send button press."""
        if event.button.id == "chat-send-btn":
            await self._do_send()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input field."""
        if event.input.id == "chat-input":
            await self._do_send()

    async def _do_send(self) -> None:
        """Send the current input as a chat message, or handle /commands."""
        inp = self.query_one("#chat-input", Input)
        text = inp.value.strip()
        if not text:
            return

        # ── Handle /commands ────────────────────────────────────────
        if text == "/clear":
            inp.value = ""
            self.action_clear_log()
            return

        if text == "/help":
            inp.value = ""
            self.action_toggle_help()
            return

        # ── Send message ────────────────────────────────────────────
        inp.value = ""

        # Extract first @mention from text to set the routing target
        mention = re.search(r"@(\w+)", text)
        target: str | None = None
        if mention:
            target = mention.group(1)

        try:
            ctx = self.task_context
            thread_id: str | None = ctx["id"] if ctx is not None else None
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

        # Refresh immediately so the sent message appears right away
        await self._fetch_messages()

    # ── Public API ──────────────────────────────────────────────────

    def focus_input(self) -> None:
        """Focus the message input field."""
        try:
            inp = self.query_one("#chat-input", Input)
            inp.focus()
        except Exception:
            pass

    # ── Actions ─────────────────────────────────────────────────────

    def action_clear_log(self) -> None:
        """Clear the visible chat log without affecting the database."""
        try:
            log = self.query_one("#chat-log", RichLog)
            log.clear()
            log.write("[dim]— pantalla limpiada —[/dim]")
        except Exception as exc:
            logger.warning("Failed to clear log: %s", exc)

    def action_toggle_help(self) -> None:
        """Show or hide the quick-reference help panel."""
        try:
            panel = self.query_one("#chat-help-panel", Static)
            if "visible" in panel.classes:
                panel.remove_class("visible")
            else:
                panel.add_class("visible")
        except Exception as exc:
            logger.warning("Failed to toggle help: %s", exc)

    # ── Help text ───────────────────────────────────────────────────

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
            lines.append(
                f"  [{color}]{kind:<10}[/{color}]"
                f"[bold]{token:<18}[/bold]{desc}"
            )
        return "\n".join(lines)

"""KanbanTUI — main Textual app for Agent Bridge supervisor hub.

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │  🔷 Agents-Bridge-MCP  │  🟢 Arq · 🟢 Dev  │  💬 3 msgs│
  ├──────────────────────────────────────────────────────────┤
  │  📊  12 tareas  ·  5 pendientes  ·  3 en progreso       │
  ├──────────────────────┬───────────────────────────────────┤
  │  TaskList            │  TaskDetail                      │
  │  (navegable con ↑↓)  │  (detalle contextual)            │
  ├──────────────────────┴───────────────────────────────────┤
  │  [N] Nueva  [M] Mover  [D] Detalle  [K] Chat  [Q] Salir │
  └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import contextlib
import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static

from agent_bridge.state.database import Database
from agent_bridge.ui.chat_overlay import ChatOverlay
from agent_bridge.ui.create_task_modal import CreateTaskModal
from agent_bridge.ui.db_watcher import DBWatcher
from agent_bridge.ui.kanban_board import KanbanBoard, TaskList
from agent_bridge.ui.move_task_modal import MoveTaskModal
from agent_bridge.ui.tui_bridge import TuiBridge

logger = logging.getLogger(__name__)


class KanbanTUI(App):
    """Agent Bridge Kanban — hub central del supervisor.

    Shows tasks in a vertical task list with a detail panel.
    Supports keyboard navigation, new/move actions, and chat overlay.
    Auto-refreshes via DBWatcher polling.
    """

    CSS = """
    Screen {
        layout: vertical;
    }

    #header-bar {
        height: 1;
        background: $panel;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }

    #summary-bar {
        height: 1;
        background: $surface;
        color: $text-muted;
        content-align: center middle;
    }

    KanbanBoard {
        height: 1fr;
    }

    #kanban-layout {
        height: 1fr;
    }

    TaskList {
        width: 40;
        min-width: 30;
        border: solid $primary;
        margin: 0 1;
        padding: 0 1;
    }

    TaskList:focus {
        border: solid $accent;
    }

    TaskItem {
        padding: 0 1;
    }

    TaskItem.selected {
        background: $accent 20%;
    }

    TaskDetail {
        width: 2fr;
        min-width: 30;
        border: solid $primary;
        margin: 0 1;
        padding: 1;
    }

    Footer {
        height: 1;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Arriba", show=False),
        Binding("down", "cursor_down", "Abajo", show=False),
        Binding("n", "new_task", "Nueva"),
        Binding("m", "move_task", "Mover"),
        Binding("d", "show_detail", "Detalle"),
        Binding("k", "toggle_chat", "Chat"),
        Binding("q", "quit", "Salir"),
        Binding("r", "refresh", "Refrescar", show=False),
    ]

    def __init__(self, db_path: str = "bridge.db", dry_run: bool = False) -> None:
        super().__init__()
        self._db = Database(db_path=db_path, dry_run=dry_run)
        self._bridge = TuiBridge(self._db)
        self._watcher = DBWatcher(self._db, interval=1.5, on_change=self._on_db_change)
        self._chat_open = False

    def compose(self) -> ComposeResult:
        yield Static(id="header-bar")
        yield Static(id="summary-bar")
        yield KanbanBoard()
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize DB, start watcher, and load initial data."""
        try:
            await self._db.initialize()
        except Exception as exc:
            self._update_header(f"AGENT BRIDGE — ERROR DE DB: {exc}")
            return

        self._update_header("🔷 Agents-Bridge-MCP  |  🟢 Conectando…")
        self._update_summary("📊  Cargando…")

        # Load initial tasks
        await self._load_tasks()
        await self._update_header_bar()
        await self._update_summary_bar()

        # Focus the task list for keyboard navigation
        with contextlib.suppress(Exception):
            self.query_one(TaskList).focus()

        # Start polling
        self.set_interval(1.5, self._poll_watcher)
        self.set_interval(5, self._update_header_bar)
        self.set_interval(5, self._update_summary_bar)

    # ── UI helpers ──────────────────────────────────────────────────

    def _update_header(self, text: str) -> None:
        """Set the header bar text."""
        with contextlib.suppress(Exception):
            self.query_one("#header-bar", Static).update(text)

    def _update_summary(self, text: str) -> None:
        """Set the summary bar text."""
        with contextlib.suppress(Exception):
            self.query_one("#summary-bar", Static).update(text)

    async def _update_header_bar(self) -> None:
        """Refresh the header with connection status and message count."""
        try:
            status_text = await self._bridge.get_connection_status()
            unread = await self._bridge.get_unread_message_count()
            self._update_header(f"🔷 Agents-Bridge-MCP  |  {status_text}  |  💬 {unread} msgs")
        except Exception as exc:
            logger.warning("Failed to update header: %s", exc)

    async def _update_summary_bar(self) -> None:
        """Refresh the summary with task counts."""
        try:
            counts = await self._bridge.get_task_counts()
            total = sum(counts.values())
            pending = counts.get("pending", 0)
            in_progress = counts.get("in_progress", 0)
            review = counts.get("review", 0)
            completed = counts.get("approved", 0)
            self._update_summary(
                f"📊  {total} tareas  ·  {pending} pendientes  ·  "
                f"{in_progress} en progreso  ·  {review} revisión  ·  "
                f"{completed} completadas"
            )
        except Exception as exc:
            logger.warning("Failed to update summary: %s", exc)

    # ── DB polling ──────────────────────────────────────────────────

    async def _poll_watcher(self) -> None:
        """Poll DB watcher to detect external changes."""
        try:
            await self._watcher.poll()
        except Exception as exc:
            logger.warning("Watcher poll error: %s", exc)

    async def _on_db_change(self, new_version: int) -> None:
        """Called by DBWatcher when data_version changes externally."""
        logger.debug("External DB change detected (v=%d)", new_version)
        await self._load_tasks()
        await self._update_header_bar()
        await self._update_summary_bar()

    async def _load_tasks(self) -> None:
        """Load tasks from DB and push to the kanban board."""
        try:
            tasks = await self._bridge.get_tasks()
        except Exception as exc:
            logger.warning("Failed to load tasks: %s", exc)
            return
        board = self.query_one(KanbanBoard)
        board.tasks = tasks

    # ── Actions ─────────────────────────────────────────────────────

    def action_cursor_up(self) -> None:
        """Navigate up in the task list."""
        with contextlib.suppress(Exception):
            self.query_one(TaskList).action_cursor_up()

    def action_cursor_down(self) -> None:
        """Navigate down in the task list."""
        with contextlib.suppress(Exception):
            self.query_one(TaskList).action_cursor_down()

    async def action_new_task(self) -> None:
        """Open the create task modal."""
        task_id = await self.push_screen(CreateTaskModal(self._bridge))
        if task_id:
            await self._after_task_created()

    async def _after_task_created(self) -> None:
        """Refresh the task list and summary after creation."""
        await self._load_tasks()
        await self._update_summary_bar()
        self.notify("✅ Tarea creada", severity="information", timeout=3)

    async def action_move_task(self) -> None:
        """Open move task modal for the selected task."""
        board = self.query_one(KanbanBoard)
        task = board.selected_task
        if task is None:
            self.notify("Seleccioná una tarea primero (↑↓)", severity="warning", timeout=2)
            return

        new_status = await self.push_screen(MoveTaskModal(task, self._bridge))
        if new_status:
            await self._after_task_moved()

    async def _after_task_moved(self) -> None:
        """Refresh the task list and summary after a status change."""
        await self._load_tasks()
        await self._update_summary_bar()
        self.notify("✅ Tarea movida", severity="information", timeout=3)

    def action_show_detail(self) -> None:
        """Placeholder: show full task detail."""
        self.notify("📄 Detalle completo — próximo release", timeout=2)

    async def action_toggle_chat(self) -> None:
        """Open chat overlay contextual to the selected task."""
        if self._chat_open:
            return
        self._chat_open = True

        board = self.query_one(KanbanBoard)
        task = board.selected_task

        overlay = ChatOverlay(self._bridge, task_context=task)

        self.push_screen(overlay, callback=lambda _: self._on_chat_closed())  # type: ignore[arg-type]

    def _on_chat_closed(self) -> None:
        """Handle chat overlay dismissal."""
        self._chat_open = False
        self.call_later(self._after_chat_closed)

    async def _after_chat_closed(self) -> None:
        """Refresh the kanban board after the chat closes."""
        await self._load_tasks()

    async def action_refresh(self) -> None:
        """Manually refresh the kanban board."""
        await self._load_tasks()
        await self._update_header_bar()
        await self._update_summary_bar()


def main(db_path: str = "bridge.db", dry_run: bool = False) -> None:
    """Launch the kanban TUI."""
    app = KanbanTUI(db_path=db_path, dry_run=dry_run)
    app.run()


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "bridge.db"
    main(db_path)

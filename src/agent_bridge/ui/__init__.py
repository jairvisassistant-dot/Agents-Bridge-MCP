"""User interface — Kanban TUI with chat overlay for human supervisor.

Provides:
- KanbanTUI: main Textual app with task kanban board
- ChatOverlay: modal chat overlay (Ctrl+K)
- KanbanBoard: widget showing tasks grouped by status
- TuiBridge: in-process Database wrapper for the UI
- DBWatcher: background poller for external DB changes
"""

from agent_bridge.ui.chat_overlay import ChatOverlay
from agent_bridge.ui.create_task_modal import CreateTaskModal
from agent_bridge.ui.db_watcher import DBWatcher
from agent_bridge.ui.kanban_board import KanbanBoard
from agent_bridge.ui.kanban_tui import KanbanTUI
from agent_bridge.ui.move_task_modal import MoveTaskModal
from agent_bridge.ui.tui_bridge import TuiBridge

__all__ = [
    "KanbanTUI",
    "ChatOverlay",
    "CreateTaskModal",
    "MoveTaskModal",
    "KanbanBoard",
    "TuiBridge",
    "DBWatcher",
]

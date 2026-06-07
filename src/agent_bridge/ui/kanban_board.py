"""Kanban board widget — vertical task list with detail panel.

Layout:
  ┌──────────────────────┬───────────────────────────────────┐
  │  TaskList            │  TaskDetail                      │
  │  (scrollable with ↑↓)│  (contextual detail on select)   │
  └──────────────────────┴───────────────────────────────────┘
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

# ── Status helpers ─────────────────────────────────────────────────────────────

STATUS_ICONS: dict[str, str] = {
    "pending": "●",
    "in_progress": "🔧",
    "review": "👁",
    "approved": "✅",
    "changes_requested": "🔄",
}

STATUS_LABELS: dict[str, str] = {
    "pending": "Pendiente",
    "in_progress": "En progreso",
    "review": "En revisión",
    "approved": "Completado",
    "changes_requested": "Cambios solicitados",
}


def _status_icon(status: str) -> str:
    """Return the display icon for a task status."""
    return STATUS_ICONS.get(status, "○")


def _status_label(status: str) -> str:
    """Return the display label for a task status."""
    return STATUS_LABELS.get(status, status)


def _short_assignee(assignee: str | None) -> str:
    """Shorten agent IDs for display."""
    if not assignee:
        return "—"
    return assignee.replace("claude-code-", "Arq:").replace("opencode-", "Dev:")


# ── TaskItem ────────────────────────────────────────────────────────────────────


class TaskItem(Static):
    """A single task row in the list.

    Shows icon, title, status badge, assignee.
    Highlighted via CSS class when selected.
    Responds to click for selection.
    """

    def __init__(self, task: dict[str, Any]) -> None:
        self._task = task
        icon = _status_icon(task.get("status", ""))
        title = rich_escape(task.get("title", "?"))
        assignee = _short_assignee(task.get("assignee"))
        label = _status_label(task.get("status", ""))
        task_id = (task.get("id") or "?")[:8]
        lines = [
            f"{icon} #{task_id} {title}",
            f"   {label}",
            f"   Asig: {assignee}",
        ]
        super().__init__("\n".join(lines))

    @property
    def task(self) -> dict[str, Any]:
        """Return the task dict for this item."""
        return self._task

    def on_click(self) -> None:
        """Notify parent TaskList to select this item."""
        parent = self.parent
        if parent is not None and hasattr(parent, "select_task"):
            parent.select_task(self)  # type: ignore[union-attr]


# ── TaskList ────────────────────────────────────────────────────────────────────


class TaskList(VerticalScroll):
    """Vertical scrollable list of TaskItems.

    Manages selection state (up/down navigates).
    Notifies parent via callback when selection changes.
    """

    tasks: reactive[list[dict[str, Any]]] = reactive([])
    selected_index: reactive[int] = 0

    def __init__(self) -> None:
        super().__init__()
        self.can_focus = True
        self._on_select: Any = None

    async def watch_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Rebuild the list when tasks change."""
        await self.remove_children()
        if not tasks:
            await self.mount(
                Static("[dim]📋 No hay tareas todavía\nPresioná N para crear[/dim]", id="empty-placeholder")
            )
            self.selected_index = 0
            self._notify_select()
            return

        items = [TaskItem(t) for t in tasks]
        await self.mount(*items)
        self.selected_index = 0
        self._update_highlight()
        self._notify_select()

    def watch_selected_index(self, old: int, new: int) -> None:
        """React to selection changes."""
        self._update_highlight()
        self._notify_select()

    def _update_highlight(self) -> None:
        """Apply or remove the 'selected' CSS class on items."""
        for i, child in enumerate(self.children):
            if isinstance(child, TaskItem):
                child.set_class(i == self.selected_index, "selected")

    def _notify_select(self) -> None:
        """Call the on_select callback if set."""
        if self._on_select is not None:
            self._on_select(self.selected_task)

    @property
    def selected_task(self) -> dict[str, Any] | None:
        """Return the currently selected task, or None."""
        children = list(self.children)
        if not children or self.selected_index >= len(children):
            return None
        child = children[self.selected_index]
        if isinstance(child, TaskItem):
            return child.task
        return None

    def select_task(self, item: TaskItem) -> None:
        """Select a specific TaskItem (called from click handler)."""
        for i, child in enumerate(self.children):
            if child is item:
                self.selected_index = i
                break

    def action_cursor_down(self) -> None:
        """Move selection down."""
        children = [c for c in self.children if isinstance(c, TaskItem)]
        max_idx = len(children) - 1
        if self.selected_index < max_idx:
            self.selected_index += 1
            target = children[self.selected_index]
            self.scroll_to_show(target)

    def action_cursor_up(self) -> None:
        """Move selection up."""
        children = [c for c in self.children if isinstance(c, TaskItem)]
        if self.selected_index > 0:
            self.selected_index -= 1
            target = children[self.selected_index]
            self.scroll_to_show(target)


# ── TaskDetail ──────────────────────────────────────────────────────────────────


class TaskDetail(Static):
    """Right panel showing details of the selected task.

    Shows title, description, status, assignee, plan, dates.
    Displays placeholder text when no task is selected.
    """

    task: reactive[dict[str, Any] | None] = reactive(None)

    CSS = """
    TaskDetail {
        padding: 1 2;
    }
    """

    def watch_task(self, task: dict[str, Any] | None) -> None:
        """Rebuild the detail view when the task changes."""
        if task is None:
            self.update("[dim]Seleccioná una tarea para ver detalle[/dim]")
            return

        title = rich_escape(task.get("title", "?"))
        desc = rich_escape(task.get("description", ""))
        status = _status_label(task.get("status", ""))
        assignee = _short_assignee(task.get("assignee"))
        plan_id = task.get("plan_id", "")
        created = task.get("created_at", "")
        updated = task.get("updated_at", "")

        lines = [f"[bold]{title}[/bold]"]
        if desc:
            lines.append("")
            lines.append(desc)
        lines.append("")
        lines.append(f"[bold]Estado:[/bold] {status}")
        lines.append(f"[bold]Asignado a:[/bold] {assignee}")
        if plan_id:
            lines.append(f"[bold]Plan:[/bold] {plan_id[:12]}")
        if created:
            lines.append(f"[bold]Creado:[/bold] {created[:10]}")
        if updated:
            lines.append(f"[bold]Actualizado:[/bold] {updated[:10]}")

        self.update("\n".join(lines))


# ── KanbanBoard ────────────────────────────────────────────────────────────────


class KanbanBoard(Static):
    """Main kanban layout: TaskList on the left, TaskDetail on the right.

    Uses Horizontal split. Detail panel shows contextual info when a task is selected.
    """

    tasks: reactive[list[dict[str, Any]]] = reactive([])

    def compose(self) -> ComposeResult:
        with Horizontal(id="kanban-layout"):
            yield TaskList()
            yield TaskDetail()

    def on_mount(self) -> None:
        """Wire the selection callback after compose."""
        task_list = self.query_one(TaskList)
        task_list._on_select = self._on_task_selected

    def watch_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Forward tasks to TaskList."""
        try:
            task_list = self.query_one(TaskList)
            task_list.tasks = tasks
        except Exception:
            pass  # Not mounted yet

    @property
    def selected_task(self) -> dict[str, Any] | None:
        """Return the currently selected task from the TaskList, or None."""
        try:
            task_list = self.query_one(TaskList)
            return task_list.selected_task
        except Exception:
            return None

    def _on_task_selected(self, task: dict[str, Any] | None) -> None:
        """Update the detail panel when a task is selected."""
        try:
            detail = self.query_one(TaskDetail)
            detail.task = task
        except Exception:
            pass  # Not mounted yet

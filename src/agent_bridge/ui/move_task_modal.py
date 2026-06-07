"""MoveTaskModal — modal to change a task's status.

Opens as a ModalScreen over the main kanban view.
Shows current status and valid target transitions.
Dismisses with the new status string on success, ``None`` on cancel.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, RadioButton, RadioSet, Static

from agent_bridge.state.state_machine import TASK_TRANSITIONS
from agent_bridge.ui.kanban_board import STATUS_ICONS, STATUS_LABELS
from agent_bridge.ui.tui_bridge import TuiBridge


class MoveTaskModal(ModalScreen[str | None]):
    """Modal to change a task's status.

    Shows current task info and all valid transition targets as radio buttons.
    Dismisses with the new status string on confirm, ``None`` on cancel.

    If the task is in a terminal state (``approved``), a message is shown
    instead and only a "Cerrar" button is available.
    """

    CSS = """
    MoveTaskModal {
        align: center middle;
    }

    #move-task-container {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 0 1;
    }

    #move-task-header {
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $primary;
        color: $text;
        margin: 0 -1;
    }

    #move-task-body {
        height: auto;
        padding: 1 0;
    }

    #task-info {
        height: auto;
        margin-bottom: 1;
    }

    #status-label {
        text-style: bold;
        margin-top: 1;
    }

    RadioSet {
        height: auto;
        margin: 1 0;
    }

    #terminal-message {
        height: auto;
        margin: 1 0;
        text-style: bold;
        color: $warning;
    }

    #button-row {
        height: 3;
        align: center middle;
        padding: 1 0;
    }

    #button-row Button {
        width: 16;
        margin: 0 1;
    }

    #cancel-btn {
        background: $surface;
        color: $text;
    }

    #move-btn {
        background: $primary;
        color: $text;
    }

    #close-btn {
        background: $surface;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancelar"),
    ]

    def __init__(self, task: dict[str, Any], bridge: TuiBridge) -> None:
        super().__init__()
        self._task = task
        self._bridge = bridge
        self._selected_status: str | None = None

    def compose(self) -> ComposeResult:
        status = self._task.get("status", "")
        title = self._task.get("title", "?")
        current_label = STATUS_LABELS.get(status, status)
        current_icon = STATUS_ICONS.get(status, "")
        valid_targets: set[str] = TASK_TRANSITIONS.get(status, set())

        with Container(id="move-task-container"):
            yield Static("📋 Mover tarea", id="move-task-header")
            with Vertical(id="move-task-body"):
                yield Static(f"Tarea: {title}", id="task-info")
                yield Static(
                    f"Estado actual: {current_icon} {current_label}",
                    id="status-label",
                )

                if not valid_targets:
                    # Terminal state — no transitions available
                    yield Static(
                        "⚠ Estado terminal — no se puede mover",
                        id="terminal-message",
                    )
                else:
                    yield Static("Mover a:")
                    buttons = [
                        RadioButton(
                            f"{STATUS_ICONS.get(t, '')} {STATUS_LABELS.get(t, t)}",
                            id=f"status-{t}",
                            value=(i == 0),
                        )
                        for i, t in enumerate(valid_targets)
                    ]
                    yield RadioSet(*buttons, id="status-radio")

            with Horizontal(id="button-row"):
                if not valid_targets:
                    yield Button("Cerrar", id="close-btn", variant="default")
                else:
                    yield Button("Cancelar", id="cancel-btn", variant="default")
                    yield Button("Mover", id="move-btn", variant="primary")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:  # type: ignore[name-defined]
        """Track the selected radio button."""
        if event.pressed.id and event.pressed.id.startswith("status-"):
            self._selected_status = event.pressed.id.replace("status-", "")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id in ("cancel-btn", "close-btn"):
            self.dismiss(None)
        elif event.button.id == "move-btn":
            await self._do_move()

    def action_cancel(self) -> None:
        """Dismiss the modal without moving."""
        self.dismiss(None)

    async def _do_move(self) -> None:
        """Validate selection and call bridge.move_task."""
        # If no radio change event fired yet, try to find the selected button
        if self._selected_status is None:
            try:
                radio_set = self.query_one("#status-radio", RadioSet)
                for child in radio_set.children:
                    if hasattr(child, "value") and child.value:  # type: ignore[union-attr]
                        btn_id = child.id or ""
                        if btn_id.startswith("status-"):
                            self._selected_status = btn_id.replace("status-", "")
                            break
            except Exception:
                pass

        if self._selected_status is None:
            self.notify("Seleccioná un estado destino", severity="warning", timeout=2)
            return

        task_id = self._task.get("id", "")
        success = await self._bridge.move_task(task_id, self._selected_status)
        if success:
            self.dismiss(self._selected_status)
        else:
            self.notify(
                "No se pudo mover la tarea — transición inválida o tarea ya movida",
                severity="error",
                timeout=3,
            )

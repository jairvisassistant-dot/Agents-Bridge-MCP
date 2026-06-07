"""EditTaskModal — modal form to edit an existing kanban task.

Opens as a ModalScreen over the main kanban view.
Fields: title (required, pre-populated), description (optional, pre-populated).
Calls TuiBridge.update_task() on submit.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from agent_bridge.ui.tui_bridge import TuiBridge


class EditTaskModal(ModalScreen[str | None]):
    """Modal form to edit an existing task.

    Title and description are pre-populated with the task's current
    values.  The plan is not changeable from this modal.
    Dismisses with the task_id on success, ``None`` on cancel.
    Shows a validation error if the title is cleared.
    """

    CSS = """
    EditTaskModal {
        align: center middle;
    }

    #edit-task-container {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 0 1;
    }

    #edit-task-header {
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $primary;
        color: $text;
        margin: 0 -1;
    }

    #edit-task-form {
        height: auto;
        padding: 1 0;
    }

    .field-label {
        height: 1;
        margin-top: 1;
        text-style: bold;
    }

    #title-input {
        margin-top: 1;
    }

    TextArea {
        height: 4;
        border: solid $primary;
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

    #save-btn {
        background: $primary;
        color: $text;
    }

    .validation-error {
        color: $error;
        text-style: bold;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancelar"),
        Binding("ctrl+c", "cancel", "Cancelar", show=False),
    ]

    def __init__(self, task: dict[str, Any], bridge: TuiBridge) -> None:
        super().__init__()
        self._task = task
        self._bridge = bridge

    def compose(self) -> ComposeResult:
        title = self._task.get("title", "")
        description = self._task.get("description", "")

        with Container(id="edit-task-container"):
            yield Static("✏️ Editar Tarea", id="edit-task-header")
            with Vertical(id="edit-task-form"):
                yield Static("Título:", classes="field-label")
                yield Input(
                    id="title-input",
                    value=title,
                    placeholder="Título de la tarea (requerido)",
                )
                yield Static("Descripción:", classes="field-label")
                yield TextArea(id="description-input", text=description)
                yield Static(id="error-text", classes="validation-error")
            with Horizontal(id="button-row"):
                yield Button("Cancelar", id="cancel-btn", variant="default")
                yield Button("Guardar", id="save-btn", variant="primary")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            await self._do_save()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the title input — move focus to description."""
        if event.input.id == "title-input":
            self.query_one("#description-input", TextArea).focus()

    def action_cancel(self) -> None:
        """Dismiss the modal without saving."""
        self.dismiss(None)

    async def _do_save(self) -> None:
        """Validate inputs and update the task.

        Shows validation errors inline.  On DB error, shows a
        notification and leaves the modal open so the user can retry.
        """
        error_widget = self.query_one("#error-text", Static)
        title_input = self.query_one("#title-input", Input)
        desc_input = self.query_one("#description-input", TextArea)

        title = title_input.value.strip()
        description = desc_input.text

        # Validate
        if not title:
            error_widget.update("[red]⚠ El título no puede estar vacío[/]")
            title_input.focus()
            return

        # Clear previous error
        error_widget.update("")

        task_id = self._task.get("id", "")
        success = await self._bridge.update_task(
            task_id=task_id,
            title=title,
            description=description,
        )
        if success:
            self.dismiss(task_id)
        else:
            self.notify(
                "No se pudo actualizar — tarea no encontrada o ya no es editable",
                severity="error",
                timeout=3,
            )

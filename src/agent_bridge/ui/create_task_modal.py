"""CreateTaskModal — modal form to create a new kanban task.

Opens as a ModalScreen over the main kanban view.
Fields: title (required), description (optional), plan (optional select).
Calls TuiBridge.create_task() on submit.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static, TextArea

from agent_bridge.ui.tui_bridge import TaskValidationError, TuiBridge


class CreateTaskModal(ModalScreen[str | None]):
    """Modal form to create a new task.

    Fields: title (required), description (optional), plan (optional select).
    Dismisses with the new task_id on success, ``None`` on cancel.
    Shows validation error if title is empty.
    """

    CSS = """
    CreateTaskModal {
        align: center middle;
    }

    #create-task-container {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 0 1;
    }

    #create-task-header {
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $primary;
        color: $text;
        margin: 0 -1;
    }

    #create-task-form {
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

    Select {
        margin-top: 1;
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

    #create-btn {
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

    def __init__(self, bridge: TuiBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._plans: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Container(id="create-task-container"):
            yield Static("📋 Nueva Tarea", id="create-task-header")
            with Vertical(id="create-task-form"):
                yield Static("Título:", classes="field-label")
                yield Input(id="title-input", placeholder="Título de la tarea (requerido)")
                yield Static("Descripción:", classes="field-label")
                yield TextArea(id="description-input", text="")
                yield Static("Plan:", classes="field-label")
                yield Select(
                    id="plan-select",
                    options=[("Cargando...", "__loading__")],
                    prompt="Seleccionar plan",
                )
                yield Static(id="error-text", classes="validation-error")
            with Horizontal(id="button-row"):
                yield Button("Cancelar", id="cancel-btn", variant="default")
                yield Button("Crear", id="create-btn", variant="primary")

    async def on_mount(self) -> None:
        """Load plans and populate the plan selector."""
        try:
            self._plans = await self._bridge.get_plans()
        except Exception:
            self._plans = []

        plan_select = self.query_one("#plan-select", Select)
        if self._plans:
            options = [(p["title"], p["id"]) for p in self._plans]
            plan_select.options = options
        else:
            plan_select.options = [("(sin planes)", "__no_plans__")]
            plan_select.disabled = True

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "create-btn":
            await self._do_create()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the title input — move focus to description."""
        if event.input.id == "title-input":
            self.query_one("#description-input", TextArea).focus()

    def action_cancel(self) -> None:
        """Dismiss the modal without creating a task."""
        self.dismiss(None)

    async def _do_create(self) -> None:
        """Validate inputs and create the task.

        Shows validation errors inline. On DB error, shows a notification
        and leaves the modal open so the user can retry.
        """
        error_widget = self.query_one("#error-text", Static)
        title_input = self.query_one("#title-input", Input)
        desc_input = self.query_one("#description-input", TextArea)
        plan_select = self.query_one("#plan-select", Select)

        title = title_input.value.strip()
        description = desc_input.text
        plan_id: str | None = plan_select.value if not plan_select.disabled else None

        # Validate
        if not title:
            error_widget.update("[red]⚠ El título no puede estar vacío[/]")
            title_input.focus()
            return

        # Check that a plan is available (FK constraint in DB requires it)
        if not self._plans:
            error_widget.update("[red]⚠ No hay planes disponibles. Creá un plan primero.[/]")
            return

        # Clear previous error
        error_widget.update("")

        try:
            task_id = await self._bridge.create_task(
                title=title,
                description=description,
                plan_id=plan_id,
            )
        except TaskValidationError as exc:
            error_widget.update(f"[red]⚠ {exc}[/]")
            title_input.focus()
            return
        except Exception as exc:
            error_msg = str(exc)
            # Provide a friendlier message for FK constraint failures
            if "FOREIGN KEY" in error_msg:
                self.notify(
                    "Error de base de datos: el plan seleccionado ya no existe. Cancelá y volvé a intentar.",
                    severity="error",
                    timeout=5,
                )
            else:
                self.notify(
                    f"Error al crear tarea: {exc}",
                    severity="error",
                    timeout=5,
                )
            return

        self.dismiss(task_id)

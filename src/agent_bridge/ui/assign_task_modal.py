"""AssignTaskModal — modal to assign a task to an available agent.

Opens as a ModalScreen over the main kanban view.
Shows a list of available (non-offline) agents as radio buttons.
Dismisses with the selected agent_id on confirm, ``None`` on cancel.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, RadioButton, RadioSet, Static

from agent_bridge.ui.tui_bridge import TuiBridge

# ── Helpers ──────────────────────────────────────────────────────────────────


def _agent_status_icon(status: str) -> str:
    """Return a coloured circle icon for the agent's connectivity status."""
    return {"online": "🟢", "busy": "🟡", "offline": "⚫"}.get(status, "⚫")


# ── Modal ────────────────────────────────────────────────────────────────────


class AssignTaskModal(ModalScreen[str | None]):
    """Modal to assign a task to an agent.

    Shows every agent whose status is not ``offline`` as a radio button
    (agent name + role + status icon).  Dismisses with the selected
    ``agent_id`` on confirm, ``None`` on cancel.

    If no agents are available a message is shown instead and only a
    "Cerrar" button is displayed.
    """

    CSS = """
    AssignTaskModal {
        align: center middle;
    }

    #assign-task-container {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 0 1;
    }

    #assign-task-header {
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $primary;
        color: $text;
        margin: 0 -1;
    }

    #assign-task-body {
        height: auto;
        padding: 1 0;
    }

    #task-info {
        height: auto;
        margin-bottom: 1;
    }

    #agents-label {
        text-style: bold;
        margin-top: 1;
    }

    RadioSet {
        height: auto;
        margin: 1 0;
    }

    #no-agents-message {
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

    #assign-btn {
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
        Binding("ctrl+c", "cancel", "Cancelar", show=False),
    ]

    def __init__(self, task: dict[str, Any], bridge: TuiBridge) -> None:
        super().__init__()
        self._task = task
        self._bridge = bridge
        self._agents: list[dict[str, Any]] = []
        self._selected_agent: str | None = None

    def compose(self) -> ComposeResult:
        title = self._task.get("title", "?")
        task_id = (self._task.get("id") or "?")[:8]

        with Container(id="assign-task-container"):
            yield Static("👤 Asignar tarea", id="assign-task-header")
            with Vertical(id="assign-task-body"):
                yield Static(
                    f"Tarea: {title}  [#a0a0a0]#{task_id}[/]",
                    id="task-info",
                )
                # Agents will be populated in on_mount
                yield Static("Cargando agentes…", id="agents-label")
                yield RadioSet(id="agents-radio")
                yield Static(id="no-agents-message")

            with Horizontal(id="button-row"):
                yield Button("Cancelar", id="cancel-btn", variant="default")
                yield Button("Asignar", id="assign-btn", variant="primary")

    async def on_mount(self) -> None:
        """Load available agents and populate the radio set."""
        try:
            self._agents = await self._bridge.get_available_agents()
        except Exception:
            self._agents = []

        agents_label = self.query_one("#agents-label", Static)
        radio_set = self.query_one("#agents-radio", RadioSet)
        no_agents = self.query_one("#no-agents-message", Static)
        assign_btn = self.query_one("#assign-btn", Button)

        if not self._agents:
            agents_label.update("Agentes disponibles:")
            no_agents.update("⚠ No hay agentes conectados")
            radio_set.disabled = True
            assign_btn.disabled = True
            return

        agents_label.update("Seleccionar agente:")
        buttons = [
            RadioButton(
                f"{_agent_status_icon(a.get('status', ''))}  "
                f"{a.get('name', a.get('agent_id', '?'))}  "
                f"[dim]{a.get('role', '')}[/dim]",
                id=f"agent-{a['agent_id']}",
                value=(i == 0),
            )
            for i, a in enumerate(self._agents)
        ]
        await radio_set.clear()
        for btn in buttons:
            await radio_set.mount(btn)

        # Select the first button by default
        if buttons:
            radio_set.index = 0
            self._selected_agent = self._agents[0]["agent_id"]

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:  # type: ignore[name-defined]
        """Track the selected radio button."""
        if event.pressed.id and event.pressed.id.startswith("agent-"):
            self._selected_agent = event.pressed.id.replace("agent-", "")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id in ("cancel-btn", "close-btn"):
            self.dismiss(None)
        elif event.button.id == "assign-btn":
            await self._do_assign()

    def action_cancel(self) -> None:
        """Dismiss the modal without assigning."""
        self.dismiss(None)

    async def _do_assign(self) -> None:
        """Validate selection and dismiss with the agent_id."""
        if self._selected_agent is None:
            # Try to read the currently selected radio
            try:
                radio_set = self.query_one("#agents-radio", RadioSet)
                for child in radio_set.children:
                    if hasattr(child, "value") and child.value:  # type: ignore[union-attr]
                        btn_id = child.id or ""
                        if btn_id.startswith("agent-"):
                            self._selected_agent = btn_id.replace("agent-", "")
                            break
            except Exception:
                pass

        if self._selected_agent is None:
            self.notify(
                "Seleccioná un agente disponible",
                severity="warning",
                timeout=2,
            )
            return

        self.dismiss(self._selected_agent)

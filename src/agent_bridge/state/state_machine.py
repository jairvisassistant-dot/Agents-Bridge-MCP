"""State machine — validates all state transitions for plans, tasks, reviews, and threads.

Every state change in the system goes through this module. If a transition
isn't defined here, it's rejected with a clear error message.
"""

from typing import TypeVar

from agent_bridge.state.models import (
    PlanStatus,
    ReviewStatus,
    TaskStatus,
    ThreadStatus,
)

# ── Generic transition helpers ───────────────────────────────────

T = TypeVar("T")


class TransitionError(ValueError):
    """Raised when a state transition is not allowed."""

    def __init__(self, entity: str, current: str, target: str):
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {entity} cannot go from '{current}' to '{target}'")


def validate_transition(
    entity_name: str,
    current: T,
    target: T,
    allowed: dict[T, set[T]],
) -> None:
    """Check if a transition is valid; raise TransitionError if not."""
    if current not in allowed:
        raise TransitionError(entity_name, str(current), str(target))
    if target not in allowed[current]:
        raise TransitionError(entity_name, str(current), str(target))


# ── Plan transitions ──────────────────────────────────────────────

PLAN_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    "idle": {"planning"},
    "planning": {"tasks_ready", "idle"},
    "tasks_ready": {"in_progress", "idle"},
    "in_progress": {"completed", "idle"},
    "completed": set(),  # terminal state
}


def validate_plan_transition(current: PlanStatus, target: PlanStatus) -> None:
    validate_transition("plan", current, target, PLAN_TRANSITIONS)


# ── Task transitions ──────────────────────────────────────────────

TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    "pending": {"in_progress"},
    "in_progress": {"review"},
    "review": {"approved", "changes_requested"},
    "changes_requested": {"review"},  # re-submit after fixes
    "approved": set(),  # terminal state
}


def validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    validate_transition("task", current, target, TASK_TRANSITIONS)


# ── Review transitions ────────────────────────────────────────────

REVIEW_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    "pending": {"in_review"},
    "in_review": {"approved", "changes_requested"},
    "approved": set(),
    "changes_requested": set(),
}


def validate_review_transition(current: ReviewStatus, target: ReviewStatus) -> None:
    validate_transition("review", current, target, REVIEW_TRANSITIONS)


# ── Thread transitions ────────────────────────────────────────────

THREAD_TRANSITIONS: dict[ThreadStatus, set[ThreadStatus]] = {
    "open": {"resolved"},
    "resolved": set(),
}


def validate_thread_transition(current: ThreadStatus, target: ThreadStatus) -> None:
    validate_transition("thread", current, target, THREAD_TRANSITIONS)


# ── Quick lookup helpers (for tool handlers) ──────────────────────

def can_transition(entity_type: str, current: str, target: str) -> bool:
    """Return True if the transition is valid, without raising."""
    transition_map = {
        "plan": PLAN_TRANSITIONS,
        "task": TASK_TRANSITIONS,
        "review": REVIEW_TRANSITIONS,
        "thread": THREAD_TRANSITIONS,
    }
    rules = transition_map.get(entity_type)
    if not rules:
        return False
    return current in rules and target in rules[current]

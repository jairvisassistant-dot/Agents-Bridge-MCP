"""Type aliases for Agent Bridge state machines.

Pydantic model classes (Plan, Task, Review, Agent, Message, Thread) were
removed in ARCH-04 — they were defined but never instantiated at runtime.
Only type aliases (Literal types) and Skill (used in config.py) remain.
"""

from typing import Literal

from pydantic import BaseModel

# ── Plan ──────────────────────────────────────────────────────────

PlanStatus = Literal["idle", "planning", "tasks_ready", "in_progress", "completed", "archived"]

# ── Task ──────────────────────────────────────────────────────────

TaskStatus = Literal["pending", "in_progress", "review", "approved", "changes_requested"]

# ── Review ─────────────────────────────────────────────────────────

ReviewStatus = Literal["pending", "in_review", "approved", "changes_requested"]

# ── Agent ──────────────────────────────────────────────────────────

AgentStatus = Literal["online", "busy", "away", "offline"]

# ── Skill (actively used in config.py) ─────────────────────────────


class Skill(BaseModel):
    """A role definition with allowed tools, instructions, and restrictions."""

    name: str
    version: int = 1
    description: str = ""
    allowed_tools: list[str] = []
    instructions: list[str] = []
    restrictions: dict = {}

# ── Thread ─────────────────────────────────────────────────────────

ThreadStatus = Literal["open", "resolved"]

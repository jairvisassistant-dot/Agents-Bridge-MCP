"""Data models for Agent Bridge — Pydantic types for all entities."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ── Plan ──────────────────────────────────────────────────────────

PlanStatus = Literal["idle", "planning", "tasks_ready", "in_progress", "completed"]


class Plan(BaseModel):
    """A work plan created by the architect agent."""

    id: str
    title: str
    description: str = ""
    status: PlanStatus = "idle"
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Task ──────────────────────────────────────────────────────────

TaskStatus = Literal[
    "pending", "in_progress", "review", "approved", "changes_requested"
]


class Task(BaseModel):
    """A single task belonging to a plan."""

    id: str
    plan_id: str
    title: str
    description: str = ""
    status: TaskStatus = "pending"
    assignee: str | None = None
    submission_summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Review ─────────────────────────────────────────────────────────

ReviewStatus = Literal["pending", "in_review", "approved", "changes_requested"]


class Review(BaseModel):
    """A review cycle for a task's work."""

    id: str
    task_id: str
    reviewer: str = "architect"
    status: ReviewStatus = "pending"
    comment: str | None = None
    created_at: datetime | None = None


# ── Agent ──────────────────────────────────────────────────────────

AgentStatus = Literal["online", "busy", "away", "offline"]


class Agent(BaseModel):
    """A connected agent session with presence tracking."""

    agent_id: str
    role: str = "default"
    status: AgentStatus = "online"
    last_seen: datetime | None = None
    connected_since: datetime | None = None
    metadata: dict = {}


# ── Skill ──────────────────────────────────────────────────────────


class Skill(BaseModel):
    """A role definition with allowed tools, instructions, and restrictions."""

    name: str
    version: int = 1
    description: str = ""
    allowed_tools: list[str] = []
    instructions: list[str] = []
    restrictions: dict = {}


# ── Message ────────────────────────────────────────────────────────


class Message(BaseModel):
    """A chat message between participants."""

    id: str
    thread_id: str | None = None
    sender: str  # human, arquitecto, desarrollador, system
    target: str | None = None  # @mention
    text: str
    turn_number: int | None = None  # turn index in threaded discussions
    created_at: datetime | None = None


# ── Thread ─────────────────────────────────────────────────────────

ThreadStatus = Literal["open", "resolved"]


class Thread(BaseModel):
    """A discussion thread with participants, turn tracking, and timeout."""

    id: str
    title: str
    status: ThreadStatus = "open"
    participants: list[str] = []  # JSON array; empty = public (no turn-taking)
    current_turn: str | None = None  # agent_name who should speak next
    last_activity_at: datetime | None = None
    created_at: datetime | None = None

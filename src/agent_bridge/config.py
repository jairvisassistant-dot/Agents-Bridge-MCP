"""Configuration loader — bridge.json, role resolution, built-in skills."""

import json
import logging
import os
from pathlib import Path

from agent_bridge.state.models import Skill

logger = logging.getLogger(__name__)

# ── Default config paths (searched in order) ──────────────────────

CONFIG_PATHS = [
    Path.cwd() / "bridge.json",
    Path.home() / ".config" / "agent-bridge" / "bridge.json",
    Path.home() / ".agent-bridge.json",
]


# ── Built-in skills ───────────────────────────────────────────────

BUILTIN_SKILLS: dict[str, Skill] = {
    "architect": Skill(
        name="architect",
        version=1,
        description="Skill del Arquitecto — planifica, revisa, aprueba",
        allowed_tools=[
            "plan.create", "plan.get", "plan.list", "plan.update",
            "plan.export", "plan.import",
            "task.create", "task.list", "task.get", "task.get_diff",
            "review.start", "review.approve", "review.request_changes",
            "review.get_history",
            "chat.send", "chat.read", "chat.thread_create", "chat.thread_list",
            "agent.heartbeat", "agent.list", "agent.get", "agent.set_status",
            "agent.whoami",
            "skill.list", "skill.get",
            "hello",
        ],
        instructions=[
            "Eres el Arquitecto del proyecto.",
            "Creas planes de trabajo con plan.create.",
            "Defines tareas con task.create.",
            "Revisas el trabajo del desarrollador con review.*.",
            "Puedes aprobar o solicitar cambios.",
            "Siempre que recibas un @arquitecto, DEBES responder.",
        ],
        restrictions={
            "max_concurrent_reviews": 3,
            "can_escalate_to_human": True,
        },
    ),
    "developer": Skill(
        name="developer",
        version=1,
        description="Skill del Desarrollador — implementa, corrige, entrega",
        allowed_tools=[
            "task.list", "task.get", "task.claim", "task.submit_work",
            "chat.send", "chat.read", "chat.thread_create", "chat.thread_list",
            "agent.heartbeat", "agent.list", "agent.get", "agent.set_status",
            "agent.whoami",
            "skill.list", "skill.get",
            "hello",
        ],
        instructions=[
            "Eres el Desarrollador del proyecto.",
            "Tomas tareas del plan con task.claim.",
            "Implementas y subes resultados con task.submit_work.",
            "Respondes a cambios solicitados por el arquitecto.",
            "Siempre que recibas un @desarrollador, DEBES responder.",
        ],
        restrictions={
            "cannot_approve_own_work": True,
            "max_concurrent_tasks": 2,
        },
    ),
    "default": Skill(
        name="default",
        version=1,
        description="Skill por defecto — solo chat y presencia",
        allowed_tools=[
            "chat.send", "chat.read", "chat.thread_create", "chat.thread_list",
            "agent.heartbeat", "agent.list", "agent.get",
            "agent.whoami",
            "skill.list", "skill.get",
            "hello",
        ],
        instructions=[
            "Eres un agente con permisos limitados.",
            "Solo puedes usar chat y consultar estado.",
            "Contacta al administrador para asignarte un rol.",
        ],
        restrictions={},
    ),
}


# ── Config loader ─────────────────────────────────────────────────


class BridgeConfig:
    """Loaded bridge.json configuration — agent roles, settings, custom skills."""

    def __init__(self, data: dict | None = None):
        self.agents: list[dict] = data.get("agents", []) if data else []
        self.settings: dict = data.get("settings", {}) if data else {}
        self.custom_skills: dict[str, Skill] = {}
        if data and "skills" in data:
            for s in data["skills"]:
                self.custom_skills[s["name"]] = Skill(**s)

    def get_role_for_agent(self, agent_id: str) -> str:
        """Resolve role for an agent_id from bridge.json agents list."""
        for a in self.agents:
            if a.get("id") == agent_id:
                return a.get("role", "default")
        return "default"

    def get_skill_for_role(self, role: str) -> Skill:
        """Get the effective skill for a role (custom → built-in → default)."""
        if role in self.custom_skills:
            return self.custom_skills[role]
        if role in BUILTIN_SKILLS:
            return BUILTIN_SKILLS[role]
        return BUILTIN_SKILLS["default"]

    def list_skills(self) -> list[dict]:
        """Return all available skills (built-in + custom)."""
        all_skills = dict(BUILTIN_SKILLS)
        all_skills.update(self.custom_skills)
        return [
            {"name": s.name, "version": s.version, "description": s.description}
            for s in all_skills.values()
        ]

    @classmethod
    def load(cls) -> "BridgeConfig":
        """Load bridge.json from the first path found, or return defaults."""
        for path in CONFIG_PATHS:
            if path.exists():
                logger.info("Loading config from %s", path)
                try:
                    with open(path) as f:
                        return cls(json.load(f))
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load %s: %s", path, e)
                    break
        logger.info("No bridge.json found, using defaults")
        return cls()

    @classmethod
    def init_default_config(cls, path: Path | None = None) -> Path:
        """Create a default bridge.json at the given path or cwd."""
        target = path or Path.cwd() / "bridge.json"
        default = {
            "version": 1,
            "agents": [
                {
                    "id": "claude-code-1",
                    "name": "Terminal Principal",
                    "role": "architect",
                    "metadata": {"type": "claude-code"},
                },
                {
                    "id": "opencode-1",
                    "name": "Terminal Secundaria",
                    "role": "developer",
                    "metadata": {"type": "opencode"},
                },
            ],
            "settings": {
                "heartbeat_interval_seconds": 30,
                "offline_timeout_seconds": 300,
                "default_skill": "default",
            },
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w") as f:
            json.dump(default, f, indent=2)
        logger.info("Default config created at %s", target)
        return target

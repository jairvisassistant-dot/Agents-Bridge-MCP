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

# ── Built-in skill template files ─────────────────────────────────

SKILLS_DIR = Path(__file__).parent / "skills"


def _load_builtin_skills() -> dict[str, Skill]:
    """Load built-in skill templates from JSON files, falling back to hardcoded dict.

    Each file under SKILLS_DIR named {role}.json is loaded.  If a file is missing
    or invalid, the hardcoded fallback is used for that role.
    """
    hardcoded = _hardcoded_skills()

    result: dict[str, Skill] = {}
    for role, fallback in hardcoded.items():
        path = SKILLS_DIR / f"{role}.json"
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                result[role] = Skill(**data)
                logger.debug("Loaded skill template from %s", path)
                continue
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logger.warning("Failed to load %s: %s — using hardcoded fallback", path, e)
        result[role] = fallback
    return result


# Cache for get_builtin_skills — (skills_dict, max_mtime)
_builtin_skills_cache: tuple[dict[str, Skill], float] | None = None


def get_builtin_skills() -> dict[str, Skill]:
    """Return built-in skills, reloading from disk when JSON files change.

    The function caches the loaded skills and checks the mtime of each
    skill JSON file on every call.  If any file has been modified since
    the last load, it reloads from disk.  This enables hot-reload of
    skill definitions while the server is running.
    """
    global _builtin_skills_cache

    # Compute the most recent mtime among existing skill files
    max_mtime = 0.0
    for role in _hardcoded_skills():
        path = SKILLS_DIR / f"{role}.json"
        if path.exists():
            try:
                mtime = path.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                pass

    # Reload if cache is missing or stale
    if _builtin_skills_cache is None or max_mtime > _builtin_skills_cache[1]:
        _builtin_skills_cache = (_load_builtin_skills(), max_mtime)

    return _builtin_skills_cache[0]


def _hardcoded_skills() -> dict[str, Skill]:
    """Hardcoded fallback skill templates (used when JSON files are missing)."""
    return {
        "architect": Skill(
            name="architect",
            version=1,
            description="Skill del Arquitecto — planifica, revisa, aprueba",
            allowed_tools=[
            "plan.create",
            "plan.get",
            "plan.list",
            "plan.update",
            "plan.export",
            "plan.import",
            "plan.archive",
            "plan.delete",
            "task.create",
            "task.list",
            "task.get",
            "task.get_diff",
            "task.update",
            "task.delete",
            "review.start",
            "review.approve",
            "review.request_changes",
            "review.get_history",
            "chat.send",
            "chat.read",
            "chat.thread_create",
            "chat.thread_list",
            "chat.thread_get_pending",
            "chat.thread_resolve",
            "chat.mark_read",
            "agent.heartbeat",
            "agent.list",
            "agent.get",
            "agent.set_status",
            "agent.whoami",
            "agent.ping",
            "agent.pong",
            "agent.idle",
            "agent.shutdown_request",
            "agent.shutdown_approve",
            "skill.list",
            "skill.get",
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
            "task.list",
            "task.get",
            "task.claim",
            "task.update",
            "task.delete",
            "task.submit_work",
            "chat.send",
            "chat.read",
            "chat.thread_create",
            "chat.thread_list",
            "chat.thread_get_pending",
            "chat.thread_resolve",
            "chat.mark_read",
            "agent.heartbeat",
            "agent.list",
            "agent.get",
            "agent.set_status",
            "agent.whoami",
            "agent.ping",
            "agent.pong",
            "agent.idle",
            "agent.shutdown_request",
            "agent.shutdown_approve",
            "skill.list",
            "skill.get",
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
            "chat.send",
            "chat.read",
            "chat.thread_create",
            "chat.thread_list",
            "chat.thread_get_pending",
            "chat.thread_resolve",
            "chat.mark_read",
            "agent.heartbeat",
            "agent.list",
            "agent.get",
            "agent.whoami",
            "skill.list",
            "skill.get",
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
        builtin = get_builtin_skills()
        if role in self.custom_skills:
            return self.custom_skills[role]
        if role in builtin:
            return builtin[role]
        return builtin["default"]

    def list_skills(self) -> list[dict]:
        """Return all available skills (built-in + custom)."""
        all_skills = dict(get_builtin_skills())
        all_skills.update(self.custom_skills)
        return [{"name": s.name, "version": s.version, "description": s.description} for s in all_skills.values()]

    @classmethod
    def load(cls) -> "BridgeConfig":
        """Load bridge.json from the first path found, or return defaults.

        Path resolution order:
          1. AGENT_BRIDGE_CONFIG env var (highest precedence)
          2. CONFIG_PATHS list (cwd/bridge.json, ~/.config/..., ~/.agent-bridge.json)
        """
        # 1. AGENT_BRIDGE_CONFIG env var
        env_path = os.environ.get("AGENT_BRIDGE_CONFIG")
        if env_path:
            p = Path(env_path)
            if p.exists():
                logger.info("Loading config from AGENT_BRIDGE_CONFIG=%s", env_path)
                try:
                    with open(p) as f:
                        return cls(json.load(f))
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load %s: %s", env_path, e)

        # 2. Standard config paths
        for path in CONFIG_PATHS:
            if path.exists():
                # Warn when resolving via cwd — fragile in production
                if path.parent == Path.cwd():
                    logger.warning(
                        "Config resolved via cwd: %s — set AGENT_BRIDGE_CONFIG for "
                        "a stable path independent of working directory",
                        path,
                    )
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

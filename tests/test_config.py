"""Tests for configuration loader — bridge.json, role resolution, built-in skills."""

import json
import tempfile
from pathlib import Path

from agent_bridge.config import BridgeConfig, get_builtin_skills, CONFIG_PATHS


class TestBuiltinSkills:
    def test_architect_has_plan_tools(self):
        skills = get_builtin_skills()
        skill = skills["architect"]
        assert "plan.create" in skill.allowed_tools
        assert "review.approve" in skill.allowed_tools
        assert "task.claim" not in skill.allowed_tools  # dev-only
        assert "task.submit_work" not in skill.allowed_tools  # dev-only

    def test_developer_has_task_tools(self):
        skills = get_builtin_skills()
        skill = skills["developer"]
        assert "task.claim" in skill.allowed_tools
        assert "task.submit_work" in skill.allowed_tools
        assert "review.approve" not in skill.allowed_tools  # arch-only
        assert "task.get_diff" not in skill.allowed_tools  # arch-only

    def test_default_has_minimal_tools(self):
        skills = get_builtin_skills()
        skill = skills["default"]
        assert "hello" in skill.allowed_tools
        assert "chat.send" in skill.allowed_tools
        assert "plan.create" not in skill.allowed_tools

    def test_all_skills_have_heartbeat(self):
        skills = get_builtin_skills()
        for name, skill in skills.items():
            assert "agent.heartbeat" in skill.allowed_tools, f"{name} missing heartbeat"


class TestBridgeConfig:
    def test_default_config_no_file(self):
        config = BridgeConfig()
        assert config.get_role_for_agent("unknown") == "default"

    def test_role_resolution_from_config(self):
        data = {
            "agents": [
                {"id": "arch-1", "role": "architect"},
                {"id": "dev-1", "role": "developer"},
            ]
        }
        config = BridgeConfig(data)
        assert config.get_role_for_agent("arch-1") == "architect"
        assert config.get_role_for_agent("dev-1") == "developer"
        assert config.get_role_for_agent("unknown") == "default"

    def test_skill_for_role_builtin(self):
        config = BridgeConfig()
        skill = config.get_skill_for_role("architect")
        assert skill.name == "architect"

    def test_skill_for_role_default(self):
        config = BridgeConfig()
        skill = config.get_skill_for_role("nonexistent")
        assert skill.name == "default"

    def test_skill_for_role_custom(self):
        data = {
            "skills": [
                {
                    "name": "senior-dev",
                    "version": 1,
                    "description": "Senior dev with limited review",
                    "allowed_tools": ["task.list", "task.claim", "task.submit_work"],
                    "instructions": [],
                    "restrictions": {},
                }
            ]
        }
        config = BridgeConfig(data)
        skill = config.get_skill_for_role("senior-dev")
        assert skill.name == "senior-dev"
        assert "task.claim" in skill.allowed_tools

    def test_list_skills_includes_builtin_and_custom(self):
        data = {
            "skills": [
                {
                    "name": "custom-role",
                    "allowed_tools": ["hello"],
                    "instructions": [],
                    "restrictions": {},
                }
            ]
        }
        config = BridgeConfig(data)
        skills = config.list_skills()
        names = [s["name"] for s in skills]
        assert "architect" in names
        assert "developer" in names
        assert "custom-role" in names

    def test_init_default_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bridge.json"
            BridgeConfig.init_default_config(path)
            assert path.exists()
            with open(path) as f:
                data = json.load(f)
            assert data["version"] == 1
            assert len(data["agents"]) == 2
            assert data["agents"][0]["role"] == "architect"
            assert data["agents"][1]["role"] == "developer"

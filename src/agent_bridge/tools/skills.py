"""Skill discovery tools — list and inspect available skills."""

import json
import logging

import mcp.types as types

from agent_bridge.config import BridgeConfig

logger = logging.getLogger(__name__)

SKILL_TOOLS = [
    types.Tool(
        name="skill.list",
        description="List all available skills (built-in + custom)",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="skill.get",
        description="Get full details of a skill including allowed tools and instructions",
        inputSchema={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name (architect, developer, or custom)",
                },
            },
            "required": ["skill_name"],
        },
    ),
]


async def handle_skill_tool(config: BridgeConfig, name: str, args: dict) -> list[types.TextContent] | None:
    if name == "skill.list":
        return _list_skills(config)
    elif name == "skill.get":
        return _get_skill(config, args)
    return None


def _list_skills(config: BridgeConfig) -> list[types.TextContent]:
    skills = config.list_skills()
    return [types.TextContent(type="text", text=json.dumps(skills, indent=2))]


def _get_skill(config: BridgeConfig, args: dict) -> list[types.TextContent]:
    skill_name = args.get("skill_name")
    if not skill_name:
        return [types.TextContent(type="text", text='{"error": "skill_name required"}')]

    skill = config.get_skill_for_role(skill_name)
    if skill.name == "default" and skill_name != "default":
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": f"skill '{skill_name}' not found"}),
            )
        ]

    return [
        types.TextContent(
            type="text",
            text=skill.model_dump_json(indent=2),
        )
    ]

"""Plan management tools — create, get, list, update plans."""

import json
import logging
import uuid

import mcp.types as types

from agent_bridge.state.database import Database
from agent_bridge.state.state_machine import TransitionError, validate_plan_transition

logger = logging.getLogger(__name__)

PLAN_TOOLS = [
    types.Tool(
        name="plan.create",
        description="Create a new work plan",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Plan title"},
                "description": {"type": "string", "description": "Plan description"},
            },
            "required": ["title"],
        },
    ),
    types.Tool(
        name="plan.get",
        description="Get plan details by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID"},
            },
            "required": ["plan_id"],
        },
    ),
    types.Tool(
        name="plan.list",
        description="List all plans",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="plan.update",
        description="Update plan status",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID"},
                "status": {
                    "type": "string",
                    "description": "New status (idle, planning, tasks_ready, in_progress, completed)",
                },
            },
            "required": ["plan_id", "status"],
        },
    ),
    types.Tool(
        name="plan.export",
        description="Export a plan with all its tasks and reviews as JSON",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID to export"},
            },
            "required": ["plan_id"],
        },
    ),
    types.Tool(
        name="plan.import",
        description="Import a plan from exported JSON data",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_data": {
                    "type": "object",
                    "description": "Plan data in the same format as plan.export output",
                },
            },
            "required": ["plan_data"],
        },
    ),
    types.Tool(
        name="plan.archive",
        description="Archive a plan (soft-delete) — no new tasks can be added",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID to archive"},
            },
            "required": ["plan_id"],
        },
    ),
    types.Tool(
        name="plan.delete",
        description="Permanently delete a plan with ALL its tasks and reviews. Irreversible.",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID to delete"},
            },
            "required": ["plan_id"],
        },
    ),
]


async def handle_plan_tool(db: Database, name: str, args: dict) -> list[types.TextContent] | None:
    if name == "plan.create":
        return await _create_plan(db, args)
    elif name == "plan.get":
        return await _get_plan(db, args)
    elif name == "plan.list":
        return await _list_plans(db)
    elif name == "plan.update":
        return await _update_plan(db, args)
    elif name == "plan.export":
        return await _export_plan(db, args)
    elif name == "plan.import":
        return await _import_plan(db, args)
    elif name == "plan.archive":
        return await _archive_plan(db, args)
    elif name == "plan.delete":
        return await _delete_plan(db, args)
    return None


async def _create_plan(db: Database, args: dict) -> list[types.TextContent]:
    title = args.get("title", "Untitled Plan")
    description = args.get("description", "")
    plan_id = str(uuid.uuid4())

    # Validate against state machine: idle → planning
    try:
        validate_plan_transition("idle", "planning")
    except TransitionError:
        return [types.TextContent(type="text", text=json.dumps({"error": "cannot create plan in current state"}))]

    await db.execute(
        "INSERT INTO plans (id, title, description, status) VALUES (?, ?, ?, 'planning')",
        (plan_id, title, description),
    )

    logger.info("Created plan %s: %s (status=planning)", plan_id, title)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"plan_id": plan_id, "status": "planning"}),
        )
    ]


async def _get_plan(db: Database, args: dict) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    if not plan_id:
        return [types.TextContent(type="text", text='{"error": "plan_id required"}')]

    row = await db.execute_one("SELECT * FROM plans WHERE id = ?", (plan_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "plan not found"}')]

    # Include associated tasks
    task_rows = await db.execute(
        "SELECT id, title, description, status, assignee FROM tasks WHERE plan_id = ? ORDER BY created_at ASC",
        (plan_id,),
    )
    tasks = [
        {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "assignee": t["assignee"],
            "description": t.get("description", ""),
        }
        for t in task_rows
    ]

    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "plan_id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "tasks": tasks,
            }),
        )
    ]


async def _list_plans(db: Database) -> list[types.TextContent]:
    rows = await db.execute("SELECT id, title, status, created_at FROM plans ORDER BY created_at DESC")
    plans = [{"id": r["id"], "title": r["title"], "status": r["status"]} for r in rows]
    return [types.TextContent(type="text", text=json.dumps(plans))]


async def _update_plan(db: Database, args: dict) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    target_status = args.get("status")

    if not plan_id or not target_status:
        return [types.TextContent(type="text", text='{"error": "plan_id and status required"}')]

    # Validate transition
    row = await db.execute_one("SELECT status FROM plans WHERE id = ?", (plan_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "plan not found"}')]

    current_status = row["status"]
    try:
        validate_plan_transition(current_status, target_status)
    except TransitionError as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

    await db.execute(
        "UPDATE plans SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (target_status, plan_id),
    )

    return [
        types.TextContent(
            type="text",
            text=json.dumps({"plan_id": plan_id, "status": target_status}),
        )
    ]


async def _export_plan(db: Database, args: dict) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    if not plan_id:
        return [types.TextContent(type="text", text='{"error": "plan_id required"}')]

    data = await db.get_plan_export(plan_id)
    if data is None:
        return [types.TextContent(type="text", text='{"error": "plan not found"}')]

    return [
        types.TextContent(
            type="text",
            text=json.dumps(data),
        )
    ]


async def _import_plan(db: Database, args: dict) -> list[types.TextContent]:
    plan_data = args.get("plan_data")
    if not plan_data:
        return [types.TextContent(type="text", text='{"error": "plan_data required"}')]

    result = await db.import_plan(plan_data)
    logger.info(
        "Imported plan %s with %d tasks",
        result["plan_id"],
        result["tasks_count"],
    )
    return [
        types.TextContent(
            type="text",
            text=json.dumps(result),
        )
    ]


async def _archive_plan(db: Database, args: dict) -> list[types.TextContent]:
    """Soft-delete a plan by setting status to 'archived'."""
    plan_id = args.get("plan_id")
    if not plan_id:
        return [types.TextContent(type="text", text='{"error": "plan_id required"}')]

    row = await db.execute_one("SELECT status FROM plans WHERE id = ?", (plan_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "plan not found"}')]

    try:
        validate_plan_transition(row["status"], "archived")
    except TransitionError as e:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": str(e)})
        )]

    await db.execute(
        "UPDATE plans SET status = 'archived', updated_at = datetime('now') WHERE id = ?",
        (plan_id,),
    )
    logger.info("Archived plan %s", plan_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"plan_id": plan_id, "status": "archived"}),
        )
    ]


async def _delete_plan(db: Database, args: dict) -> list[types.TextContent]:
    """Permanently delete a plan and cascade to all tasks and reviews."""
    plan_id = args.get("plan_id")
    if not plan_id:
        return [types.TextContent(type="text", text='{"error": "plan_id required"}')]

    row = await db.execute_one("SELECT id FROM plans WHERE id = ?", (plan_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "plan not found"}')]

    # Full cascade: messages → threads → reviews → tasks → plan
    await db.execute(
        "DELETE FROM messages WHERE thread_id IN (SELECT id FROM tasks WHERE plan_id = ?)",
        (plan_id,),
    )
    await db.execute(
        "DELETE FROM threads WHERE id IN (SELECT id FROM tasks WHERE plan_id = ?)",
        (plan_id,),
    )
    await db.execute(
        "DELETE FROM reviews WHERE task_id IN (SELECT id FROM tasks WHERE plan_id = ?)",
        (plan_id,),
    )
    await db.execute("DELETE FROM tasks WHERE plan_id = ?", (plan_id,))
    await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))

    logger.info("Deleted plan %s with all tasks and reviews", plan_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"plan_id": plan_id, "deleted": True}),
        )
    ]

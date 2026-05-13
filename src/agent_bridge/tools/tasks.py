"""Task management tools — create, claim, list, submit, get tasks."""

import json
import logging
import uuid

import mcp.types as types

from agent_bridge.state.database import Database
from agent_bridge.state.state_machine import validate_task_transition, TransitionError

logger = logging.getLogger(__name__)

TASK_TOOLS = [
    types.Tool(
        name="task.create",
        description="Create a new task in a plan",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Parent plan ID"},
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
            },
            "required": ["plan_id", "title"],
        },
    ),
    types.Tool(
        name="task.list",
        description="List tasks, optionally filtered by plan or status",
        inputSchema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Filter by plan ID"},
                "status": {
                    "type": "string",
                    "description": "Filter by status (pending, in_progress, review, approved, changes_requested)",
                },
            },
        },
    ),
    types.Tool(
        name="task.claim",
        description="Claim a task — sets assignee + status to in_progress",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "agent": {
                    "type": "string",
                    "description": "Agent name (developer, architect)",
                    "default": "developer",
                },
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="task.get",
        description="Get task details by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="task.submit_work",
        description="Submit completed work for review, optionally with a diff",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "summary": {"type": "string", "description": "Summary of what was done"},
                "diff": {
                    "type": "string",
                    "description": "Git diff or changes made (for architect review)",
                },
            },
            "required": ["task_id", "summary"],
        },
    ),
    types.Tool(
        name="task.get_diff",
        description="Get the diff submitted with a task's work (architect review)",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["task_id"],
        },
    ),
]


async def handle_task_tool(
    db: Database, name: str, args: dict
) -> list[types.TextContent] | None:
    if name == "task.create":
        return await _create_task(db, args)
    elif name == "task.list":
        return await _list_tasks(db, args)
    elif name == "task.claim":
        return await _claim_task(db, args)
    elif name == "task.get":
        return await _get_task(db, args)
    elif name == "task.submit_work":
        return await _submit_work(db, args)
    elif name == "task.get_diff":
        return await _get_diff(db, args)
    return None


async def _create_task(
    db: Database, args: dict
) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    title = args.get("title", "Untitled Task")
    description = args.get("description", "")
    task_id = str(uuid.uuid4())

    if not plan_id:
        return [types.TextContent(type="text", text='{"error": "plan_id required"}')]

    await db.execute(
        "INSERT INTO tasks (id, plan_id, title, description) VALUES (?, ?, ?, ?)",
        (task_id, plan_id, title, description),
    )

    logger.info("Created task %s in plan %s", task_id, plan_id)
    return [
        types.TextContent(
            type="text",
            text=f'{{"task_id": "{task_id}", "status": "pending"}}',
        )
    ]


async def _list_tasks(
    db: Database, args: dict
) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    status_filter = args.get("status")

    if plan_id:
        rows = await db.execute(
            "SELECT * FROM tasks WHERE plan_id = ? ORDER BY created_at",
            (plan_id,),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM tasks ORDER BY created_at"
        )

    tasks = []
    for r in rows:
        if status_filter and r["status"] != status_filter:
            continue
        tasks.append({
            "id": r["id"],
            "plan_id": r["plan_id"],
            "title": r["title"],
            "status": r["status"],
            "assignee": r["assignee"],
        })

    return [types.TextContent(type="text", text=json.dumps(tasks))]


async def _claim_task(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    agent = args.get("agent", "developer")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # Atomic: UPDATE only if pending, rowcount tells us if it worked
    affected = await db.execute_write(
        "UPDATE tasks SET status = 'in_progress', assignee = ?, updated_at = datetime('now') "
        "WHERE id = ? AND status = 'pending'",
        (agent, task_id),
    )

    if affected == 0:
        row = await db.execute_one(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            return [types.TextContent(
                type="text", text='{"error": "task not found"}'
            )]
        try:
            validate_task_transition(row["status"], "in_progress")
        except TransitionError as e:
            return [types.TextContent(type="text", text=f'{{"error": "{e}"}}')]
        # Shouldn't reach here if validate passed, but safeguard
        return [types.TextContent(
            type="text",
            text=f'{{"error": "task is {row["status"]}, could not claim"}}',
        )]

    logger.info("Task %s claimed by %s", task_id, agent)
    return [
        types.TextContent(
            type="text",
            text=f'{{"task_id": "{task_id}", "status": "in_progress", "assignee": "{agent}"}}',
        )
    ]


async def _submit_work(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    summary = args.get("summary", "")
    diff = args.get("diff", "")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # Atomic: UPDATE only if status allows transition to review
    affected = await db.execute_write(
        "UPDATE tasks SET status = 'review', submission_summary = ?, diff_text = ?, "
        "updated_at = datetime('now') WHERE id = ? AND status IN ('in_progress', 'changes_requested')",
        (summary, diff, task_id),
    )

    if affected == 0:
        row = await db.execute_one(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            return [types.TextContent(
                type="text", text='{"error": "task not found"}'
            )]
        try:
            validate_task_transition(row["status"], "review")
        except TransitionError as e:
            return [types.TextContent(type="text", text=f'{{"error": "{e}"}}')]
        return [types.TextContent(
            type="text",
            text=f'{{"error": "task is {row["status"]}, could not submit"}}',
        )]

    logger.info("Work submitted for task %s", task_id)
    return [
        types.TextContent(
            type="text",
            text=f'{{"task_id": "{task_id}", "status": "review"}}',
        )
    ]


async def _get_task(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    row = await db.execute_one(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    )
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]

    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "id": row["id"],
                "plan_id": row["plan_id"],
                "title": row["title"],
                "status": row["status"],
                "assignee": row["assignee"],
                "submission_summary": row["submission_summary"],
                "has_diff": bool(row["diff_text"]),
            }),
        )
    ]


async def _get_diff(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    row = await db.execute_one(
        "SELECT id, status, submission_summary, diff_text FROM tasks WHERE id = ?",
        (task_id,),
    )
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]

    return [
        types.TextContent(
            type="text",
            text=json.dumps({
                "task_id": row["id"],
                "status": row["status"],
                "submission_summary": row["submission_summary"],
                "diff": row["diff_text"] or "",
            }),
        )
    ]

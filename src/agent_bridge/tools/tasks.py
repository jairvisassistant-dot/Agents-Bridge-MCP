"""Task management tools — create, claim, list, submit, get tasks."""

import json
import logging
import uuid

import mcp.types as types

from agent_bridge.state.database import Database
from agent_bridge.state.state_machine import TransitionError, validate_task_transition

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
                "depends_on": {
                    "type": "string",
                    "description": "Optional task ID that must be approved before this task can be claimed",
                },
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
    types.Tool(
        name="task.update",
        description="Update a task's title and/or description. Only pending/in_progress tasks can be updated.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="task.delete",
        description="Delete a task permanently. Only allowed for pending or in_progress tasks.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["task_id"],
        },
    ),
]


async def handle_task_tool(db: Database, name: str, args: dict) -> list[types.TextContent] | None:
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
    elif name == "task.update":
        return await _update_task(db, args)
    elif name == "task.delete":
        return await _delete_task(db, args)
    return None


async def _create_task(db: Database, args: dict) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    title = args.get("title", "Untitled Task")
    description = args.get("description", "")
    depends_on = args.get("depends_on")
    task_id = str(uuid.uuid4())

    if not plan_id:
        return [types.TextContent(type="text", text='{"error": "plan_id required"}')]

    # Validate plan is not in a terminal state
    plan_row = await db.execute_one("SELECT status FROM plans WHERE id = ?", (plan_id,))
    if plan_row is None:
        return [types.TextContent(type="text", text='{"error": "plan not found"}')]
    if plan_row["status"] in ("completed", "archived"):
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"plan is {plan_row['status']}, cannot add tasks"})
        )]

    # Validate depends_on references an existing task
    if depends_on:
        dep = await db.execute_one("SELECT id FROM tasks WHERE id = ?", (depends_on,))
        if dep is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"dependency task '{depends_on}' not found"})
            )]

    await db.execute(
        "INSERT INTO tasks (id, plan_id, title, description, depends_on) VALUES (?, ?, ?, ?, ?)",
        (task_id, plan_id, title, description, depends_on),
    )

    logger.info("Created task %s in plan %s (depends_on=%s)", task_id, plan_id, depends_on)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"task_id": task_id, "status": "pending"}),
        )
    ]


async def _list_tasks(db: Database, args: dict) -> list[types.TextContent]:
    plan_id = args.get("plan_id")
    status_filter = args.get("status")

    if plan_id:
        rows = await db.execute(
            "SELECT * FROM tasks WHERE plan_id = ? ORDER BY created_at",
            (plan_id,),
        )
    else:
        rows = await db.execute("SELECT * FROM tasks ORDER BY created_at")

    tasks = []
    for r in rows:
        if status_filter and r["status"] != status_filter:
            continue
        tasks.append(
            {
                "id": r["id"],
                "plan_id": r["plan_id"],
                "title": r["title"],
                "status": r["status"],
                "assignee": r["assignee"],
            }
        )

    return [types.TextContent(type="text", text=json.dumps(tasks))]


async def _claim_task(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    _agent_role = args.get("_agent_role")
    agent = _agent_role if _agent_role not in (None, "default") else args.get("agent", "developer")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # ── max_concurrent_tasks check ────────────────────────────
    restrictions = args.get("_restrictions", {})
    max_tasks = restrictions.get("max_concurrent_tasks", None)
    if max_tasks is not None:
        count = await db.execute_one(
            "SELECT COUNT(*) as cnt FROM tasks WHERE assignee = ? AND status = 'in_progress'",
            (agent,),
        )
        if count and count["cnt"] >= max_tasks:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "error": "max_concurrent_tasks_reached",
                    "detail": f"Already at the maximum of {max_tasks} concurrent in_progress tasks. Complete or release one first.",
                })
            )]

    # ── depends_on checks ─────────────────────────────────────
    task_row = await db.execute_one(
        "SELECT depends_on, status FROM tasks WHERE id = ?", (task_id,)
    )
    if task_row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]

    depends_on = task_row["depends_on"]

    if depends_on:
        # Check dependency exists and is approved
        dep = await db.execute_one(
            "SELECT id, status FROM tasks WHERE id = ?", (depends_on,)
        )
        if dep is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"dependency task '{depends_on}' not found"})
            )]
        if dep["status"] != "approved":
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "error": "dependency_not_approved",
                    "detail": f"Dependency task '{depends_on}' has status '{dep['status']}', must be 'approved'",
                })
            )]

        # Circular dependency detection: walk the depends_on chain
        visited = {task_id}
        current = depends_on
        while current:
            if current in visited:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "circular_dependency",
                        "detail": f"Circular dependency detected involving task '{current}'",
                    })
                )]
            visited.add(current)
            parent = await db.execute_one(
                "SELECT depends_on FROM tasks WHERE id = ?", (current,)
            )
            current = parent["depends_on"] if parent else None

    # Read current status FIRST
    row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]

    # Validate transition BEFORE write (state machine enforcement)
    try:
        validate_task_transition(row["status"], "in_progress")
    except TransitionError as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

    # Atomic: UPDATE using the read status (captures race conditions)
    affected = await db.execute_write(
        "UPDATE tasks SET status = 'in_progress', assignee = ?, updated_at = datetime('now') "
        "WHERE id = ? AND status = ?",
        (agent, task_id, row["status"]),
    )

    if affected == 0:
        # Race condition: another claim won between our SELECT and UPDATE
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": "concurrent claim detected, task was already claimed"}),
            )
        ]

    logger.info("Task %s claimed by %s", task_id, agent)
    # Notify chat
    title = await db.get_task_title(task_id)
    sender_name = args.get("_sender_name", "desarrollador")
    await db.notify_chat(f"🟡 {sender_name} está trabajando en: {title}", sender=sender_name)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"task_id": task_id, "status": "in_progress", "assignee": agent}),
        )
    ]


async def _submit_work(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    summary = args.get("summary", "")
    diff = args.get("diff", "")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # Read current status FIRST
    row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]

    # Validate transition BEFORE write (state machine enforcement)
    try:
        validate_task_transition(row["status"], "review")
    except TransitionError as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

    # Atomic: UPDATE using the read status (captures race conditions)
    affected = await db.execute_write(
        "UPDATE tasks SET status = 'review', submission_summary = ?, diff_text = ?, "
        "updated_at = datetime('now') WHERE id = ? AND status = ?",
        (summary, diff, task_id, row["status"]),
    )

    if affected == 0:
        # Race condition: status changed between SELECT and UPDATE
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": "concurrent submit detected, task status changed"}),
            )
        ]

    logger.info("Work submitted for task %s", task_id)
    # Notify chat
    title = await db.get_task_title(task_id)
    sender_name = args.get("_sender_name", "desarrollador")
    await db.notify_chat(f"📤 {sender_name} entregó: {title}", sender=sender_name)
    # System notification to architect
    await db.send_system_notification(
        target="arquitecto",
        text=f"'{title}' entregada para revisión.",
        msg_type="status_update",
        priority="normal",
    )
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"task_id": task_id, "status": "review"}),
        )
    ]


async def _get_task(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    row = await db.execute_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "id": row["id"],
                    "plan_id": row["plan_id"],
                    "title": row["title"],
                    "status": row["status"],
                    "assignee": row["assignee"],
                    "submission_summary": row["submission_summary"],
                    "has_diff": bool(row["diff_text"]),
                }
            ),
        )
    ]


async def _get_diff(db: Database, args: dict) -> list[types.TextContent]:
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
            text=json.dumps(
                {
                    "task_id": row["id"],
                    "status": row["status"],
                    "submission_summary": row["submission_summary"],
                    "diff": row["diff_text"] or "",
                }
            ),
        )
    ]


async def _update_task(db: Database, args: dict) -> list[types.TextContent]:
    """Update a task's title and/or description."""
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    title = args.get("title")
    description = args.get("description")

    if not title and not description:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "at least one of 'title' or 'description' is required"})
        )]

    # Only pending/in_progress tasks can be updated
    row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]
    if row["status"] not in ("pending", "in_progress"):
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"task is {row['status']}, can only update pending or in_progress tasks"})
        )]

    # Build dynamic UPDATE
    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    updates.append("updated_at = datetime('now')")
    params.append(task_id)

    await db.execute(
        f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
        params,
    )

    updated = {"task_id": task_id}
    if title:
        updated["title"] = title
    if description:
        updated["description"] = description
    logger.info("Updated task %s", task_id)
    return [types.TextContent(type="text", text=json.dumps(updated))]


async def _delete_task(db: Database, args: dict) -> list[types.TextContent]:
    """Delete a task permanently. Only pending or in_progress tasks can be deleted."""
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    row = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]
    if row["status"] not in ("pending", "in_progress"):
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "error": f"task is {row['status']}, can only delete pending or in_progress tasks"
            })
        )]

    # Delete associated reviews first, then the task
    await db.execute("DELETE FROM reviews WHERE task_id = ?", (task_id,))
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    logger.info("Deleted task %s", task_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"task_id": task_id, "deleted": True}),
        )
    ]

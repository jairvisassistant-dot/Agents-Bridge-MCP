"""Review management tools — start, approve, request changes."""

import json
import logging
import uuid

import mcp.types as types

from agent_bridge.state.database import Database

logger = logging.getLogger(__name__)

REVIEW_TOOLS = [
    types.Tool(
        name="review.start",
        description="Start a review for a submitted task",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to review"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="review.approve",
        description="Approve a task's work",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "comment": {"type": "string", "description": "Approval comment"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="review.request_changes",
        description="Request changes on a task's work",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "changes": {
                    "type": "string",
                    "description": "Description of required changes",
                },
            },
            "required": ["task_id", "changes"],
        },
    ),
    types.Tool(
        name="review.get_history",
        description="Get review history for a task",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["task_id"],
        },
    ),
]


async def handle_review_tool(db: Database, name: str, args: dict) -> list[types.TextContent] | None:
    if name == "review.start":
        return await _start_review(db, args)
    elif name == "review.approve":
        return await _approve_review(db, args)
    elif name == "review.request_changes":
        return await _request_changes(db, args)
    elif name == "review.get_history":
        return await _get_review_history(db, args)
    return None


MAX_REVIEW_CYCLES = 3


async def _check_review_cycles(db: Database, task_id: str) -> str | None:
    """Return an error message if the task has exceeded max review cycles, else None."""
    row = await db.execute_one(
        "SELECT COUNT(*) as cnt FROM reviews WHERE task_id = ? AND status = 'changes_requested'",
        (task_id,),
    )
    if row and row["cnt"] >= MAX_REVIEW_CYCLES:
        return json.dumps({
            "error": "max_review_cycles_reached",
            "detail": (
                f"This task has reached the maximum of {MAX_REVIEW_CYCLES} review cycles. "
                "Escalate to human for resolution."
            ),
        })
    return None


async def _start_review(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # Task must be in 'review' state to start a review
    task = await db.execute_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if task is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]
    if task["status"] != "review":
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": f"task is {task['status']}, must be review"}),
            )
        ]

    # Max 3 review cycles check
    cycle_error = await _check_review_cycles(db, task_id)
    if cycle_error:
        return [types.TextContent(type="text", text=cycle_error)]

    # Check for existing active review
    existing = await db.execute_one(
        "SELECT id FROM reviews WHERE task_id = ? AND status = 'in_review'",
        (task_id,),
    )
    if existing is not None:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "review already active", "review_id": existing["id"]})
        )]

    review_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO reviews (id, task_id, status) VALUES (?, ?, 'in_review')",
        (review_id, task_id),
    )

    logger.info("Started review %s for task %s", review_id, task_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"review_id": review_id, "status": "in_review"}),
        )
    ]


async def _approve_review(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    comment = args.get("comment", "")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # ── cannot_approve_own_work check ──────────────────────────
    restrictions = args.get("_restrictions", {})
    if restrictions.get("cannot_approve_own_work", False):
        task_row = await db.execute_one(
            "SELECT assignee FROM tasks WHERE id = ?", (task_id,)
        )
        if task_row and task_row["assignee"]:
            agent_role = args.get("_agent_role")
            if agent_role and task_row["assignee"] == agent_role:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "cannot_approve_own_work",
                        "detail": f"Agents with role '{agent_role}' cannot approve their own work.",
                    })
                )]

    # Centralized guard: transition_task() validates + updates task atomically
    ok = await db.transition_task(task_id, "approved")
    if not ok:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "cannot approve — task not found, invalid transition, or concurrent change"}),
        )]

    # Update the review record (separate transaction — approved is terminal so no race)
    await db.execute_write(
        """UPDATE reviews SET status = 'approved', comment = ?
           WHERE id = (SELECT id FROM reviews WHERE task_id = ? ORDER BY created_at DESC LIMIT 1)""",
        (comment, task_id),
    )

    logger.info("Task %s approved", task_id)
    # Notify chat
    title = await db.get_task_title(task_id)
    sender_name = args.get("_sender_name", "arquitecto")
    await db.notify_chat(f"✅ {sender_name} aprobó: {title}", sender=sender_name)
    # System notification to assignee
    task_row = await db.execute_one("SELECT assignee FROM tasks WHERE id = ?", (task_id,))
    if task_row and task_row["assignee"]:
        target_map = {"developer": "desarrollador", "architect": "arquitecto"}
        notify_target = target_map.get(task_row["assignee"], task_row["assignee"])
        await db.send_system_notification(
            target=notify_target,
            text=f"Tu tarea '{title}' fue aprobada.",
            msg_type="status_update",
            priority="high",
        )
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"task_id": task_id, "status": "approved", "comment": comment}),
        )
    ]


async def _request_changes(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    changes = args.get("changes", "")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]
    if not changes:
        return [types.TextContent(type="text", text='{"error": "changes description required"}')]

    # Max 3 review cycles check before requesting more changes
    cycle_error = await _check_review_cycles(db, task_id)
    if cycle_error:
        return [types.TextContent(type="text", text=cycle_error)]

    # Centralized guard: transition_task() validates + updates task atomically
    ok = await db.transition_task(task_id, "changes_requested")
    if not ok:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "cannot request changes — task not found or concurrent change"}),
        )]

    # Update the review record (separate transaction)
    await db.execute_write(
        """UPDATE reviews SET status = 'changes_requested', comment = ?
           WHERE id = (SELECT id FROM reviews WHERE task_id = ? ORDER BY created_at DESC LIMIT 1)""",
        (changes, task_id),
    )

    logger.info("Changes requested for task %s: %s", task_id, changes)
    # Notify chat
    title = await db.get_task_title(task_id)
    sender_name = args.get("_sender_name", "arquitecto")
    await db.notify_chat(f"🔄 {sender_name} pidió cambios en: {title}", sender=sender_name)
    # System notification to assignee
    task_row = await db.execute_one("SELECT assignee FROM tasks WHERE id = ?", (task_id,))
    if task_row and task_row["assignee"]:
        target_map = {"developer": "desarrollador", "architect": "arquitecto"}
        notify_target = target_map.get(task_row["assignee"], task_row["assignee"])
        await db.send_system_notification(
            target=notify_target,
            text=f"Tu tarea '{title}' requiere cambios: {changes[:200]}",
            msg_type="status_update",
            priority="high",
        )
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"task_id": task_id, "status": "changes_requested"}),
        )
    ]


async def _get_review_history(db: Database, args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    rows = await db.execute(
        "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at",
        (task_id,),
    )
    reviews = [
        {
            "id": r["id"],
            "status": r["status"],
            "comment": r["comment"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return [types.TextContent(type="text", text=json.dumps(reviews))]

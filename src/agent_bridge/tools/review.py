"""Review management tools — start, approve, request changes."""

import json
import logging
import uuid

import mcp.types as types

from agent_bridge.state.database import Database
from agent_bridge.state.state_machine import (
    validate_task_transition,
    validate_review_transition,
    TransitionError,
)

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


async def handle_review_tool(
    db: Database, name: str, args: dict
) -> list[types.TextContent] | None:
    if name == "review.start":
        return await _start_review(db, args)
    elif name == "review.approve":
        return await _approve_review(db, args)
    elif name == "review.request_changes":
        return await _request_changes(db, args)
    elif name == "review.get_history":
        return await _get_review_history(db, args)
    return None


async def _start_review(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # Task must be in 'review' state to start a review
    task = await db.execute_one(
        "SELECT status FROM tasks WHERE id = ?", (task_id,)
    )
    if task is None:
        return [types.TextContent(type="text", text='{"error": "task not found"}')]
    if task["status"] != "review":
        return [
            types.TextContent(
                type="text",
                text=f'{{"error": "task is {task["status"]}, must be review"}}',
            )
        ]

    review_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO reviews (id, task_id, status) VALUES (?, ?, 'in_review')",
        (review_id, task_id),
    )

    logger.info("Started review %s for task %s", review_id, task_id)
    return [
        types.TextContent(
            type="text",
            text=f'{{"review_id": "{review_id}", "status": "in_review"}}',
        )
    ]


async def _approve_review(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    comment = args.get("comment", "")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]

    # Validate task is in review state (atomic check)
    affected = await db.execute_write(
        "UPDATE tasks SET status = 'approved', updated_at = datetime('now') "
        "WHERE id = ? AND status = 'review'",
        (task_id,),
    )

    if affected == 0:
        row = await db.execute_one(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            return [types.TextContent(type="text", text='{"error": "task not found"}')]
        try:
            validate_task_transition(row["status"], "approved")
        except TransitionError as e:
            return [types.TextContent(type="text", text=f'{{"error": "{e}"}}')]
        return [types.TextContent(
            type="text",
            text=f'{{"error": "task is {row["status"]}, could not approve"}}',
        )]

    # Update the latest review record
    await db.execute(
        """UPDATE reviews SET status = 'approved', comment = ?
           WHERE id = (SELECT id FROM reviews WHERE task_id = ? ORDER BY created_at DESC LIMIT 1)""",
        (comment, task_id),
    )

    logger.info("Task %s approved", task_id)
    return [
        types.TextContent(
            type="text",
            text=f'{{"task_id": "{task_id}", "status": "approved", "comment": "{comment}"}}',
        )
    ]


async def _request_changes(
    db: Database, args: dict
) -> list[types.TextContent]:
    task_id = args.get("task_id")
    changes = args.get("changes", "")

    if not task_id:
        return [types.TextContent(type="text", text='{"error": "task_id required"}')]
    if not changes:
        return [
            types.TextContent(
                type="text", text='{"error": "changes description required"}'
            )
        ]

    # Atomic: UPDATE only if task is in 'review' state
    affected = await db.execute_write(
        "UPDATE tasks SET status = 'changes_requested', updated_at = datetime('now') "
        "WHERE id = ? AND status = 'review'",
        (task_id,),
    )

    if affected == 0:
        row = await db.execute_one(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            return [types.TextContent(type="text", text='{"error": "task not found"}')]
        try:
            validate_task_transition(row["status"], "changes_requested")
        except TransitionError as e:
            return [types.TextContent(type="text", text=f'{{"error": "{e}"}}')]
        return [types.TextContent(
            type="text",
            text=f'{{"error": "task is {row["status"]}, could not request changes"}}',
        )]

    # Update the latest review record
    await db.execute(
        """UPDATE reviews SET status = 'changes_requested', comment = ?
           WHERE id = (SELECT id FROM reviews WHERE task_id = ? ORDER BY created_at DESC LIMIT 1)""",
        (changes, task_id),
    )

    logger.info("Changes requested for task %s: %s", task_id, changes)
    return [
        types.TextContent(
            type="text",
            text=f'{{"task_id": "{task_id}", "status": "changes_requested"}}',
        )
    ]


async def _get_review_history(
    db: Database, args: dict
) -> list[types.TextContent]:
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

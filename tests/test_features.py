"""Tests for Phase 7 features — restrictions (7.2), dependencies (7.3), plan/task CRUD (7.4).

STRICT TDD MODE: handlers are called directly when custom _restrictions are needed,
or via the full MCP server pipeline for CRUD tests that validate the tool flow.
"""

import json
import tempfile
import uuid
from pathlib import Path

import anyio
import pytest
from mcp.types import CallToolRequest

from agent_bridge.server import create_server
from agent_bridge.state.database import Database
from agent_bridge.tools.review import handle_review_tool
from agent_bridge.tools.tasks import handle_task_tool


# ── Shared fixtures ─────────────────────────────────────────────


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)
    Path(path + ".lock").unlink(missing_ok=True)


# ── Shared helpers ──────────────────────────────────────────────


async def _call(server, tool: str, args: dict | None = None):
    """Call an MCP tool through the full server pipeline."""
    req = CallToolRequest(
        method="tools/call",
        params={"name": tool, "arguments": args or {}},
    )
    resp = await server.request_handlers[CallToolRequest](req)
    return json.loads(resp.root.content[0].text)


async def _call_handler(db: Database, handler, tool_name: str, args: dict) -> dict:
    """Call a tool handler directly, bypassing server permissions.

    This is necessary for restriction tests where custom `_restrictions`
    and `_agent_role` must be passed without server overrides.
    """
    result = await handler(db, tool_name, args)
    return json.loads(result[0].text)


async def _setup_plan_with_task(db_path: str, extra_tasks: int = 0):
    """Insert a plan + 1 + extra_tasks tasks directly into DB.

    Returns (db_instance, plan_id, [task_ids]).
    """
    db = Database(db_path)
    await db.initialize()
    plan_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO plans (id, title, status) VALUES (?, 'Test Plan', 'tasks_ready')",
        (plan_id,),
    )
    task_ids = []
    for i in range(1 + extra_tasks):
        tid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks (id, plan_id, title, status) VALUES (?, ?, ?, 'pending')",
            (tid, plan_id, f"Task {i + 1}"),
        )
        task_ids.append(tid)
    return db, plan_id, task_ids


# ── Task 1: Test infrastructure helpers ─────────────────────────
# Shared fixtures and helpers defined above at module level.
# This class exercises them to ensure they are callable.


class TestInfrastructure:
    """Ensure shared helpers import and run correctly."""

    def test_db_path_fixture_works(self, db_path):
        assert db_path.endswith(".db")
        assert Path(db_path).parent.exists()

    def test_setup_plan_with_task_creates_plan_and_task(self, db_path):
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path)
            assert plan_id is not None
            assert len(task_ids) == 1
            # Verify in DB
            plan = await db.execute_one("SELECT id, status FROM plans WHERE id = ?", (plan_id,))
            assert plan["status"] == "tasks_ready"
            task = await db.execute_one("SELECT id, status FROM tasks WHERE id = ?", (task_ids[0],))
            assert task["status"] == "pending"

        anyio.run(run)

    def test_setup_review_cycles_inserts_reviews(self, db_path):
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path)
            tid = task_ids[0]
            from tests.test_features import _setup_review_cycles

            await _setup_review_cycles(db, tid, 3)
            rows = await db.execute(
                "SELECT COUNT(*) as cnt FROM reviews WHERE task_id = ?", (tid,),
            )
            assert rows[0]["cnt"] == 3

        anyio.run(run)

    def test_call_handler_works(self, db_path):
        async def run():
            db = Database(db_path)
            await db.initialize()
            plan_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES (?, 'Test', 'tasks_ready')",
                (plan_id,),
            )
            result = await _call_handler(db, handle_task_tool, "task.create", {
                "plan_id": plan_id,
                "title": "Handler Test",
            })
            assert result["status"] == "pending"

        anyio.run(run)


# ── Review cycle helper ─────────────────────────────────────────


async def _setup_review_cycles(db: Database, task_id: str, count: int):
    """Directly insert `count` review records with changes_requested status."""
    for i in range(count):
        rid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO reviews (id, task_id, status, created_at) "
            "VALUES (?, ?, 'changes_requested', datetime('now', ?))",
            (rid, task_id, f"-{count - i} minutes"),
        )


# ── Task 2: TestSkillRestrictions (7.2) ─────────────────────────


class TestSkillRestrictions:
    """Restrictions enforcement in tool handlers (max_concurrent_tasks,
    cannot_approve_own_work, max_review_cycles).

    These tests call handlers directly so custom _restrictions can be passed
    without server interference.
    """

    # ── max_concurrent_tasks ────────────────────────────────────

    def test_max_concurrent_tasks_blocks(self, db_path):
        """max_concurrent_tasks=1 → first claim ok, second blocked."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path, extra_tasks=1)
            t1, t2 = task_ids[0], task_ids[1]

            r1 = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t1,
                "_agent_role": "developer",
                "_restrictions": {"max_concurrent_tasks": 1},
            })
            assert r1["status"] == "in_progress"

            r2 = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t2,
                "_agent_role": "developer",
                "_restrictions": {"max_concurrent_tasks": 1},
            })
            assert r2["error"] == "max_concurrent_tasks_reached"

        anyio.run(run)

    def test_max_concurrent_tasks_allows_within_limit(self, db_path):
        """max_concurrent_tasks=2 → first and second claim both succeed."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path, extra_tasks=1)
            t1, t2 = task_ids[0], task_ids[1]

            r1 = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t1,
                "_agent_role": "developer",
                "_restrictions": {"max_concurrent_tasks": 2},
            })
            assert r1["status"] == "in_progress"

            r2 = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t2,
                "_agent_role": "developer",
                "_restrictions": {"max_concurrent_tasks": 2},
            })
            assert r2["status"] == "in_progress"

        anyio.run(run)

    def test_max_concurrent_tasks_per_agent(self, db_path):
        """Restriction is per-agent: agent A blocked, agent B succeeds."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path, extra_tasks=1)
            t1, t2 = task_ids[0], task_ids[1]

            # Agent A claims first task → success
            r_a1 = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t1,
                "_agent_role": "agent-a",
                "_restrictions": {"max_concurrent_tasks": 1},
            })
            assert r_a1["status"] == "in_progress"

            # Agent A tries second task → blocked
            r_a2 = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t2,
                "_agent_role": "agent-a",
                "_restrictions": {"max_concurrent_tasks": 1},
            })
            assert r_a2["error"] == "max_concurrent_tasks_reached"

            # Same task B still pending, agent B claims it → success
            r_b = await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": t2,
                "_agent_role": "agent-b",
                "_restrictions": {"max_concurrent_tasks": 1},
            })
            assert r_b["status"] == "in_progress"
            assert r_b["assignee"] == "agent-b"

        anyio.run(run)

    # ── cannot_approve_own_work ─────────────────────────────────

    def test_cannot_approve_own_work_blocks(self, db_path):
        """Developer cannot approve own task."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path)
            tid = task_ids[0]

            # Claim as developer
            await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": tid, "_agent_role": "developer",
            })

            # Submit work to move to 'review' status
            await _call_handler(db, handle_task_tool, "task.submit_work", {
                "task_id": tid, "summary": "Done",
            })

            # Approve with same role → blocked
            r = await _call_handler(db, handle_review_tool, "review.approve", {
                "task_id": tid,
                "_agent_role": "developer",
                "_restrictions": {"cannot_approve_own_work": True},
            })
            assert r["error"] == "cannot_approve_own_work"

        anyio.run(run)

    def test_cannot_approve_own_work_allows_cross_role(self, db_path):
        """Architect can approve developer's task."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path)
            tid = task_ids[0]

            # Claim as developer
            await _call_handler(db, handle_task_tool, "task.claim", {
                "task_id": tid, "_agent_role": "developer",
            })

            # Submit work
            await _call_handler(db, handle_task_tool, "task.submit_work", {
                "task_id": tid, "summary": "Done",
            })

            # Approve with different role → success
            r = await _call_handler(db, handle_review_tool, "review.approve", {
                "task_id": tid,
                "_agent_role": "architect",
                "_restrictions": {"cannot_approve_own_work": True},
            })
            assert r["status"] == "approved"

        anyio.run(run)

    # ── max_review_cycles ───────────────────────────────────────

    def test_max_review_cycles_blocks_after_3(self, db_path):
        """After 3 changes_requested reviews, review.start is blocked."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path)
            tid = task_ids[0]

            # Task must be in 'review' status for review.start
            await db.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (tid,))

            # Insert 3 changes_requested reviews (hits MAX_REVIEW_CYCLES = 3)
            await _setup_review_cycles(db, tid, 3)

            r = await _call_handler(db, handle_review_tool, "review.start", {
                "task_id": tid,
            })
            assert r["error"] == "max_review_cycles_reached"

        anyio.run(run)

    def test_max_review_cycles_allows_within_limit(self, db_path):
        """After 2 changes_requested reviews, a 3rd review.start succeeds."""
        async def run():
            db, plan_id, task_ids = await _setup_plan_with_task(db_path)
            tid = task_ids[0]

            await db.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (tid,))

            # Insert 2 changes_requested reviews (within limit)
            await _setup_review_cycles(db, tid, 2)

            r = await _call_handler(db, handle_review_tool, "review.start", {
                "task_id": tid,
            })
            assert r["status"] == "in_review"

        anyio.run(run)


# ── Task 3: TestTaskDependencies (7.3) ─────────────────────────


class TestTaskDependencies:
    """Tests for depends_on — task creation and claim gating.

    Creation uses the full MCP server pipeline (validates tool flow).
    Claims use _call_handler because task.claim is not in the architect role's
    allowed_tools.
    """

    def test_create_task_with_depends_on(self, db_path):
        """Creating a task with depends_on succeeds."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Dep Test"})
            t1 = await _call(server, "task.create", {"plan_id": plan["plan_id"], "title": "Task 1"})

            r = await _call(server, "task.create", {
                "plan_id": plan["plan_id"],
                "title": "Dep Task",
                "depends_on": t1["task_id"],
            })
            assert r["status"] == "pending"

        anyio.run(run)

    def test_create_task_invalid_depends_on(self, db_path):
        """Creating a task with a non-existent dependency → error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Invalid Dep"})
            r = await _call(server, "task.create", {
                "plan_id": plan["plan_id"],
                "title": "Bad Dep",
                "depends_on": "nonexistent-task-id",
            })
            assert "error" in r
            assert "not found" in r["error"]

        anyio.run(run)

    def test_claim_blocked_by_unapproved_dependency(self, db_path):
        """Claiming a task whose dependency is not approved → error."""
        async def run():
            arch, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(arch, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            dev, init2 = create_server(db_path=db_path, agent_id="test-dev")
            await init2()
            await _call(dev, "agent.heartbeat", {
                "agent_id": "test-dev", "role": "developer",
            })

            plan = await _call(arch, "plan.create", {"title": "Dep Test"})
            t1 = await _call(arch, "task.create", {"plan_id": plan["plan_id"], "title": "Task 1"})
            t2 = await _call(arch, "task.create", {
                "plan_id": plan["plan_id"], "title": "Depends on T1",
                "depends_on": t1["task_id"],
            })

            r = await _call(dev, "task.claim", {
                "task_id": t2["task_id"], "agent": "developer",
            })
            assert r["error"] == "dependency_not_approved"

        anyio.run(run)

    def test_claim_allowed_when_dependency_approved(self, db_path):
        """Claiming a task whose dependency is approved → success."""
        async def run():
            arch, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(arch, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })
            dev, init2 = create_server(db_path=db_path, agent_id="test-dev")
            await init2()
            await _call(dev, "agent.heartbeat", {
                "agent_id": "test-dev", "role": "developer",
            })

            plan = await _call(arch, "plan.create", {"title": "Dep Test"})
            t1 = await _call(arch, "task.create", {"plan_id": plan["plan_id"], "title": "Dependency"})
            t2 = await _call(arch, "task.create", {
                "plan_id": plan["plan_id"], "title": "Depends on T1",
                "depends_on": t1["task_id"],
            })

            # Directly approve t1
            db = Database(db_path)
            await db.initialize()
            await db.execute("UPDATE tasks SET status = 'approved' WHERE id = ?", (t1["task_id"],))

            r = await _call(dev, "task.claim", {
                "task_id": t2["task_id"], "agent": "developer",
            })
            assert r["status"] == "in_progress"

        anyio.run(run)

    def test_circular_dependency_detected(self, db_path):
        """Claiming a task in a circular chain A→B→A → error.

        Task B must be approved first so the dependency check passes
        and the cycle detection runs.
        """
        async def run():
            db = Database(db_path)
            await db.initialize()
            plan_id = str(uuid.uuid4())
            task_a = str(uuid.uuid4())
            task_b = str(uuid.uuid4())

            await db.execute(
                "INSERT INTO plans (id, title, status) VALUES (?, 'Circular Test', 'tasks_ready')",
                (plan_id,),
            )
            await db.execute(
                "INSERT INTO tasks (id, plan_id, title, status, depends_on) "
                "VALUES (?, ?, 'Task A', 'pending', ?)",
                (task_a, plan_id, task_b),
            )
            await db.execute(
                "INSERT INTO tasks (id, plan_id, title, status, depends_on) "
                "VALUES (?, ?, 'Task B', 'pending', ?)",
                (task_b, plan_id, task_a),
            )

            # Approve B so the dependency check passes and cycle check runs
            await db.execute("UPDATE tasks SET status = 'approved' WHERE id = ?", (task_b,))

            # Claim via a developer server
            dev, init = create_server(db_path=db_path, agent_id="test-circ-dev")
            await init()
            await _call(dev, "agent.heartbeat", {
                "agent_id": "test-circ-dev", "role": "developer",
            })
            r = await _call(dev, "task.claim", {"task_id": task_a, "agent": "developer"})
            assert r["error"] == "circular_dependency"

        anyio.run(run)


# ── Task 4: TestPlanCRUD (7.4) ─────────────────────────────────


class TestPlanCRUD:
    """Tests for plan.update, plan.archive, plan delete."""

    def test_plan_update_transition(self, db_path):
        """Valid plan transition (planning → tasks_ready) succeeds."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Update Test"})
            r = await _call(server, "plan.update", {
                "plan_id": plan["plan_id"], "status": "tasks_ready",
            })
            assert r["status"] == "tasks_ready"

        anyio.run(run)

    def test_plan_update_invalid_transition(self, db_path):
        """Invalid transition (planning → completed) → error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Invalid"})
            r = await _call(server, "plan.update", {
                "plan_id": plan["plan_id"], "status": "completed",
            })
            assert "error" in r

        anyio.run(run)

    def test_plan_archive_soft_delete(self, db_path):
        """Archive is a soft delete — plan.get still returns it."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Archive Test"})
            pid = plan["plan_id"]

            # Transition to a status that can be archived
            await _call(server, "plan.update", {
                "plan_id": pid, "status": "tasks_ready",
            })

            # Archive (now available in architect allowed_tools)
            r = await _call(server, "plan.archive", {"plan_id": pid})
            assert r["status"] == "archived"

            # plan.get still returns the archived plan
            r = await _call(server, "plan.get", {"plan_id": pid})
            assert r["plan_id"] == pid
            assert r["status"] == "archived"

        anyio.run(run)

    def test_plan_archive_on_completed_fails(self, db_path):
        """Archiving a completed plan → error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Completed"})
            pid = plan["plan_id"]

            # Walk through valid transitions to completed
            await _call(server, "plan.update", {"plan_id": pid, "status": "tasks_ready"})
            await _call(server, "plan.update", {"plan_id": pid, "status": "in_progress"})
            await _call(server, "plan.update", {"plan_id": pid, "status": "completed"})

            # Archive (now available in architect allowed_tools)
            r = await _call(server, "plan.archive", {"plan_id": pid})
            assert "error" in r

        anyio.run(run)

    def test_plan_delete_cascades(self, db_path):
        """Deleting a plan removes its tasks too."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Delete Cascade"})
            pid = plan["plan_id"]

            # Create a task in this plan
            task = await _call(server, "task.create", {"plan_id": pid, "title": "Task"})
            tid = task["task_id"]

            # Delete (now available in architect allowed_tools)
            r = await _call(server, "plan.delete", {"plan_id": pid})
            assert r["deleted"] is True

            # Plan gone
            r = await _call(server, "plan.get", {"plan_id": pid})
            assert "error" in r

            # Task gone
            r = await _call(server, "task.get", {"task_id": tid})
            assert "error" in r

        anyio.run(run)

    def test_plan_delete_nonexistent(self, db_path):
        """Deleting a non-existent plan → error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            r = await _call(server, "plan.delete", {"plan_id": "nonexistent-plan"})
            assert "error" in r

        anyio.run(run)


# ── Task 5: TestTaskCRUD (7.4) ─────────────────────────────────


class TestTaskCRUD:
    """Tests for task.update and task.delete."""

    # ── task.update ─────────────────────────────────────────────

    def test_task_update_title_and_description(self, db_path):
        """Updating a pending task's title/description succeeds."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "CRUD Test"})
            task = await _call(server, "task.create", {
                "plan_id": plan["plan_id"], "title": "Task",
            })
            tid = task["task_id"]

            # Update (now available in architect allowed_tools)
            r = await _call(server, "task.update", {
                "task_id": tid,
                "title": "Updated Title",
                "description": "Updated description",
            })
            assert r["task_id"] == tid
            assert r["title"] == "Updated Title"
            assert r["description"] == "Updated description"

        anyio.run(run)

    def test_task_update_blocks_for_approved(self, db_path):
        """Updating an approved task → error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Block Update"})
            task = await _call(server, "task.create", {
                "plan_id": plan["plan_id"], "title": "Approved Task",
            })
            tid = task["task_id"]

            # Set to approved via direct DB
            db = Database(db_path)
            await db.initialize()
            await db.execute("UPDATE tasks SET status = 'approved' WHERE id = ?", (tid,))

            r = await _call(server, "task.update", {
                "task_id": tid,
                "title": "Should Fail",
            })
            assert "error" in r

        anyio.run(run)

    # ── task.delete ─────────────────────────────────────────────

    def test_task_delete_pending(self, db_path):
        """Deleting a pending task succeeds."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Delete Task"})
            task = await _call(server, "task.create", {
                "plan_id": plan["plan_id"], "title": "To Delete",
            })
            tid = task["task_id"]

            # Delete (now available in architect allowed_tools)
            r = await _call(server, "task.delete", {"task_id": tid})
            assert r["deleted"] is True

            # Verify gone
            r = await _call(server, "task.get", {"task_id": tid})
            assert "error" in r

        anyio.run(run)

    def test_task_delete_blocks_for_approved(self, db_path):
        """Deleting an approved task → error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()
            await _call(server, "agent.heartbeat", {
                "agent_id": "test-arch", "role": "architect",
            })

            plan = await _call(server, "plan.create", {"title": "Block Delete"})
            task = await _call(server, "task.create", {
                "plan_id": plan["plan_id"], "title": "Approved Task",
            })
            tid = task["task_id"]

            # Set to approved via direct DB
            db = Database(db_path)
            await db.initialize()
            await db.execute("UPDATE tasks SET status = 'approved' WHERE id = ?", (tid,))

            r = await _call(server, "task.delete", {"task_id": tid})
            assert "error" in r

        anyio.run(run)

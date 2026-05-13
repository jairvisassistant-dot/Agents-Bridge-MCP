"""SQLite database layer — state persistence for Agent Bridge.

Uses sync sqlite3 wrapped in anyio.to_thread.run_sync to avoid
blocking the event loop.

Concurrency: SQLite WAL mode handles concurrent reads naturally.
Writes are serialized by SQLite internally (no FileLock needed).
Key operations like task.claim use a lightweight flag-based lock
stored in SQLite itself (atomic UPDATE ... WHERE status='pending').

Dry-run mode: when _dry_run=True, write operations (INSERT/UPDATE/DELETE/
ALTER/CREATE/DROP) are logged and skipped. The connection uses :memory:
so no persistent state is modified. Reads are allowed against the
in-memory schema.
"""

import logging
import sqlite3

import anyio

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3  # bump this when adding migrations below

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP")


def _is_write(sql: str) -> bool:
    """Return True if the SQL statement is a write operation."""
    stripped = sql.strip().upper()
    for prefix in _WRITE_PREFIXES:
        if stripped.startswith(prefix):
            return True
    return False

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS _meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'offline',
    last_seen TEXT,
    connected_since TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idle',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assignee TEXT,
    submission_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    reviewer TEXT NOT NULL DEFAULT 'architect',
    status TEXT NOT NULL DEFAULT 'pending',
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT,
    sender TEXT NOT NULL,
    target TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _run_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Run incremental migrations between schema versions."""
    if from_version < 2:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'default',
                status TEXT NOT NULL DEFAULT 'offline',
                last_seen TEXT,
                connected_since TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        logger.info("Migration v1→v2: added agents table")

    if from_version < 3:
        conn.execute("ALTER TABLE tasks ADD COLUMN diff_text TEXT DEFAULT ''")
        logger.info("Migration v2→v3: added diff_text to tasks")


class Database:
    """Manages shared SQLite state with WAL mode.

    All DB operations run via anyio.to_thread.run_sync to keep the
    event loop responsive.

    Concurrency is handled by SQLite's WAL mode + atomic UPDATE with
    WHERE conditions. No external file locks needed.

    Dry-run mode: when dry_run=True, write operations are logged and
    skipped. The connection uses an in-memory SQLite DB so no
    persistent state is modified. Reads are allowed against the
    in-memory schema (initialised on first connect).
    """

    def __init__(self, db_path: str = "bridge.db", dry_run: bool = False):
        self.db_path = db_path
        self._dry_run = dry_run
        self._memory_conn: sqlite3.Connection | None = None

    # ── Sync helpers (run in thread via anyio) ─────────────────

    def _connect(self) -> sqlite3.Connection:
        if self._dry_run:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA journal_mode=WAL;")
                self._memory_conn.execute("PRAGMA foreign_keys=ON;")
                self._memory_conn.execute("PRAGMA busy_timeout=5000;")
            return self._memory_conn

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")  # 5s wait on lock
        return conn

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

            cursor = conn.execute(
                "SELECT value FROM _meta WHERE key = 'schema_version'"
            )
            row = cursor.fetchone()
            current_version = int(row[0]) if row else 0

            if current_version < SCHEMA_VERSION:
                logger.info(
                    "Migrating schema from v%d to v%d",
                    current_version,
                    SCHEMA_VERSION,
                )
                _run_migrations(conn, current_version)
                conn.execute(
                    "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                conn.commit()
        finally:
            if not self._dry_run:
                conn.close()

    def _execute(
        self, sql: str, params: tuple = ()
    ) -> list[sqlite3.Row]:
        if self._dry_run and _is_write(sql):
            logger.info("[DRY-RUN] SQL: %s | params=%s", sql, params)
            return []
        conn = self._connect()
        try:
            cursor = conn.execute(sql, params)
            if not self._dry_run:
                conn.commit()
            return cursor.fetchall()
        finally:
            if not self._dry_run:
                conn.close()

    def _execute_one(
        self, sql: str, params: tuple = ()
    ) -> sqlite3.Row | None:
        if self._dry_run and _is_write(sql):
            logger.info("[DRY-RUN] SQL: %s | params=%s", sql, params)
            return None
        rows = self._execute(sql, params)
        return rows[0] if rows else None

    def _execute_write(
        self, sql: str, params: tuple = ()
    ) -> int:
        if self._dry_run and _is_write(sql):
            logger.info("[DRY-RUN] SQL: %s | params=%s", sql, params)
            return 0
        conn = self._connect()
        try:
            cursor = conn.execute(sql, params)
            if not self._dry_run:
                conn.commit()
            return cursor.rowcount
        finally:
            if not self._dry_run:
                conn.close()

    # ── Async public API ───────────────────────────────────────

    async def initialize(self) -> None:
        """Create schema tables if they don't exist."""
        await anyio.to_thread.run_sync(self._initialize)
        mode = "dry-run (:memory:)" if self._dry_run else self.db_path
        logger.info("Database initialized at %s", mode)

    async def execute(
        self, sql: str, params: tuple = ()
    ) -> list[sqlite3.Row]:
        """Execute SQL and return all rows (for SELECT)."""
        return await anyio.to_thread.run_sync(self._execute, sql, params)

    async def execute_one(
        self, sql: str, params: tuple = ()
    ) -> sqlite3.Row | None:
        """Execute SQL and return first row or None."""
        return await anyio.to_thread.run_sync(self._execute_one, sql, params)

    async def execute_write(
        self, sql: str, params: tuple = ()
    ) -> int:
        """Execute an UPDATE/INSERT and return the number of affected rows.

        Use this for atomic conditional updates:
          await db.execute_write(
              \"UPDATE tasks SET status='x' WHERE id=? AND status='pending'\",
              (task_id,)
          )
        Returns rowcount (1 if update succeeded, 0 if condition failed).
        """
        return await anyio.to_thread.run_sync(self._execute_write, sql, params)

    # ── Reset ──────────────────────────────────────────────────

    async def reset(self) -> None:
        """Drop all tables and recreate the schema from scratch."""
        def _reset():
            conn = self._connect()
            try:
                conn.executescript("""
                    DROP TABLE IF EXISTS reviews;
                    DROP TABLE IF EXISTS tasks;
                    DROP TABLE IF EXISTS plans;
                    DROP TABLE IF EXISTS messages;
                    DROP TABLE IF EXISTS threads;
                    DROP TABLE IF EXISTS agents;
                    DROP TABLE IF EXISTS _meta;
                """)
                conn.commit()
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                conn.commit()
                logger.info("Database reset complete — all data cleared")
            finally:
                if not self._dry_run:
                    conn.close()
        await anyio.to_thread.run_sync(_reset)

    # ── Export / Import ─────────────────────────────────────────

    async def get_plan_export(self, plan_id: str) -> dict | None:
        """Export a plan with all its tasks and reviews as a single dict."""
        def _export():
            conn = self._connect()
            try:
                plan = conn.execute(
                    "SELECT * FROM plans WHERE id = ?", (plan_id,)
                ).fetchone()
                if plan is None:
                    return None

                tasks = conn.execute(
                    "SELECT * FROM tasks WHERE plan_id = ? ORDER BY created_at",
                    (plan_id,),
                ).fetchall()

                task_ids = [t["id"] for t in tasks]
                reviews: list[sqlite3.Row] = []
                if task_ids:
                    placeholders = ",".join("?" for _ in task_ids)
                    reviews = conn.execute(
                        f"SELECT * FROM reviews WHERE task_id IN ({placeholders}) ORDER BY created_at",
                        task_ids,
                    ).fetchall()

                return {
                    "plan": dict(plan),
                    "tasks": [dict(t) for t in tasks],
                    "reviews": [dict(r) for r in reviews],
                }
            finally:
                if not self._dry_run:
                    conn.close()
        return await anyio.to_thread.run_sync(_export)

    async def import_plan(self, plan_data: dict) -> dict:
        """Import a plan with its tasks and reviews (INSERT OR IGNORE)."""
        def _import():
            conn = self._connect()
            try:
                plan = plan_data["plan"]
                conn.execute(
                    """INSERT OR IGNORE INTO plans
                       (id, title, description, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        plan["id"],
                        plan.get("title", ""),
                        plan.get("description", ""),
                        plan.get("status", "idle"),
                        plan.get("created_at"),
                        plan.get("updated_at"),
                    ),
                )

                tasks_count = 0
                for task in plan_data.get("tasks", []):
                    conn.execute(
                        """INSERT OR IGNORE INTO tasks
                           (id, plan_id, title, description, status, assignee,
                            submission_summary, diff_text, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            task["id"],
                            plan["id"],
                            task.get("title", ""),
                            task.get("description", ""),
                            task.get("status", "pending"),
                            task.get("assignee"),
                            task.get("submission_summary"),
                            task.get("diff_text", ""),
                            task.get("created_at"),
                            task.get("updated_at"),
                        ),
                    )
                    tasks_count += 1

                for review in plan_data.get("reviews", []):
                    conn.execute(
                        """INSERT OR IGNORE INTO reviews
                           (id, task_id, reviewer, status, comment, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            review["id"],
                            review["task_id"],
                            review.get("reviewer", "architect"),
                            review.get("status", "pending"),
                            review.get("comment"),
                            review.get("created_at"),
                        ),
                    )

                conn.commit()
                return {"plan_id": plan["id"], "tasks_count": tasks_count}
            finally:
                if not self._dry_run:
                    conn.close()
        return await anyio.to_thread.run_sync(_import)

    # ── Stale agent detection and task reassignment ──────────────

    async def get_stale_agents(self, threshold_minutes: int = 5) -> list[sqlite3.Row]:
        """Return agents whose last_seen is older than threshold and not yet offline."""
        def _query():
            conn = self._connect()
            try:
                return conn.execute(
                    """SELECT agent_id, status, last_seen FROM agents
                       WHERE status != 'offline'
                       AND last_seen < datetime('now', ?)""",
                    (f'-{threshold_minutes} minutes',),
                ).fetchall()
            finally:
                conn.close()
        return await anyio.to_thread.run_sync(_query)

    async def reassign_tasks_from_agent(self, agent_id: str) -> int:
        """Reassign in_progress tasks from a stale agent back to pending.
        
        Returns the number of tasks reassigned.
        """
        def _reassign():
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """UPDATE tasks SET status = 'pending', assignee = NULL,
                       updated_at = datetime('now')
                       WHERE assignee = ? AND status = 'in_progress'""",
                    (agent_id,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()
        return await anyio.to_thread.run_sync(_reassign)

    async def mark_agent_offline(self, agent_id: str) -> None:
        """Mark an agent as offline."""
        def _mark():
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE agents SET status = 'offline' WHERE agent_id = ?",
                    (agent_id,),
                )
                conn.commit()
            finally:
                conn.close()
        await anyio.to_thread.run_sync(_mark)

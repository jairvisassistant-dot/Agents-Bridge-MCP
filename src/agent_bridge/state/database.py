"""SQLite database layer — state persistence for Agent Bridge.

Uses sync sqlite3 wrapped in anyio.to_thread.run_sync to avoid
blocking the event loop.

Concurrency: A single persistent connection is used for normal mode,
serialized via threading.RLock. WAL mode + BEGIN IMMEDIATE on writes
ensures write-ahead locking without deadlocks.

Dry-run mode: when _dry_run=True, write operations are logged and
skipped. Each operation gets a fresh :memory: connection so no
persistent state is modified.
"""

import logging
import sqlite3
import threading
import uuid

import anyio

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 7  # bump this when adding migrations below

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP")


def _is_write(sql: str) -> bool:
    """Return True if the SQL statement is a write operation."""
    stripped = sql.strip().upper()
    return any(stripped.startswith(prefix) for prefix in _WRITE_PREFIXES)


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
    msg_type TEXT NOT NULL DEFAULT 'chat',
    priority TEXT NOT NULL DEFAULT 'normal',
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ping_requests (
    id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    pong_at TEXT,
    latency_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
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

    if from_version < 4:
        conn.execute("ALTER TABLE messages ADD COLUMN turn_number INTEGER")
        conn.execute("ALTER TABLE threads ADD COLUMN participants TEXT NOT NULL DEFAULT '[]'")
        conn.execute("ALTER TABLE threads ADD COLUMN current_turn TEXT")
        conn.execute("ALTER TABLE threads ADD COLUMN last_activity_at TEXT")
        logger.info("Migration v3→v4: added discussion fields to threads and messages")

    if from_version < 5:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ping_requests (
                id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                pong_at TEXT,
                latency_ms INTEGER,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        logger.info("Migration v4→v5: added ping_requests table")

    if from_version < 6:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        if "msg_type" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'chat'")
        if "priority" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
        if "read" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN read INTEGER NOT NULL DEFAULT 0")
        logger.info("Migration v5→v6: added msg_type, priority, read to messages")

    if from_version < 7:
        conn.execute("ALTER TABLE tasks ADD COLUMN depends_on TEXT DEFAULT NULL")
        logger.info("Migration v6→v7: added depends_on to tasks (nullable FK to tasks.id)")


def _run_reverse_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Run reverse migrations to downgrade schema version."""
    if from_version >= 7:
        conn.execute("ALTER TABLE tasks DROP COLUMN depends_on")
        logger.info("Reverse migration v7→v6: dropped depends_on from tasks")

    if from_version >= 6:
        conn.executescript("""
            CREATE TABLE messages_v5 AS SELECT id, thread_id, sender, target, text, created_at FROM messages;
            DROP TABLE messages;
            ALTER TABLE messages_v5 RENAME TO messages;
        """)
        logger.info("Reverse migration v6→v5: reverted msg_type, priority, read")

    if from_version >= 5:
        conn.execute("DROP TABLE IF EXISTS ping_requests")
        logger.info("Reverse migration v5→v4: dropped ping_requests")

    if from_version >= 4:
        conn.executescript("""
            CREATE TABLE messages_v3 AS SELECT id, thread_id, sender, target, text, created_at FROM messages;
            DROP TABLE messages;
            ALTER TABLE messages_v3 RENAME TO messages;
            CREATE TABLE threads_v3 AS SELECT id, title, status, created_at FROM threads;
            DROP TABLE threads;
            ALTER TABLE threads_v3 RENAME TO threads;
        """)
        logger.info("Reverse migration v4→v3: reverted discussion fields")

    if from_version >= 3:
        conn.execute("ALTER TABLE tasks DROP COLUMN diff_text")
        logger.info("Reverse migration v3→v2: dropped diff_text")


class Database:
    """Manages shared SQLite state with WAL mode and singleton connection.

    A single persistent connection (self._conn) is created on first use and
    reused for the lifecycle. All access is serialized via threading.RLock
    to ensure thread safety when used with anyio.to_thread.run_sync.

    Writes use BEGIN IMMEDIATE to acquire a write lock upfront, preventing
    deadlocks under concurrent access.

    Dry-run mode: when dry_run=True, write operations are logged and
    skipped. Each operation gets a fresh :memory: connection, so no
    persistent state is modified.
    """

    def __init__(self, db_path: str = "bridge.db", dry_run: bool = False):
        self.db_path = db_path
        self._dry_run = dry_run
        self._conn: sqlite3.Connection | None = None
        self._dry_run_conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    # ── Sync helpers (run in thread via anyio) ─────────────────

    def _connect(self) -> sqlite3.Connection:
        """Return a SQLite connection.

        Normal mode: returns the singleton ``self._conn``, creating it
        on the first call and applying PRAGMAs once.

        Dry-run mode: returns a fresh ``:memory:`` connection each time
        (never cached) so the object is not shared across threads.
        """
        if self._dry_run:
            if self._dry_run_conn is None:
                self._dry_run_conn = sqlite3.connect(":memory:")
                self._dry_run_conn.row_factory = sqlite3.Row
                self._dry_run_conn.execute("PRAGMA journal_mode=WAL;")
                self._dry_run_conn.execute("PRAGMA foreign_keys=ON;")
                self._dry_run_conn.execute("PRAGMA busy_timeout=5000;")
            return self._dry_run_conn

        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
        return self._conn

    def _initialize(self) -> None:
        """Create schema tables and run pending migrations.

        Wrapped in BEGIN IMMEDIATE + lock so only one caller runs
        migrations, preventing race conditions on concurrent startup.
        """
        with self._lock:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            conn.executescript(SCHEMA_SQL)

            cursor = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
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
            elif current_version > SCHEMA_VERSION:
                logger.info(
                    "Reverse-migrating schema from v%d to v%d",
                    current_version,
                    SCHEMA_VERSION,
                )
                _run_reverse_migrations(conn, current_version)
                conn.execute(
                    "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        if self._dry_run and _is_write(sql):
            logger.info("[DRY-RUN] SQL: %s | params=%s", sql, params)
            return []
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(sql, params)
            if not self._dry_run:
                conn.commit()
            return cursor.fetchall()

    def _execute_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        if self._dry_run and _is_write(sql):
            logger.info("[DRY-RUN] SQL: %s | params=%s", sql, params)
            return None
        rows = self._execute(sql, params)
        return rows[0] if rows else None

    def _execute_write(self, sql: str, params: tuple = ()) -> int:
        if self._dry_run and _is_write(sql):
            logger.info("[DRY-RUN] SQL: %s | params=%s", sql, params)
            return 0
        with self._lock:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount

    # ── Async public API ───────────────────────────────────────

    async def initialize(self) -> None:
        """Create schema tables if they don't exist."""
        await anyio.to_thread.run_sync(self._initialize)
        mode = "dry-run (:memory:)" if self._dry_run else self.db_path
        logger.info("Database initialized at %s", mode)

    async def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute SQL and return all rows (for SELECT)."""
        return await anyio.to_thread.run_sync(self._execute, sql, params)

    async def execute_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Execute SQL and return first row or None."""
        return await anyio.to_thread.run_sync(self._execute_one, sql, params)

    async def execute_write(self, sql: str, params: tuple = ()) -> int:
        """Execute an UPDATE/INSERT and return the number of affected rows.

        Use this for atomic conditional updates:
          await db.execute_write(
              "UPDATE tasks SET status='x' WHERE id=? AND status='pending'",
              (task_id,)
          )
        Returns rowcount (1 if update succeeded, 0 if condition failed).
        """
        return await anyio.to_thread.run_sync(self._execute_write, sql, params)

    async def with_transaction(self, func):
        """Run func(conn) atomically inside BEGIN IMMEDIATE + COMMIT.

        The callback receives a sync ``sqlite3.Connection`` and runs in a
        worker thread.  If it returns, the transaction is committed; if it
        raises, the transaction is rolled back and the exception propagates.

        Usage::

            result = await db.with_transaction(lambda conn: _sync_fn(conn, arg))

        This is the ONLY way to guarantee that multiple writes are visible
        as a single atomic unit — both UPDATE (turn claim) and INSERT
        (message) happen before any other writer can observe the change.
        """

        def _run():
            if self._dry_run:
                logger.info("[DRY-RUN] with_transaction skipped")
                return None
            with self._lock:
                conn = self._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    result = func(conn)
                    conn.commit()
                    return result
                except Exception:
                    conn.rollback()
                    raise

        return await anyio.to_thread.run_sync(_run)

    async def close(self) -> None:
        """Close the persistent connection and release resources."""

        def _close():
            with self._lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None

        await anyio.to_thread.run_sync(_close)

    async def resolve_thread_atomic(self, thread_id: str, system_text: str) -> bool:
        """Atomically resolve a thread and insert a system message.

        Uses ``with_transaction`` so that both the status UPDATE and the
        message INSERT commit (or roll back) together.  Returns ``True``
        if this call performed the resolution, ``False`` if the thread
        was already resolved (by a concurrent caller or a background
        timeout).
        """

        def _resolve(conn):
            cur = conn.execute(
                "UPDATE threads SET status = 'resolved' WHERE id = ? AND status = 'open'",
                (thread_id,),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "INSERT INTO messages (id, thread_id, sender, text) VALUES (?, ?, 'system', ?)",
                (str(uuid.uuid4()), thread_id, system_text),
            )
            return True

        return await self.with_transaction(_resolve)

    # ── Reset ──────────────────────────────────────────────────

    async def reset(self) -> None:
        """Drop all tables and recreate the schema from scratch."""

        def _reset():
            with self._lock:
                conn = self._connect()
                conn.execute("BEGIN IMMEDIATE")
                conn.executescript("""
                    DROP TABLE IF EXISTS reviews;
                    DROP TABLE IF EXISTS tasks;
                    DROP TABLE IF EXISTS plans;
                    DROP TABLE IF EXISTS messages;
                    DROP TABLE IF EXISTS threads;
                    DROP TABLE IF EXISTS agents;
                    DROP TABLE IF EXISTS _meta;
                """)
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                conn.commit()
                logger.info("Database reset complete — all data cleared")

        await anyio.to_thread.run_sync(_reset)

    # ── Export / Import ─────────────────────────────────────────

    async def get_plan_export(self, plan_id: str) -> dict | None:
        """Export a plan with all its tasks and reviews as a single dict."""

        def _export():
            with self._lock:
                conn = self._connect()
                plan = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
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

        return await anyio.to_thread.run_sync(_export)

    async def import_plan(self, plan_data: dict) -> dict:
        """Import a plan with its tasks and reviews (INSERT OR IGNORE)."""

        def _import():
            with self._lock:
                conn = self._connect()
                conn.execute("BEGIN IMMEDIATE")
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

        return await anyio.to_thread.run_sync(_import)

    # ── Stale agent detection and task reassignment ──────────────

    async def get_stale_agents(self, threshold_minutes: int = 5) -> list[sqlite3.Row]:
        """Return agents whose last_seen is older than threshold and not yet offline."""

        def _query():
            with self._lock:
                conn = self._connect()
                return conn.execute(
                    """SELECT agent_id, status, last_seen FROM agents
                       WHERE status != 'offline'
                       AND last_seen < datetime('now', ?)""",
                    (f"-{threshold_minutes} minutes",),
                ).fetchall()

        return await anyio.to_thread.run_sync(_query)

    async def reassign_tasks_from_agent(self, agent_id: str) -> int:
        """Reassign in_progress tasks from a stale agent back to pending.

        Returns the number of tasks reassigned.
        """

        def _reassign():
            with self._lock:
                conn = self._connect()
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """UPDATE tasks SET status = 'pending', assignee = NULL,
                       updated_at = datetime('now')
                       WHERE assignee = ? AND status = 'in_progress'""",
                    (agent_id,),
                )
                conn.commit()
                return cursor.rowcount

        return await anyio.to_thread.run_sync(_reassign)

    async def mark_agent_offline(self, agent_id: str) -> None:
        """Mark an agent as offline."""

        def _mark():
            with self._lock:
                conn = self._connect()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE agents SET status = 'offline' WHERE agent_id = ?",
                    (agent_id,),
                )
                conn.commit()

        await anyio.to_thread.run_sync(_mark)

    async def notify_chat(self, text: str, sender: str = "system") -> None:
        """Post a system notification message to the general chat."""
        msg_id = str(uuid.uuid4())
        await self.execute_write(
            "INSERT INTO messages (id, sender, text) VALUES (?, ?, ?)",
            (msg_id, sender, text),
        )

    async def get_task_title(self, task_id: str) -> str | None:
        """Fetch the title of a task by ID."""
        row = await self.execute_one("SELECT title FROM tasks WHERE id = ?", (task_id,))
        return row["title"] if row else None

    # ── Ping / Pong ─────────────────────────────────────────────

    async def create_ping_request(self, sender_id: str, target_id: str) -> str:
        """Create a new ping request and return its ID."""
        ping_id = str(uuid.uuid4())
        await self.execute_write(
            "INSERT INTO ping_requests (id, sender_id, target_id) VALUES (?, ?, ?)",
            (ping_id, sender_id, target_id),
        )
        return ping_id

    async def record_pong(self, ping_id: str) -> int:
        """Record a pong response and return latency in milliseconds.

        Uses with_transaction so the UPDATE and SELECT happen atomically.
        Returns 0 if the ping_id is unknown or already resolved.
        """

        def _record(conn: sqlite3.Connection) -> int:
            conn.execute(
                """UPDATE ping_requests
                   SET pong_at = datetime('now'),
                       status = 'pong',
                       latency_ms = CAST(
                           (julianday('now') - julianday(sent_at)) * 86400000 AS INTEGER
                       )
                   WHERE id = ? AND status = 'pending'""",
                (ping_id,),
            )
            row = conn.execute(
                "SELECT latency_ms FROM ping_requests WHERE id = ?",
                (ping_id,),
            ).fetchone()
            return int(row["latency_ms"]) if row and row["latency_ms"] is not None else 0

        return await self.with_transaction(_record)

    async def get_ping_request(self, ping_id: str) -> dict | None:
        """Get a ping request by ID, or None if not found."""
        row = await self.execute_one("SELECT * FROM ping_requests WHERE id = ?", (ping_id,))
        return dict(row) if row else None

    # ── Enhanced messaging ───────────────────────────────────────

    async def mark_message_read(self, message_id: str) -> None:
        """Mark a specific message as read."""
        await self.execute_write(
            "UPDATE messages SET read = 1 WHERE id = ?",
            (message_id,),
        )

    async def send_system_notification(
        self,
        target: str,
        text: str,
        msg_type: str = "status_update",
        priority: str = "normal",
    ) -> None:
        """Send a system-generated typed notification to a specific agent."""
        msg_id = str(uuid.uuid4())
        await self.execute_write(
            "INSERT INTO messages (id, sender, target, text, msg_type, priority) VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, "system", target, text, msg_type, priority),
        )

    async def get_unread_count(self, target: str) -> int:
        """Get count of unread messages for a target agent."""
        row = await self.execute_one(
            "SELECT COUNT(*) AS cnt FROM messages WHERE target = ? AND read = 0",
            (target,),
        )
        return row["cnt"] if row else 0

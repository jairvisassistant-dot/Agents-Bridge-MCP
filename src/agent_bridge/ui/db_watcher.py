"""Background watcher that polls PRAGMA data_version to detect external DB changes.

Does NOT use watchfiles/inotify/honker — polling data_version costs ~1μs per call
and is trivially correct with WAL mode (50ms double-check on change).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from agent_bridge.state.database import Database

logger = logging.getLogger(__name__)


class DBWatcher:
    """Background watcher that polls PRAGMA data_version.

    Uses Textual's set_interval for scheduling (interval is set externally).
    Calls on_change callback when data_version changes.

    WAL-mode mitigation: when data_version changes, wait 50ms and re-check
    to avoid false positives from checkpoint flushes.
    """

    def __init__(
        self,
        db: Database,
        interval: float = 1.5,
        on_change: Callable[[int], Any] | None = None,
    ) -> None:
        self._db = db
        self.interval = interval
        self.on_change = on_change
        self._known_version: int = 0

    async def poll(self) -> int:
        """Poll PRAGMA data_version and call on_change if changed.

        Returns the current data_version.
        """
        version = await self._get_data_version()

        if version != self._known_version:
            # WAL-mitigation: wait 50ms and double-check
            await asyncio.sleep(0.05)
            version = await self._get_data_version()

            if self._known_version != 0 and self.on_change is not None:
                logger.debug("data_version changed: %d → %d", self._known_version, version)
                await self._call_on_change(version)

        self._known_version = version
        return version

    async def _get_data_version(self) -> int:
        """Query PRAGMA data_version from the database."""
        row = await self._db.execute_one("PRAGMA data_version")
        if row is None:
            return 0
        return int(row[0])

    async def _call_on_change(self, new_version: int) -> None:
        """Safely invoke the on_change callback."""
        if self.on_change is None:
            return
        try:
            result = self.on_change(new_version)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("DBWatcher on_change callback failed")

    async def force_refresh(self) -> None:
        """Force a poll that will trigger on_change even if version matches.

        Uses -1 as a sentinel that guarantees the version comparison succeeds
        and passes the first-poll guard (_known_version != 0).
        """
        self._known_version = -1
        await self.poll()

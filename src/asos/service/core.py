"""
CoreService: the orchestrator process that will eventually own the
Canvas sync worker, the notification engine, the scheduler, etc.

For this foundation milestone it deliberately does almost nothing: it
starts, sets up its DB engine/session factory, writes a heartbeat on
an interval, and shuts down cleanly on request. Every future subsystem
(Canvas sync, mastery scoring, notifications) will be registered here
as a "worker" the service ticks, rather than as a separate ad hoc
process — see PROJECT.md 'Concurrency model'.
"""

from __future__ import annotations

import logging
import threading
import time

from asos.config import get_database_url
from asos.credentials import CredentialVault
from asos.db.base import Base, make_engine, make_session_factory
from asos.db import models  # noqa: F401  (registers tables on Base.metadata)
from asos.facts.authority import seed_default_sources
from asos.service.health import write_heartbeat

logger = logging.getLogger("asos.service")

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15


class CoreService:
    def __init__(
        self,
        *,
        heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        credential_vault: CredentialVault | None = None,
    ) -> None:
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.credential_vault = credential_vault or CredentialVault()
        self._stop_event = threading.Event()

        self.engine = make_engine(get_database_url())
        Base.metadata.create_all(self.engine)  # safety net; Alembic is the source of truth for schema evolution
        self.session_factory = make_session_factory(self.engine)

        with self.session_factory() as session:
            seed_default_sources(session)

    def request_stop(self) -> None:
        logger.info("stop requested")
        self._stop_event.set()

    def run_forever(self) -> None:
        """Blocks, writing a heartbeat on an interval, until request_stop()
        is called (typically from a signal handler installed by the CLI)."""
        logger.info(
            "AsOS core service starting (heartbeat every %ss)", self.heartbeat_interval_seconds
        )
        write_heartbeat(status="running")
        try:
            while not self._stop_event.is_set():
                write_heartbeat(status="running")
                self._stop_event.wait(self.heartbeat_interval_seconds)
        finally:
            write_heartbeat(status="stopped")
            self.engine.dispose()
            logger.info("AsOS core service stopped cleanly")

    def run_one_tick(self) -> None:
        """Runs a single heartbeat write without entering the blocking loop.
        Used by tests and by `asos health --run-once`-style debug commands."""
        write_heartbeat(status="running")

"""
CoreService: the orchestrator process owning the heartbeat and the
periodic job scheduler (Canvas sync, ICS sync, notification scanning,
browser scraping -- whichever are configured).

CoreService itself knows nothing about Canvas, ICS, or browser
automation specifically -- it only knows how to run a named callable
on an interval. What actually gets registered lives in
asos.service.jobs, which decides which jobs make sense based on what
credentials exist. This keeps CoreService trivially testable (no
credential/network dependencies to fake) and keeps the "which jobs
exist" decision in one place rather than hardcoded into the scheduler.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import threading
from typing import Callable

from sqlalchemy.orm import Session

from asos.config import get_database_url
from asos.credentials import CredentialVault
from asos.db.base import Base, _now, make_engine, make_session_factory
from asos.db import models  # noqa: F401  (registers tables on Base.metadata)
from asos.facts.authority import seed_default_sources
from asos.service.health import write_heartbeat

logger = logging.getLogger("asos.service")

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15


@dataclasses.dataclass
class ScheduledJob:
    name: str
    interval_seconds: float
    func: Callable[[Session], None]
    last_run: datetime.datetime | None = None

    def is_due(self, now: datetime.datetime) -> bool:
        if self.last_run is None:
            return True
        return (now - self.last_run).total_seconds() >= self.interval_seconds


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
        self._jobs: list[ScheduledJob] = []

        self.engine = make_engine(get_database_url())
        Base.metadata.create_all(self.engine)  # safety net; Alembic is the source of truth for schema evolution
        self.session_factory = make_session_factory(self.engine)

        with self.session_factory() as session:
            seed_default_sources(session)

    def register_job(self, name: str, interval_seconds: float, func: Callable[[Session], None]) -> None:
        """Registers a job to run at most once every interval_seconds,
        checked on every heartbeat tick. A job that fails is logged and
        skipped -- it does not crash the service or block other jobs,
        and it's still considered "run" for backoff purposes (so a
        persistently failing job retries once per interval, not once
        per tick)."""
        self._jobs.append(ScheduledJob(name=name, interval_seconds=interval_seconds, func=func))
        logger.info("registered job '%s' (every %ss)", name, interval_seconds)

    def run_due_jobs(self) -> None:
        now = _now()
        for job in self._jobs:
            if not job.is_due(now):
                continue
            try:
                with self.session_factory() as session:
                    job.func(session)
                logger.info("job '%s' completed", job.name)
            except Exception:
                logger.exception("job '%s' failed", job.name)
            finally:
                job.last_run = now

    def request_stop(self) -> None:
        logger.info("stop requested")
        self._stop_event.set()

    def run_forever(self) -> None:
        """Blocks, writing a heartbeat and running any due jobs on each
        tick, until request_stop() is called (typically from a signal
        handler installed by the CLI)."""
        logger.info(
            "AsOS core service starting (heartbeat every %ss, %d job(s) registered)",
            self.heartbeat_interval_seconds,
            len(self._jobs),
        )
        write_heartbeat(status="running")
        try:
            while not self._stop_event.is_set():
                write_heartbeat(status="running")
                self.run_due_jobs()
                self._stop_event.wait(self.heartbeat_interval_seconds)
        finally:
            write_heartbeat(status="stopped")
            self.engine.dispose()
            logger.info("AsOS core service stopped cleanly")

    def run_one_tick(self) -> None:
        """Runs a single heartbeat write + due-job check without entering
        the blocking loop. Used by tests and debug commands."""
        write_heartbeat(status="running")
        self.run_due_jobs()

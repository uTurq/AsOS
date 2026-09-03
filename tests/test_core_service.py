from __future__ import annotations

import threading
import time

from asos.credentials import CredentialVault
from asos.service.core import CoreService
from asos.service.health import is_healthy
from tests.fakes import InMemoryKeyringBackend


def _service() -> CoreService:
    vault = CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")
    return CoreService(heartbeat_interval_seconds=1, credential_vault=vault)


def test_service_creates_schema_on_init(isolated_data_dir):
    from asos.config import get_database_path

    _service()
    assert get_database_path().exists()


def test_run_one_tick_writes_healthy_heartbeat(isolated_data_dir):
    service = _service()
    service.run_one_tick()
    healthy, _ = is_healthy()
    assert healthy is True


def test_run_forever_stops_cleanly_on_request(isolated_data_dir):
    service = _service()
    thread = threading.Thread(target=service.run_forever, daemon=True)
    thread.start()

    # Give it a moment to write its first heartbeat.
    time.sleep(0.2)
    healthy, _ = is_healthy()
    assert healthy is True

    service.request_stop()
    thread.join(timeout=5)
    assert not thread.is_alive()

    # After a clean stop, the heartbeat should report "stopped", which
    # is_healthy correctly treats as not-running.
    healthy_after_stop, reason = is_healthy()
    assert healthy_after_stop is False
    assert "stopped" in reason


def test_registered_job_runs_on_first_tick(isolated_data_dir):
    service = _service()
    calls = []
    service.register_job("test-job", interval_seconds=60, func=lambda session: calls.append(1))

    service.run_one_tick()
    assert calls == [1]


def test_job_does_not_rerun_before_its_interval_elapses(isolated_data_dir):
    service = _service()
    calls = []
    service.register_job("test-job", interval_seconds=3600, func=lambda session: calls.append(1))

    service.run_one_tick()
    service.run_one_tick()
    service.run_one_tick()
    assert calls == [1]  # only ran once, despite three ticks


def test_job_reruns_after_interval_elapses(isolated_data_dir):
    import datetime

    service = _service()
    calls = []
    service.register_job("test-job", interval_seconds=0.05, func=lambda session: calls.append(1))

    service.run_one_tick()
    time.sleep(0.1)
    service.run_one_tick()
    assert calls == [1, 1]


def test_failing_job_does_not_crash_service_or_block_other_jobs(isolated_data_dir):
    service = _service()
    calls = []

    def failing_job(session):
        raise RuntimeError("simulated failure")

    def working_job(session):
        calls.append("worked")

    service.register_job("failing", interval_seconds=60, func=failing_job)
    service.register_job("working", interval_seconds=60, func=working_job)

    service.run_one_tick()  # must not raise
    assert calls == ["worked"]


def test_failing_job_still_backs_off_by_interval(isolated_data_dir):
    """A persistently failing job should retry once per interval, not
    once per tick -- otherwise a broken Canvas token would spam retries
    every heartbeat forever."""
    service = _service()
    attempt_count = []

    def failing_job(session):
        attempt_count.append(1)
        raise RuntimeError("simulated failure")

    service.register_job("failing", interval_seconds=3600, func=failing_job)

    service.run_one_tick()
    service.run_one_tick()
    service.run_one_tick()
    assert len(attempt_count) == 1

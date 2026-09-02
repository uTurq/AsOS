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

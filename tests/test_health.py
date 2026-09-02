from __future__ import annotations

import datetime
import json

from asos.config import get_heartbeat_path
from asos.service.health import is_healthy, read_heartbeat, write_heartbeat


def test_no_heartbeat_file_means_unhealthy(isolated_data_dir):
    healthy, reason = is_healthy()
    assert healthy is False
    assert "no heartbeat" in reason


def test_fresh_heartbeat_is_healthy(isolated_data_dir):
    write_heartbeat(status="running")
    healthy, reason = is_healthy()
    assert healthy is True
    assert "running" in reason


def test_stale_heartbeat_is_unhealthy(isolated_data_dir):
    write_heartbeat(status="running")
    # Backdate the heartbeat file's timestamp to simulate a crashed service.
    path = get_heartbeat_path()
    data = json.loads(path.read_text())
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    data["timestamp"] = old_time.isoformat()
    path.write_text(json.dumps(data))

    healthy, reason = is_healthy(max_age_seconds=60)
    assert healthy is False
    assert "stale" in reason


def test_stopped_status_is_unhealthy(isolated_data_dir):
    write_heartbeat(status="stopped")
    healthy, reason = is_healthy()
    assert healthy is False
    assert "stopped" in reason


def test_read_heartbeat_roundtrip(isolated_data_dir):
    write_heartbeat(status="running")
    hb = read_heartbeat()
    assert hb is not None
    assert hb.status == "running"
    assert hb.pid > 0


def test_corrupt_heartbeat_file_treated_as_absent(isolated_data_dir):
    path = get_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json{{{")
    assert read_heartbeat() is None
    healthy, _ = is_healthy()
    assert healthy is False

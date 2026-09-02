"""
Health check mechanism.

The running core service periodically writes a small JSON heartbeat
file (timestamp + PID + status — nothing sensitive). Anything that
wants to know "is AsOS actually running?" — the CLI, a future tray
icon, a future dashboard — reads that file rather than trying to poll
the process directly, which keeps the check trivially cross-platform.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os

from asos.config import get_heartbeat_path

DEFAULT_STALE_AFTER_SECONDS = 60


@dataclasses.dataclass
class Heartbeat:
    timestamp: datetime.datetime
    pid: int
    status: str


def write_heartbeat(status: str = "running") -> None:
    payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pid": os.getpid(),
        "status": status,
    }
    path = get_heartbeat_path()
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload))
    tmp_path.replace(path)  # atomic on both POSIX and Windows


def read_heartbeat() -> Heartbeat | None:
    path = get_heartbeat_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Heartbeat(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            pid=data["pid"],
            status=data["status"],
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def is_healthy(max_age_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> tuple[bool, str]:
    """Returns (healthy, human_readable_reason)."""
    hb = read_heartbeat()
    if hb is None:
        return False, "no heartbeat file found — service has likely never run, or data dir was cleared"

    age = datetime.datetime.now(datetime.timezone.utc) - hb.timestamp
    if age.total_seconds() > max_age_seconds:
        return False, f"heartbeat is stale ({age.total_seconds():.0f}s old, pid {hb.pid}, status was '{hb.status}')"

    if hb.status != "running":
        return False, f"last reported status was '{hb.status}', not 'running' (pid {hb.pid})"

    return True, f"running (pid {hb.pid}, heartbeat {age.total_seconds():.0f}s old)"

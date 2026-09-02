"""
Central configuration for AsOS.

Design principle: no hardcoded OS-specific paths anywhere else in the
codebase. Everything that needs a data/log/config directory imports
from here. This is what lets the same code run correctly on the
Windows machine AsOS actually lives on and in a Linux dev/test
environment without special-casing.

The data directory can be overridden with the ASOS_DATA_DIR environment
variable — this is how tests and CI get an isolated, disposable
directory instead of touching the real user data dir.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "AsOS"
_APP_AUTHOR = "AsOS"  # used on Windows/macOS path construction

_dirs = PlatformDirs(appname=_APP_NAME, appauthor=_APP_AUTHOR)


def get_data_dir() -> Path:
    """Directory for persistent application data (the SQLite DB, ingested
    document store, credential-vault metadata, etc.).

    Windows default: %LOCALAPPDATA%\\AsOS\\AsOS
    Linux default:   ~/.local/share/AsOS
    macOS default:   ~/Library/Application Support/AsOS
    """
    override = os.environ.get("ASOS_DATA_DIR")
    path = Path(override) if override else Path(_dirs.user_data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_log_dir() -> Path:
    """Directory for log files."""
    override = os.environ.get("ASOS_LOG_DIR")
    path = Path(override) if override else Path(_dirs.user_log_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_database_path() -> Path:
    """Path to the primary SQLite database file."""
    return get_data_dir() / "asos.db"


def get_database_url() -> str:
    """SQLAlchemy connection URL for the primary database."""
    return f"sqlite:///{get_database_path()}"


def get_heartbeat_path() -> Path:
    """Path to the core service's heartbeat file, used for health checks."""
    return get_data_dir() / "heartbeat.json"


# Credential vault service name — the namespace AsOS uses when storing
# secrets in the OS-native credential store (Windows Credential Manager,
# macOS Keychain, Linux Secret Service). Keeping this centralized avoids
# typos silently creating a second, orphaned credential entry.
CREDENTIAL_SERVICE_NAME = "AsOS"

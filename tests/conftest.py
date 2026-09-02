from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch):
    """Every test gets its own throwaway data dir so tests never touch
    the real ~/.local/share/AsOS (or %LOCALAPPDATA%\\AsOS on Windows)."""
    monkeypatch.setenv("ASOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ASOS_LOG_DIR", str(tmp_path / "logs"))
    yield tmp_path


@pytest.fixture(autouse=True)
def isolated_keyring_backend(tmp_path: Path):
    """Point the real `keyring` module at a throwaway file-based backend
    for the duration of each test.

    This is a dev/test-only stand-in: it exists because this sandbox (and
    plain headless Linux/CI generally) has no OS credential store to talk
    to. On the actual target machine (Windows), `keyring` auto-selects
    Windows Credential Manager and this fixture is irrelevant — it never
    runs there because it only affects the `keyring` module's in-memory
    backend selection for this test process.
    """
    import keyring
    from keyrings.alt.file import PlaintextKeyring

    backend = PlaintextKeyring()
    backend.file_path = str(tmp_path / "test_keyring.cfg")
    original_backend = keyring.get_keyring()
    keyring.set_keyring(backend)
    yield
    keyring.set_keyring(original_backend)


@pytest.fixture
def engine(isolated_data_dir):
    """A DB engine with the full schema applied via SQLAlchemy metadata
    directly (fast, for unit tests). Migration correctness itself is
    covered separately in test_migrations.py."""
    from asos.config import get_database_url
    from asos.db.base import Base, make_engine
    from asos.db import models  # noqa: F401  (registers tables)

    eng = make_engine(get_database_url())
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    from asos.db.base import make_session_factory

    factory = make_session_factory(engine)
    with factory() as s:
        yield s

"""
Verifies migrations actually work end-to-end via the real alembic CLI,
against a throwaway data dir — not just that the models import cleanly.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_alembic(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _table_names(db_path: Path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("select name from sqlite_master where type='table'").fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def test_upgrade_creates_all_expected_tables(isolated_data_dir):
    env = os.environ.copy()
    env["ASOS_DATA_DIR"] = str(isolated_data_dir / "data")

    result = _run_alembic("upgrade", "head", env=env)
    assert result.returncode == 0, result.stderr

    db_path = isolated_data_dir / "data" / "asos.db"
    assert db_path.exists()

    tables = _table_names(db_path)
    expected = {
        "courses",
        "assignments",
        "calendar_events",
        "concepts",
        "mastery_events",
        "documents",
        "document_chunks",
        "sources",
        "facts",
        "assessments",
        "assessment_concepts",
        "assessment_documents",
        "tasks",
        "notifications",
        "study_sessions",
        "study_session_concepts",
        "episodic_notes",
        "alembic_version",
    }
    assert expected.issubset(tables)


def test_downgrade_then_upgrade_is_clean(isolated_data_dir):
    env = os.environ.copy()
    env["ASOS_DATA_DIR"] = str(isolated_data_dir / "data")

    assert _run_alembic("upgrade", "head", env=env).returncode == 0
    down = _run_alembic("downgrade", "base", env=env)
    assert down.returncode == 0, down.stderr

    db_path = isolated_data_dir / "data" / "asos.db"
    tables = _table_names(db_path) - {"alembic_version"}
    assert tables == set(), f"downgrade left tables behind: {tables}"

    up_again = _run_alembic("upgrade", "head", env=env)
    assert up_again.returncode == 0, up_again.stderr

from __future__ import annotations

from typer.testing import CliRunner

from asos.cli import app

runner = CliRunner()


def test_paths_command_runs(isolated_data_dir):
    result = runner.invoke(app, ["paths"])
    assert result.exit_code == 0
    assert "Data dir" in result.stdout


def test_init_db_command_runs(isolated_data_dir):
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0

    from asos.config import get_database_path

    assert get_database_path().exists()


def test_health_command_reports_unhealthy_when_never_run(isolated_data_dir):
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 1
    assert "no heartbeat" in result.stdout


def test_creds_set_rejects_unknown_name(isolated_data_dir):
    result = runner.invoke(app, ["creds", "set", "not_a_real_credential"])
    assert result.exit_code == 1
    assert "Unknown credential name" in result.stdout


def test_creds_check_reports_not_set(isolated_data_dir):
    result = runner.invoke(app, ["creds", "check", "canvas_api_token"])
    assert result.exit_code == 0
    assert "not set" in result.stdout


def test_canvas_sync_without_credentials_fails_clearly(isolated_data_dir):
    result = runner.invoke(app, ["canvas", "sync"])
    assert result.exit_code == 1
    assert "not fully set" in result.stdout


def test_calendar_sync_without_credentials_fails_clearly(isolated_data_dir):
    result = runner.invoke(app, ["calendar", "sync"])
    assert result.exit_code == 1
    assert "ics_feed_url is not set" in result.stdout


def test_facts_conflicts_empty_by_default(isolated_data_dir):
    runner.invoke(app, ["init-db"])
    result = runner.invoke(app, ["facts", "conflicts"])
    assert result.exit_code == 0
    assert "No unresolved fact conflicts" in result.stdout


def test_facts_resolve_and_recheck_conflicts(isolated_data_dir):
    runner.invoke(app, ["init-db"])

    from asos.config import get_database_url
    from asos.db.base import make_engine, make_session_factory
    from asos.db.enums import FactExplicitness, SourceType
    from asos.db.models import Course
    from asos.facts.authority import record_fact
    import datetime

    engine = make_engine(get_database_url())
    with make_session_factory(engine)() as session:
        course = Course(name="Chemistry 1010")
        session.add(course)
        session.commit()
        record_fact(
            session,
            course_id=course.id,
            subject="Exam 1 date",
            value="2026-10-14",
            source_type=SourceType.SYLLABUS,
            explicitness=FactExplicitness.EXPLICIT_STATEMENT,
            verified_at=datetime.datetime(2026, 8, 1),
        )
        record_fact(
            session,
            course_id=course.id,
            subject="Exam 1 date",
            value="2026-10-16",
            source_type=SourceType.CANVAS_CALENDAR_AUTO,
            explicitness=FactExplicitness.DEFAULT_TEMPLATE,
            verified_at=datetime.datetime(2026, 9, 1),
        )
        course_id = course.id
    engine.dispose()

    result = runner.invoke(app, ["facts", "conflicts"])
    assert result.exit_code == 0
    assert "Exam 1 date" in result.stdout

    resolve_result = runner.invoke(app, ["facts", "resolve", "Exam 1 date", "2026-10-16", "--course-id", str(course_id)])
    assert resolve_result.exit_code == 0
    assert "Recorded" in resolve_result.stdout

    after_result = runner.invoke(app, ["facts", "conflicts"])
    assert "No unresolved fact conflicts" in after_result.stdout

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

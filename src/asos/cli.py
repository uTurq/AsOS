"""
AsOS CLI — the debugging/administration surface. Kept available
permanently per the v1 spec: voice is an additional interface, not a
replacement for text/CLI access.
"""

from __future__ import annotations

import getpass
import logging
import signal
import sys

import typer

from asos.config import get_data_dir, get_database_path, get_database_url, get_log_dir
from asos.credentials import (
    ANTHROPIC_API_KEY,
    CANVAS_API_TOKEN,
    CANVAS_BASE_URL,
    CredentialNotFoundError,
    CredentialVault,
    KNOWN_CREDENTIAL_NAMES,
)
from asos.logging_setup import configure_logging
from asos.service.core import CoreService
from asos.service.health import is_healthy

app = typer.Typer(help="AsOS — Assist Operating System")
creds_app = typer.Typer(help="Manage locally-stored credentials (Canvas token, Anthropic API key, ...).")
canvas_app = typer.Typer(help="Canvas sync commands.")
app.add_typer(creds_app, name="creds")
app.add_typer(canvas_app, name="canvas")

logger = logging.getLogger("asos.cli")


@app.command()
def paths() -> None:
    """Print the resolved OS-specific paths AsOS is using."""
    typer.echo(f"Data dir:     {get_data_dir()}")
    typer.echo(f"Database:     {get_database_path()}")
    typer.echo(f"Log dir:      {get_log_dir()}")


@app.command("init-db")
def init_db() -> None:
    """Apply all pending Alembic migrations to bring the local DB up to date."""
    import subprocess
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=project_root)
    raise typer.Exit(result.returncode)


@app.command()
def run() -> None:
    """Run the AsOS core service in the foreground (Ctrl+C to stop)."""
    configure_logging()
    service = CoreService()

    def _handle_signal(signum, frame):
        service.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    service.run_forever()


@app.command()
def health(max_age_seconds: int = 60) -> None:
    """Check whether the core service appears to be running, via its heartbeat file."""
    healthy, reason = is_healthy(max_age_seconds=max_age_seconds)
    typer.echo(reason)
    raise typer.Exit(0 if healthy else 1)


def _friendly_vault_or_exit() -> CredentialVault:
    """Constructing a real CredentialVault touches the OS credential store
    immediately (keyring probes for a usable backend). On a properly set
    up Windows/macOS/Linux-desktop machine this always succeeds; it can
    fail on a bare headless Linux box with no Secret Service/KWallet
    running. Surface that as a clear message, not a stack trace."""
    try:
        vault = CredentialVault()
        vault.has_credential("__asos_backend_probe__")  # forces backend selection now, not later
        return vault
    except Exception as exc:  # keyring's own exception types vary by backend
        typer.echo(
            "Could not reach an OS credential store (Windows Credential Manager / "
            "macOS Keychain / Linux Secret Service). No credential was stored, read, "
            f"or deleted.\nUnderlying error: {exc}"
        )
        raise typer.Exit(1)


@creds_app.command("set")
def creds_set(name: str = typer.Argument(..., help=f"One of: {', '.join(sorted(KNOWN_CREDENTIAL_NAMES))}")) -> None:
    """Prompt for a credential value and store it in the OS credential vault.
    The value is never taken as a CLI argument (would land in shell history)
    and is never echoed or logged."""
    if name not in KNOWN_CREDENTIAL_NAMES:
        typer.echo(f"Unknown credential name '{name}'. Known: {', '.join(sorted(KNOWN_CREDENTIAL_NAMES))}")
        raise typer.Exit(1)
    vault = _friendly_vault_or_exit()
    value = getpass.getpass(f"Enter value for '{name}' (input hidden): ")
    vault.set_credential(name, value)
    typer.echo(f"Stored '{name}'.")


@creds_app.command("check")
def creds_check(name: str) -> None:
    """Report whether a credential is present, without ever revealing its value."""
    vault = _friendly_vault_or_exit()
    present = vault.has_credential(name)
    typer.echo(f"'{name}': {'present' if present else 'not set'}")


@creds_app.command("delete")
def creds_delete(name: str) -> None:
    """Remove a credential from the vault."""
    vault = _friendly_vault_or_exit()
    vault.delete_credential(name)
    typer.echo(f"Deleted '{name}' (if it existed).")


@canvas_app.command("sync")
def canvas_sync() -> None:
    """Run one Canvas sync pass (courses, assignments, calendar events)
    and print a summary. Requires canvas_base_url and canvas_api_token
    to already be set via `asos creds set`."""
    from asos.canvas.client import CanvasAPIError, CanvasClient
    from asos.canvas.sync import CanvasSyncWorker
    from asos.db.base import Base, make_engine, make_session_factory
    from asos.db import models  # noqa: F401

    vault = _friendly_vault_or_exit()
    base_url = vault.get_credential_or_none(CANVAS_BASE_URL)
    token = vault.get_credential_or_none(CANVAS_API_TOKEN)
    if not base_url or not token:
        typer.echo(
            "Canvas credentials are not fully set. Run:\n"
            f"  asos creds set {CANVAS_BASE_URL}\n"
            f"  asos creds set {CANVAS_API_TOKEN}"
        )
        raise typer.Exit(1)

    engine = make_engine(get_database_url())
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    client = CanvasClient(base_url, token)
    worker = CanvasSyncWorker(client)

    try:
        with session_factory() as session:
            summary = worker.sync_all(session)
    except CanvasAPIError as exc:
        typer.echo(f"Canvas sync failed: {exc}")
        raise typer.Exit(1)

    typer.echo(
        f"Synced {summary['courses']} course(s), {summary['assignments']} assignment(s), "
        f"{summary['calendar_events']} calendar event(s). "
        f"{summary['changes_detected']} change(s) detected this run."
    )


if __name__ == "__main__":
    app()

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
facts_app = typer.Typer(help="Query and resolve fact conflicts.")
docs_app = typer.Typer(help="Document ingestion (syllabi, lecture notes, study guides) and search.")
app.add_typer(creds_app, name="creds")
app.add_typer(canvas_app, name="canvas")
app.add_typer(facts_app, name="facts")
app.add_typer(docs_app, name="docs")

logger = logging.getLogger("asos.cli")


@app.command()
def paths() -> None:
    """Print the resolved OS-specific paths AsOS is using."""
    typer.echo(f"Data dir:     {get_data_dir()}")
    typer.echo(f"Database:     {get_database_path()}")
    typer.echo(f"Log dir:      {get_log_dir()}")


@app.command("init-db")
def init_db() -> None:
    """Apply all pending Alembic migrations and seed reference data
    (e.g. default source-authority weights)."""
    import subprocess
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=project_root)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)

    from asos.db.base import make_engine, make_session_factory
    from asos.facts.authority import seed_default_sources

    engine = make_engine(get_database_url())
    with make_session_factory(engine)() as session:
        seed_default_sources(session)
    engine.dispose()


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


@facts_app.command("conflicts")
def facts_conflicts(course_id: int = typer.Option(None, help="Limit to one course's DB id.")) -> None:
    """List every subject with an unresolved, genuinely conflicting set
    of facts (e.g. syllabus vs. Canvas disagreeing on an exam date)."""
    from asos.db.base import make_engine, make_session_factory
    from asos.facts.authority import find_all_conflicts

    engine = make_engine(get_database_url())
    with make_session_factory(engine)() as session:
        conflicts = find_all_conflicts(session, course_id=course_id)
        if not conflicts:
            typer.echo("No unresolved fact conflicts.")
            return
        for resolution in conflicts:
            typer.echo(f"Subject: {resolution.subject} (course_id={resolution.course_id})")
            for fact in resolution.conflicting:
                typer.echo(
                    f"  - '{fact.value}'  [source={fact.source.type.value}, "
                    f"explicitness={fact.explicitness.value}, verified_at={fact.verified_at}]"
                )
    engine.dispose()


@facts_app.command("resolve")
def facts_resolve(
    subject: str = typer.Argument(..., help="Exact subject text, as shown by `asos facts conflicts`."),
    value: str = typer.Argument(..., help="The correct value, as the user states it."),
    course_id: int = typer.Option(None, help="Limit to one course's DB id."),
) -> None:
    """Settle a conflict by stating the correct value yourself. Recorded
    as a new, high-authority fact — the old conflicting facts are kept
    for history but stop being considered current."""
    from asos.db.base import make_engine, make_session_factory
    from asos.facts.authority import resolve_conflict_with_user_statement

    engine = make_engine(get_database_url())
    with make_session_factory(engine)() as session:
        fact = resolve_conflict_with_user_statement(session, course_id=course_id, subject=subject, value=value)
        typer.echo(f"Recorded '{subject}' = '{value}' (fact id {fact.id}). Future conflicts on this subject won't resurface this.")
    engine.dispose()


@docs_app.command("ingest")
def docs_ingest(
    path: str = typer.Argument(..., help="Path to a .pdf, .docx, .pptx, .txt, or .md file."),
    source_type: str = typer.Option(..., help="One of: syllabus, lecture, notes, study_guide, other"),
    course_id: int = typer.Option(None, help="Course DB id to associate this document with."),
    title: str = typer.Option(None, help="Defaults to the filename if omitted."),
) -> None:
    """Parse, chunk, embed, and store a document.

    NOTE: uses a placeholder (non-semantic) embedding — see
    PROJECT.md's open decisions. Retrieval will work but with mediocre
    relevance quality until a real local embedding model is chosen and
    validated on the target machine."""
    from pathlib import Path

    from asos.db.base import Base, make_engine, make_session_factory
    from asos.db import models  # noqa: F401
    from asos.db.enums import DocumentSourceType
    from asos.documents.embeddings import HashingEmbeddingProvider
    from asos.documents.ingestion import ingest_document

    try:
        source_type_enum = DocumentSourceType(source_type)
    except ValueError:
        typer.echo(f"Unknown source_type '{source_type}'. Must be one of: {', '.join(t.value for t in DocumentSourceType)}")
        raise typer.Exit(1)

    source_path = Path(path)
    if not source_path.exists():
        typer.echo(f"File not found: {path}")
        raise typer.Exit(1)

    engine = make_engine(get_database_url())
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as session:
        document = ingest_document(
            session,
            source_path=source_path,
            course_id=course_id,
            source_type=source_type_enum,
            title=title,
            embedding_provider=HashingEmbeddingProvider(),
        )
        typer.echo(f"Ingested '{document.title}' (document id {document.id}).")
    engine.dispose()


@docs_app.command("search")
def docs_search(
    query: str = typer.Argument(...),
    course_id: int = typer.Option(None, help="Limit search to one course."),
    top_k: int = typer.Option(5),
) -> None:
    """Search ingested document chunks (placeholder embedding — see `docs ingest`)."""
    from asos.db.base import make_engine, make_session_factory
    from asos.documents.embeddings import HashingEmbeddingProvider
    from asos.documents.retrieval import search_chunks

    engine = make_engine(get_database_url())
    with make_session_factory(engine)() as session:
        results = search_chunks(
            session, query=query, embedding_provider=HashingEmbeddingProvider(), course_id=course_id, top_k=top_k
        )
        if not results:
            typer.echo("No matching content found.")
        for r in results:
            label = f" [{r.chunk.page_or_slide}]" if r.chunk.page_or_slide else ""
            typer.echo(f"({r.score:.3f}) {r.document.title}{label}: {r.chunk.content[:200]}")
    engine.dispose()


@docs_app.command("extract-facts")
def docs_extract_facts(document_id: int = typer.Argument(...)) -> None:
    """Run the one-time Claude extraction pass over an already-ingested
    document's text, recording any facts found. Requires
    anthropic_api_key to be set — this makes a real, billed API call."""
    from asos.db.base import make_engine, make_session_factory
    from asos.db.models import Document, DocumentChunk
    from asos.documents.claude_client import AnthropicClaudeClient, ClaudeAPIError
    from asos.documents.extraction import ExtractionError, extract_syllabus_facts

    vault = _friendly_vault_or_exit()
    api_key = vault.get_credential_or_none(ANTHROPIC_API_KEY)
    if not api_key:
        typer.echo(f"anthropic_api_key is not set. Run: asos creds set {ANTHROPIC_API_KEY}")
        raise typer.Exit(1)

    engine = make_engine(get_database_url())
    with make_session_factory(engine)() as session:
        document = session.get(Document, document_id)
        if document is None:
            typer.echo(f"No document with id {document_id}.")
            raise typer.Exit(1)
        chunks = (
            session.query(DocumentChunk)
            .filter_by(document_id=document_id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        full_text = "\n\n".join(c.content for c in chunks)

        try:
            facts = extract_syllabus_facts(
                session,
                course_id=document.course_id,
                document_id=document.id,
                syllabus_text=full_text,
                claude_client=AnthropicClaudeClient(api_key=api_key),
            )
        except (ClaudeAPIError, ExtractionError) as exc:
            typer.echo(f"Extraction failed: {exc}")
            raise typer.Exit(1)

        typer.echo(f"Extracted {len(facts)} fact(s):")
        for f in facts:
            typer.echo(f"  - {f.subject}: {f.value}")
    engine.dispose()


if __name__ == "__main__":
    app()

# AsOS — Assist Operating System

A persistent, local-first academic assistant. Claude is the reasoning
engine invoked selectively by a local core service; most retrieval,
scheduling, and state management happens locally without API calls.

See `PROJECT.md` for the locked v1 specification, architecture,
acceptance criteria, and decision log — that file is the durable
source of truth for this project across sessions.

## Quick start (development)

```
uv venv .venv
uv pip install -e ".[dev]"
.venv/bin/asos init-db
.venv/bin/asos paths
.venv/bin/asos run          # Ctrl+C to stop
.venv/bin/asos health       # in another terminal
.venv/bin/pytest
```

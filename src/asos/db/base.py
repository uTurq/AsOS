"""Engine/session construction. Models live in models.py; this module is
kept separate so Alembic's env.py can import Base without pulling in
engine-construction side effects, and vice versa."""

from __future__ import annotations

import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def _now() -> datetime.datetime:
    """Returns the current time as a naive UTC datetime.

    Convention for this entire codebase: every datetime stored in or
    compared against the database is naive and implicitly UTC — never
    timezone-aware. This is deliberate, not an oversight: SQLite has no
    native timezone support, and `DateTime(timezone=True)` on SQLite
    silently returns a NAIVE datetime the moment a row is reloaded from
    disk (e.g. after the object falls out of SQLAlchemy's identity map,
    which happens routinely — a service restart, a cache eviction, or
    simply enough time passing that Python garbage-collects the old
    in-memory object). A timezone-aware value in Python and a naive one
    read back from the DB are never `==` to each other even when they
    represent the same instant, which silently poisons any diffing or
    staleness logic built on top (this is exactly how a real bug was
    caught during Canvas-sync development — see PROJECT.md's decision
    log). Being explicitly naive-UTC everywhere removes the trap
    instead of papering over it. Any code that receives a timezone-aware
    datetime from elsewhere (an API response, `datetime.now(tz=...)`,
    etc.) must convert with `.astimezone(datetime.timezone.utc).replace(tzinfo=None)`
    before it touches the database.
    """
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def make_engine(database_url: str, *, echo: bool = False):
    # check_same_thread=False is safe here because we serialize DB access
    # through the core service's own event loop / a single writer — see
    # PROJECT.md "Concurrency model" for the reasoning.
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=echo, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)

"""Engine/session construction. Models live in models.py; this module is
kept separate so Alembic's env.py can import Base without pulling in
engine-construction side effects, and vice versa."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str, *, echo: bool = False):
    # check_same_thread=False is safe here because we serialize DB access
    # through the core service's own event loop / a single writer — see
    # PROJECT.md "Concurrency model" for the reasoning.
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=echo, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)

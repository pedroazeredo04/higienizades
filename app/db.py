"""Engine, session plumbing and the SQLite pragmas that make concurrency safe."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

from app.config import get_config


@event.listens_for(Engine, "connect")
def _apply_sqlite_pragmas(dbapi_connection, _record) -> None:
    """WAL + a busy timeout: readers never block the writer, and the odd
    simultaneous tap from two phones waits instead of erroring out."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_config().database_url,
        connect_args={"check_same_thread": False},
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed by the endpoint."""
    with Session(get_engine()) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for code outside a request (background jobs, CLI)."""
    with Session(get_engine()) as session:
        yield session

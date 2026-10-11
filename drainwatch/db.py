"""SQLite engine and session helpers. The demo database is rebuilt from the seed on every start."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from drainwatch import models  # noqa: F401  (registers the tables)

DB_PATH = Path(__file__).resolve().parent.parent / ".data" / "drainwatch.db"

_engine = None


def engine():
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return _engine


def reset_db() -> None:
    SQLModel.metadata.drop_all(engine())
    SQLModel.metadata.create_all(engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine(), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

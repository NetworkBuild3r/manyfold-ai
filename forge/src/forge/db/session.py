"""Engine / session helpers and the SPEC-007 skip-locked claim statement.

INIT-032/SPEC-004
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select

from forge.config import require_db_url
from forge.db.enums import ContainerStatus
from forge.db.models import Container

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine(url: str | None = None) -> Engine:
    """Return a process-wide engine, or a one-off engine when *url* is given."""
    global _engine
    if url is not None:
        return create_engine(url, pool_pre_ping=True)
    if _engine is None:
        _engine = create_engine(require_db_url(), pool_pre_ping=True)
    return _engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    global _session_factory
    if engine is not None:
        return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)
    return _session_factory


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def pending_claim_stmt(limit: int = 50) -> Select[tuple[Container]]:
    """Hot path for SPEC-007: pending rows, ordered, FOR UPDATE SKIP LOCKED.

    Uses ix_containers_pending_claim (status, id) WHERE status = 'pending'.
    """
    return (
        select(Container)
        .where(Container.status == ContainerStatus.pending)
        .order_by(Container.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

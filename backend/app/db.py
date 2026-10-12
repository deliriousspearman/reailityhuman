from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


@lru_cache
def engine() -> Engine:
    return create_engine(settings().sqlalchemy_url, pool_pre_ping=True)


@lru_cache
def _sessions() -> sessionmaker[Session]:
    return sessionmaker(engine(), expire_on_commit=False)


@contextmanager
def session() -> Iterator[Session]:
    """A session that commits on success and rolls back on error."""
    with _sessions()() as s:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session() as s:
        yield s

"""SQLite persistence for run metadata (via SQLAlchemy). Kept simple by
design for this phase — no Postgres/Docker required to run locally.
Full TestRunState (large, nested) is persisted as JSON in the `state_json`
column; relational tables can be split out later without changing the API.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import get_settings

Base = declarative_base()


class TestRunRecord(Base):
    __tablename__ = "test_runs"

    run_id = Column(String, primary_key=True)
    application_url = Column(String, nullable=False)
    status = Column(String, nullable=False, default="created")
    current_stage = Column(String, nullable=False, default="initializing")
    state_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        )
        Base.metadata.create_all(_engine)
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()

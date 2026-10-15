from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover - dependency is optional for library consumers
    pass


def configured_database_url() -> str | None:
    value = str(os.getenv("DATABASE_URL", "") or "").strip()
    return value or None


def create_database_engine(database_url: str | None = None) -> Engine:
    url = database_url or configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(url, pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

"""Storage for pipeline results (SQLAlchemy with SQLite by default).

Helpers take a Session and return GenerationRecord models, never ORM rows.
Nothing here creates an engine or touches the filesystem at import time.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, DateTime, Engine, String, Text, create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from logixconfig.models import Equipment, Tag
from logixconfig.validator import Issue

logger = logging.getLogger(__name__)

DATABASE_URL_ENV_VAR = "DATABASE_URL"
DEFAULT_DATABASE_URL = "sqlite:///logixconfig.db"
DEFAULT_MAX_ROWS = 200


class Base(DeclarativeBase):
    pass


class GenerationRow(Base):
    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str] = mapped_column(Text)
    controller_name: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    equipment: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    tags: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    assumptions: Mapped[list[str]] = mapped_column(JSON)
    unsupported: Mapped[list[str]] = mapped_column(JSON)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class GenerationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime
    description: str
    controller_name: str
    status: str
    equipment: list[Equipment]
    tags: list[Tag]
    assumptions: list[str]
    unsupported: list[str]
    narrative: str | None
    issues: list[Issue]


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV_VAR) or DEFAULT_DATABASE_URL


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    options: dict[str, Any] = {"hide_parameters": True}
    if make_url(url).get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if is_in_memory_sqlite(url):
            options["poolclass"] = StaticPool
    return create_engine(url, **options)


def is_in_memory_sqlite(url: str) -> bool:
    parsed = make_url(url)
    return parsed.database in (None, "", ":memory:") or parsed.query.get("mode") == "memory"


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def create_generation(
    session: Session,
    *,
    description: str,
    controller_name: str,
    status: str,
    equipment: list[Equipment],
    tags: list[Tag],
    assumptions: list[str],
    unsupported: list[str],
    issues: list[Issue],
    narrative: str | None = None,
    created_at: datetime | None = None,
) -> GenerationRecord:
    row = GenerationRow(
        id=str(uuid.uuid4()),
        created_at=to_utc(created_at or datetime.now(timezone.utc)),
        description=description,
        controller_name=controller_name,
        status=status.value if isinstance(status, Enum) else status,
        equipment=[item.model_dump(mode="json") for item in equipment],
        tags=[tag.model_dump(mode="json") for tag in tags],
        assumptions=list(assumptions),
        unsupported=list(unsupported),
        narrative=narrative,
        issues=[issue.model_dump(mode="json") for issue in issues],
    )
    session.add(row)
    session.commit()
    logger.info("Stored generation %s with %d tags", row.id, len(row.tags))
    return to_record(row)


def get_generation(session: Session, generation_id: str) -> GenerationRecord | None:
    row = session.get(GenerationRow, generation_id)
    return to_record(row) if row else None


def prune_old(session: Session, max_rows: int = DEFAULT_MAX_ROWS) -> int:
    if max_rows < 1:
        raise ValueError("max_rows must be at least 1")
    newest = (
        select(GenerationRow.id)
        .order_by(GenerationRow.created_at.desc(), GenerationRow.id.desc())
        .limit(max_rows)
    )
    result = session.execute(delete(GenerationRow).where(GenerationRow.id.not_in(newest)))
    session.commit()
    deleted = result.rowcount or 0
    logger.info("Pruned %d old generations", deleted)
    return deleted


def to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    return moment.astimezone(timezone.utc)


def from_stored_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def to_record(row: GenerationRow) -> GenerationRecord:
    return GenerationRecord(
        id=row.id,
        created_at=from_stored_utc(row.created_at),
        description=row.description,
        controller_name=row.controller_name,
        status=row.status,
        equipment=[Equipment.model_validate(item) for item in row.equipment],
        tags=[Tag.model_validate(tag) for tag in row.tags],
        assumptions=list(row.assumptions),
        unsupported=list(row.unsupported),
        narrative=row.narrative,
        issues=[Issue.model_validate(issue) for issue in row.issues],
    )

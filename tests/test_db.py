import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from logixconfig import db
from logixconfig.models import Equipment, Tag
from logixconfig.templates import tags_for
from logixconfig.validator import Issue, Severity

PUMP = Equipment(name="P101", type="pump", description="Crude transfer pump A")
LEVEL = Equipment(name="LT101", type="level_transmitter", description="Tank 1 level transmitter")
ISSUE = Issue(name="LT101_Hi_SP", severity=Severity.WARNING, rule="missing_description", message="No description")
SECRET_DESCRIPTION = "Confidential-process-text-7f3a: a tank feeds two pumps"
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def engine() -> Engine:
    engine = db.make_engine("sqlite://")
    db.init_db(engine)
    return engine


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return db.session_factory(engine)


def store(sessions: sessionmaker[Session], **overrides) -> db.GenerationRecord:
    values = {
        "description": "A tank feeds a pump.",
        "controller_name": "Skid01",
        "status": "succeeded",
        "equipment": [PUMP, LEVEL],
        "tags": tags_for(PUMP) + tags_for(LEVEL),
        "assumptions": ["Assumed one pump"],
        "unsupported": ["tank"],
        "issues": [ISSUE],
        "narrative": "Pump P101 transfers crude.",
    }
    values.update(overrides)
    with sessions() as session:
        return db.create_generation(session, **values)


def fetch(sessions: sessionmaker[Session], generation_id: str) -> db.GenerationRecord | None:
    with sessions() as session:
        return db.get_generation(session, generation_id)


def row_count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(db.GenerationRow))


def test_round_trip_returns_typed_models(sessions: sessionmaker[Session]) -> None:
    created = store(sessions)
    loaded = fetch(sessions, created.id)
    assert loaded == created
    assert loaded.equipment == [PUMP, LEVEL]
    assert all(isinstance(item, Equipment) for item in loaded.equipment)
    assert all(isinstance(tag, Tag) for tag in loaded.tags)
    assert loaded.tags == tags_for(PUMP) + tags_for(LEVEL)
    assert loaded.issues == [ISSUE]
    assert isinstance(loaded.issues[0], Issue)
    assert (loaded.controller_name, loaded.status) == ("Skid01", "succeeded")
    assert (loaded.assumptions, loaded.unsupported) == (["Assumed one pump"], ["tank"])
    assert loaded.narrative == "Pump P101 transfers crude."


def test_record_is_frozen(sessions: sessionmaker[Session]) -> None:
    record = store(sessions)
    with pytest.raises(Exception):
        record.status = "failed"


def test_enum_status_is_stored_as_its_value(sessions: sessionmaker[Session]) -> None:
    from enum import Enum

    class FakeStatus(str, Enum):
        FAILED = "failed"

    record = store(sessions, status=FakeStatus.FAILED)
    assert fetch(sessions, record.id).status == "failed"


def test_created_at_is_utc_aware_after_reading_back(sessions: sessionmaker[Session]) -> None:
    pacific = timezone(timedelta(hours=-8))
    record = store(sessions, created_at=datetime(2026, 11, 3, 22, 0, tzinfo=pacific))
    loaded = fetch(sessions, record.id)
    assert loaded.created_at.utcoffset() == timedelta(0)
    assert loaded.created_at == datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


def test_created_at_defaults_to_now_in_utc(sessions: sessionmaker[Session]) -> None:
    before = datetime.now(timezone.utc)
    loaded = fetch(sessions, store(sessions).id)
    assert loaded.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(seconds=1) <= loaded.created_at <= datetime.now(timezone.utc)


def test_naive_created_at_is_rejected(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError):
        store(sessions, created_at=datetime(2026, 1, 1))


def test_unknown_id_returns_none(sessions: sessionmaker[Session]) -> None:
    assert fetch(sessions, str(uuid.uuid4())) is None


def test_ids_are_unique_uuid4_strings(sessions: sessionmaker[Session]) -> None:
    ids = [store(sessions).id for _ in range(5)]
    assert len(set(ids)) == 5
    assert all(uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value for value in ids)


def test_description_is_stored_unchanged(sessions: sessionmaker[Session]) -> None:
    description = 'Tank "TK-100" feeds\n  pump P101 \'A\'\n\ttemp 50 \u00b0C, caf\u00e9 \u6c34 \U0001f6e2 ]]> <x>&amp; '
    record = store(sessions, description=description)
    assert fetch(sessions, record.id).description == description


def test_empty_lists_and_no_narrative_round_trip(sessions: sessionmaker[Session]) -> None:
    record = store(sessions, assumptions=[], unsupported=[], issues=[], narrative=None)
    loaded = fetch(sessions, record.id)
    assert (loaded.assumptions, loaded.unsupported, loaded.issues, loaded.narrative) == ([], [], [], None)


def test_prune_keeps_newest_rows(sessions: sessionmaker[Session]) -> None:
    records = [store(sessions, created_at=START + timedelta(minutes=i)) for i in range(5)]
    with sessions() as session:
        assert db.prune_old(session, max_rows=2) == 3
    assert row_count(sessions) == 2
    assert [fetch(sessions, record.id) is not None for record in records] == [False, False, False, True, True]


def test_prune_does_nothing_under_the_limit(sessions: sessionmaker[Session]) -> None:
    for i in range(3):
        store(sessions, created_at=START + timedelta(minutes=i))
    with sessions() as session:
        assert db.prune_old(session, max_rows=3) == 0
        assert db.prune_old(session) == 0
    assert row_count(sessions) == 3


@pytest.mark.parametrize("max_rows", [0, -1])
def test_prune_rejects_max_rows_below_one(sessions: sessionmaker[Session], max_rows: int) -> None:
    with sessions() as session, pytest.raises(ValueError):
        db.prune_old(session, max_rows=max_rows)


def test_database_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.database_url() == "sqlite:///logixconfig.db"


def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///other.db")
    assert db.database_url() == "sqlite:///other.db"


def test_in_memory_sqlite_uses_static_pool() -> None:
    assert db.make_engine("sqlite://").pool.__class__.__name__ == "StaticPool"
    assert db.make_engine("sqlite:///:memory:").pool.__class__.__name__ == "StaticPool"


def test_import_creates_no_engine_or_file(tmp_path: Path) -> None:
    script = (
        "import sqlalchemy\n"
        "def fail(*args, **kwargs):\n"
        "    raise AssertionError('engine created at import')\n"
        "sqlalchemy.create_engine = fail\n"
        "import logixconfig.db\n"
    )
    env = {**os.environ, "DATABASE_URL": "postgresql://nobody@unreachable.invalid:1/none"}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_logs_never_contain_description(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine")
    engine = db.make_engine("sqlite://")
    db.init_db(engine)
    sessions = db.session_factory(engine)
    record = store(sessions, description=SECRET_DESCRIPTION, narrative=SECRET_DESCRIPTION)
    fetch(sessions, record.id)
    with sessions() as session:
        db.prune_old(session, max_rows=1)
    assert any(record.name.startswith("sqlalchemy.engine") for record in caplog.records)
    assert "Confidential-process-text-7f3a" not in caplog.text


def test_two_sessions_share_injected_engine(sessions: sessionmaker[Session]) -> None:
    with sessions() as writer:
        record = db.create_generation(
            writer,
            description="d",
            controller_name="Skid01",
            status="succeeded",
            equipment=[PUMP],
            tags=tags_for(PUMP),
            assumptions=[],
            unsupported=[],
            issues=[],
        )
    with sessions() as reader:
        assert db.get_generation(reader, record.id) == record

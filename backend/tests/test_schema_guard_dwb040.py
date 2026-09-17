# Path: tests/test_schema_guard_dwb040.py
# File: test_schema_guard_dwb040.py
# Created: 2026-09-17
# Purpose: Pin the startup schema guard: a behind database refuses to boot, an at-head one is left alone, a virgin one is built from the models (DWB-040)
# Caller: pytest
# Callees: app.services.schema_guard
# Data In: monkeypatched revision lookups
# Data Out: Assertions on SchemaOutOfDate and on whether create_all runs
# Last Modified: 2026-09-17 (DWB-040: initial)

import pytest

from app.services import schema_guard
from app.services.schema_guard import SchemaOutOfDate, verify_schema


class _Sentinel:
    """Stands in for the engine; the guard only passes it through."""


@pytest.fixture
def created(monkeypatch):
    """Record whether the model-driven create_all path was taken."""
    calls = []
    monkeypatch.setattr(
        schema_guard.Base.metadata, "create_all", lambda bind: calls.append(bind)
    )
    return calls


def _revisions(monkeypatch, applied, head):
    monkeypatch.setattr(schema_guard, "_applied_revision", lambda engine: applied)
    monkeypatch.setattr(schema_guard, "_head_revision", lambda: head)


class TestBehindDatabaseRefusesToBoot:
    def test_raises_naming_both_revisions(self, monkeypatch, created):
        _revisions(monkeypatch, "dwb527a1b2c3", "dwb581a1b2c3")

        with pytest.raises(SchemaOutOfDate) as excinfo:
            verify_schema(_Sentinel())

        message = str(excinfo.value)
        assert "dwb527a1b2c3" in message
        assert "dwb581a1b2c3" in message
        assert "alembic upgrade head" in message

    def test_does_not_half_build_the_schema(self, monkeypatch, created):
        # The whole point: a behind database must not get the new tables
        # without the new columns, which is what made the failure silent.
        _revisions(monkeypatch, "dwb527a1b2c3", "dwb581a1b2c3")

        with pytest.raises(SchemaOutOfDate):
            verify_schema(_Sentinel())

        assert created == []


class TestUpToDateDatabase:
    def test_boots_and_leaves_the_schema_to_the_migrations(self, monkeypatch, created):
        _revisions(monkeypatch, "dwb581a1b2c3", "dwb581a1b2c3")

        verify_schema(_Sentinel())

        assert created == []


class TestVirginDatabase:
    def test_builds_from_the_models(self, monkeypatch, created):
        # No alembic_version means no migration history to contradict, which
        # is also the path the suite itself takes: conftest builds lat_test
        # with create_all and never runs alembic.
        _revisions(monkeypatch, None, "dwb581a1b2c3")
        engine = _Sentinel()

        verify_schema(engine)

        assert created == [engine]


class TestUnreadableAlembicConfig:
    def test_boots_rather_than_blocking_on_an_unknown_head(
        self, monkeypatch, created
    ):
        # A head we cannot read is not evidence the database is behind, so the
        # guard must not become a boot failure of its own making.
        _revisions(monkeypatch, "dwb581a1b2c3", None)

        verify_schema(_Sentinel())

        assert created == []

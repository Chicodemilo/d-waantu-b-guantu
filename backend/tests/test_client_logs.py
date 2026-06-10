# Path: tests/test_client_logs.py
# File: test_client_logs.py
# Created: 2026-06-10
# Purpose: Tests for /api/client-logs - batch POST (lenient), GET filters, retention enforcement (DWB-371)
# Caller: pytest
# Callees: app/routers/client_logs.py, app/services/client_log.py
# Data In: HTTP requests via TestClient
# Data Out: Assertions on response shape + DB state
# Last Modified: 2026-06-10

"""DWB-371: client-side log feed.

The batch POST is intentionally lenient - a single malformed record must
not reject the whole batch. The GET endpoint supports since/level/category/
route filters with a sane bounded limit. Retention enforced at insert
time, oldest-by-id dropped first."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import client_log as svc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(**overrides) -> dict:
    base = {
        "level": "info",
        "category": "nav",
        "message": "clicked Projects",
        "occurred_at": _now_iso(),
        "route": "/projects",
    }
    base.update(overrides)
    return base


class TestPostClientLogsHappyPath:
    def test_single_record_lands(self, client):
        r = client.post("/api/client-logs", json=[_record()])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["received"] == 1
        assert body["accepted"] == 1
        assert body["rejected"] == 0
        assert body["rejections"] == []

        rows = client.get("/api/client-logs").json()
        assert len(rows) == 1
        assert rows[0]["category"] == "nav"
        assert rows[0]["route"] == "/projects"

    def test_batch_of_many_lands(self, client):
        batch = [_record(category=f"cat{i}", message=f"m{i}") for i in range(10)]
        r = client.post("/api/client-logs", json=batch)
        body = r.json()
        assert body["received"] == 10
        assert body["accepted"] == 10
        assert body["rejected"] == 0

    def test_empty_batch_is_noop(self, client):
        r = client.post("/api/client-logs", json=[])
        body = r.json()
        assert body == {
            "received": 0,
            "accepted": 0,
            "rejected": 0,
            "rejections": [],
            "trimmed": 0,
        }


class TestPostClientLogsLenient:
    def test_batch_with_one_bad_record_keeps_the_good_ones(self, client):
        good1 = _record(category="ok1")
        bad = {"level": "info"}  # missing category, message, occurred_at
        good2 = _record(category="ok2")
        r = client.post("/api/client-logs", json=[good1, bad, good2])
        body = r.json()
        assert body["received"] == 3
        assert body["accepted"] == 2
        assert body["rejected"] == 1
        assert len(body["rejections"]) == 1
        assert body["rejections"][0]["index"] == 1

        # Good ones in DB.
        rows = client.get("/api/client-logs").json()
        categories = {r["category"] for r in rows}
        assert categories == {"ok1", "ok2"}

    def test_invalid_level_rejected_individually(self, client):
        bad_level = _record(level="critical")  # not in enum
        good = _record(category="g")
        r = client.post("/api/client-logs", json=[bad_level, good])
        body = r.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        rows = client.get("/api/client-logs").json()
        assert len(rows) == 1
        assert rows[0]["category"] == "g"

    def test_long_category_rejected(self, client):
        # category max_length=64
        too_long = _record(category="x" * 65)
        r = client.post("/api/client-logs", json=[too_long])
        body = r.json()
        assert body["rejected"] == 1
        assert body["accepted"] == 0


class TestGetClientLogsFilters:
    def test_filter_by_level(self, client):
        client.post("/api/client-logs", json=[
            _record(level="info", category="i"),
            _record(level="error", category="e1"),
            _record(level="error", category="e2"),
        ])
        rows = client.get("/api/client-logs", params={"level": "error"}).json()
        assert len(rows) == 2
        assert {r["category"] for r in rows} == {"e1", "e2"}

    def test_filter_by_category(self, client):
        client.post("/api/client-logs", json=[
            _record(category="nav"),
            _record(category="render"),
            _record(category="nav"),
        ])
        rows = client.get("/api/client-logs", params={"category": "nav"}).json()
        assert len(rows) == 2
        assert all(r["category"] == "nav" for r in rows)

    def test_filter_by_route(self, client):
        client.post("/api/client-logs", json=[
            _record(route="/projects"),
            _record(route="/sprints"),
        ])
        rows = client.get("/api/client-logs", params={"route": "/sprints"}).json()
        assert len(rows) == 1
        assert rows[0]["route"] == "/sprints"

    def test_filter_by_since(self, client, db_session):
        """Records with created_at < since are excluded. created_at is
        server-stamped on insert, so we backdate one row directly."""
        from app.models.client_log import ClientLog

        # Insert via API first so the server stamps created_at.
        client.post("/api/client-logs", json=[_record(message="newer")])
        # Then insert a stale row with backdated created_at.
        stale = ClientLog(
            level="info",
            category="nav",
            message="older",
            occurred_at=datetime.utcnow() - timedelta(hours=2),
            created_at=datetime.utcnow() - timedelta(hours=2),
        )
        db_session.add(stale)
        db_session.commit()

        cutoff = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        rows = client.get(
            "/api/client-logs", params={"since": cutoff}
        ).json()
        msgs = [r["message"] for r in rows]
        assert "newer" in msgs
        assert "older" not in msgs

    def test_limit_bounds(self, client):
        batch = [_record(message=f"m{i}") for i in range(5)]
        client.post("/api/client-logs", json=batch)
        rows = client.get("/api/client-logs", params={"limit": 2}).json()
        assert len(rows) == 2

    def test_limit_rejects_over_1000(self, client):
        # Router-side validation: 1001 -> 422.
        r = client.get("/api/client-logs", params={"limit": 1001})
        assert r.status_code == 422

    def test_most_recent_first(self, client):
        client.post("/api/client-logs", json=[_record(message="first")])
        client.post("/api/client-logs", json=[_record(message="second")])
        client.post("/api/client-logs", json=[_record(message="third")])
        rows = client.get("/api/client-logs").json()
        assert [r["message"] for r in rows[:3]] == ["third", "second", "first"]


class TestClientLogsRetention:
    def test_retention_trims_oldest_beyond_cap(self, client, db_session):
        """Insert 30 with cap=20: 10 oldest dropped, response.trimmed=10."""
        from app.models.client_log import ClientLog
        from sqlalchemy import select

        # Use the service directly so we can pass a small cap.
        raw = [_record(message=f"r{i}") for i in range(30)]
        result = svc.insert_batch(db_session, raw, retention_cap=20)
        assert result["accepted"] == 30
        assert result["trimmed"] == 10

        rows = db_session.scalars(
            select(ClientLog).order_by(ClientLog.id.asc())
        ).all()
        assert len(rows) == 20
        # The surviving rows are r10..r29 (oldest 10 dropped).
        survivors = [row.message for row in rows]
        assert survivors[0] == "r10"
        assert survivors[-1] == "r29"

    def test_cap_zero_disables_trim(self, client, db_session):
        from app.models.client_log import ClientLog
        from sqlalchemy import func, select

        raw = [_record(message=f"x{i}") for i in range(50)]
        result = svc.insert_batch(db_session, raw, retention_cap=0)
        assert result["trimmed"] == 0
        total = db_session.scalar(select(func.count()).select_from(ClientLog))
        assert total == 50

    def test_default_cap_is_10000(self):
        # Sanity-check the documented default so it can't quietly change.
        assert svc.DEFAULT_RETENTION_CAP == 10_000

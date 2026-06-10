# Path: tests/test_server_logs.py
# File: test_server_logs.py
# Created: 2026-06-10
# Purpose: Tests for /api/server-logs ring buffer, handler routing, filter compose, exclusion of noisy loggers, retention bound (DWB-372)
# Caller: pytest
# Callees: app/services/server_log_buffer.py, app/services/server_log_handler.py, app/routers/server_logs.py
# Data In: synthetic LogRecord emissions + HTTP queries
# Data Out: assertions on buffer contents and HTTP responses
# Last Modified: 2026-06-10

"""DWB-372: backend server-log ring buffer.

Design: in-memory deque + lock, populated by a custom logging.Handler
on the root logger. Records from noisy loggers (uvicorn.*, sqlalchemy.*,
starlette.*, alembic.*, httpx, urllib3, etc.) are dropped at the handler
level so the feed surfaces app-level emissions only. Does NOT survive
`uvicorn --reload` - that's the documented trade-off."""

import logging
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services import server_log_buffer
from app.services.server_log_handler import RingBufferHandler, install


@pytest.fixture
def installed_handler():
    """Install the handler fresh and clear the buffer per test so cases
    don't see each other's records. Yields the handler instance so tests
    can detach it cleanly."""
    server_log_buffer.clear()
    handler = install(level=logging.DEBUG)  # DEBUG so tests can emit any level
    yield handler
    logging.getLogger().removeHandler(handler)
    server_log_buffer.clear()


class TestHandlerCapture:
    def test_app_logger_record_lands_in_buffer(self, installed_handler):
        logging.getLogger("app.services.demo").info("hello world")
        records = server_log_buffer.query(limit=10)
        assert len(records) == 1
        assert records[0]["logger_name"] == "app.services.demo"
        assert records[0]["level"] == "INFO"
        assert records[0]["message"] == "hello world"

    def test_warning_and_error_levels_captured(self, installed_handler):
        logging.getLogger("app.X").warning("watch out")
        logging.getLogger("app.X").error("boom")
        levels = [r["level"] for r in server_log_buffer.query(limit=10)]
        assert "WARNING" in levels
        assert "ERROR" in levels

    def test_exception_traceback_captured(self, installed_handler):
        log = logging.getLogger("app.svc")
        try:
            raise ValueError("test error for traceback")
        except ValueError:
            log.exception("oops")
        records = server_log_buffer.query(limit=5)
        assert len(records) == 1
        assert "ValueError" in (records[0]["exc_info"] or "")
        assert "test error for traceback" in (records[0]["exc_info"] or "")

    def test_extra_context_captured(self, installed_handler):
        logging.getLogger("app.svc").info(
            "ticket closed",
            extra={"ticket_key": "DWB-372", "duration_ms": 12},
        )
        records = server_log_buffer.query(limit=5)
        ctx = records[0]["context_json"]
        assert ctx == {"ticket_key": "DWB-372", "duration_ms": 12}

    def test_non_json_extras_get_reprd(self, installed_handler):
        class Weird:
            def __repr__(self):
                return "<Weird>"

        logging.getLogger("app.svc").info(
            "with weird extra", extra={"thing": Weird()}
        )
        ctx = server_log_buffer.query(limit=5)[0]["context_json"]
        assert ctx == {"thing": "<Weird>"}


class TestHandlerExclusion:
    def test_uvicorn_access_excluded(self, installed_handler):
        logging.getLogger("uvicorn.access").info("GET /api/foo 200")
        assert server_log_buffer.size() == 0

    def test_sqlalchemy_engine_excluded(self, installed_handler):
        logging.getLogger("sqlalchemy.engine").info("SELECT 1")
        assert server_log_buffer.size() == 0

    def test_starlette_excluded(self, installed_handler):
        logging.getLogger("starlette.routing").warning("...")
        assert server_log_buffer.size() == 0

    def test_alembic_excluded(self, installed_handler):
        logging.getLogger("alembic.runtime").info("upgrade ok")
        assert server_log_buffer.size() == 0

    def test_app_record_lands_when_noise_excluded(self, installed_handler):
        """Mix excluded + included in the same emit stream: only the app
        record shows up."""
        logging.getLogger("uvicorn.access").info("GET /api/x 200")
        logging.getLogger("sqlalchemy.engine").info("BEGIN")
        logging.getLogger("app.svc").info("real event")
        records = server_log_buffer.query(limit=10)
        assert len(records) == 1
        assert records[0]["message"] == "real event"


class TestBufferRetention:
    def test_ring_buffer_drops_oldest(self):
        server_log_buffer.configure_buffer(maxlen=5)
        try:
            for i in range(10):
                server_log_buffer.append({
                    "logger_name": "test",
                    "level": "INFO",
                    "message": f"m{i}",
                    "created_at": datetime.now(timezone.utc),
                })
            assert server_log_buffer.size() == 5
            records = server_log_buffer.query(limit=10)
            # Most-recent first: m9, m8, m7, m6, m5
            assert [r["message"] for r in records] == [
                "m9", "m8", "m7", "m6", "m5"
            ]
        finally:
            server_log_buffer.configure_buffer(maxlen=2000)

    def test_clear_empties_buffer(self):
        server_log_buffer.append({
            "logger_name": "test",
            "level": "INFO",
            "message": "x",
            "created_at": datetime.now(timezone.utc),
        })
        server_log_buffer.clear()
        assert server_log_buffer.size() == 0


class TestGetServerLogsRouter:
    def test_get_returns_buffered_records(self, client, installed_handler):
        logging.getLogger("app.demo").info("router test 1")
        logging.getLogger("app.demo").info("router test 2")
        r = client.get("/api/server-logs")
        assert r.status_code == 200
        body = r.json()
        # Most-recent first.
        assert body[0]["message"] == "router test 2"
        assert body[1]["message"] == "router test 1"

    def test_filter_by_level(self, client, installed_handler):
        logging.getLogger("app.a").info("an info")
        logging.getLogger("app.a").error("an error")
        body = client.get(
            "/api/server-logs", params={"level": "error"}
        ).json()
        assert all(r["level"] == "ERROR" for r in body)
        assert any(r["message"] == "an error" for r in body)

    def test_filter_by_level_is_case_insensitive(
        self, client, installed_handler
    ):
        logging.getLogger("app.a").warning("hi")
        body = client.get(
            "/api/server-logs", params={"level": "warning"}
        ).json()
        assert len(body) == 1

    def test_filter_by_logger(self, client, installed_handler):
        logging.getLogger("app.foo").info("from foo")
        logging.getLogger("app.bar").info("from bar")
        body = client.get(
            "/api/server-logs", params={"logger": "app.bar"}
        ).json()
        assert len(body) == 1
        assert body[0]["message"] == "from bar"

    def test_filter_by_q_substring(self, client, installed_handler):
        logging.getLogger("app.z").info("connection refused")
        logging.getLogger("app.z").info("ticket closed")
        body = client.get(
            "/api/server-logs", params={"q": "REFUSED"}
        ).json()
        assert len(body) == 1
        assert "refused" in body[0]["message"].lower()

    def test_filter_by_since(self, client, installed_handler):
        logging.getLogger("app.z").info("old")
        time.sleep(0.05)
        cutoff = datetime.now(timezone.utc).isoformat()
        time.sleep(0.05)
        logging.getLogger("app.z").info("new")
        body = client.get(
            "/api/server-logs", params={"since": cutoff}
        ).json()
        msgs = [r["message"] for r in body]
        assert "new" in msgs
        assert "old" not in msgs

    def test_limit_bounds(self, client, installed_handler):
        for i in range(20):
            logging.getLogger("app.z").info(f"m{i}")
        body = client.get(
            "/api/server-logs", params={"limit": 5}
        ).json()
        assert len(body) == 5

    def test_limit_over_1000_rejected(self, client):
        r = client.get("/api/server-logs", params={"limit": 1001})
        assert r.status_code == 422

    def test_filters_compose_with_and(self, client, installed_handler):
        logging.getLogger("app.a").info("apple info")
        logging.getLogger("app.b").info("apple info")
        logging.getLogger("app.a").error("apple error")
        body = client.get(
            "/api/server-logs",
            params={"logger": "app.a", "level": "info"},
        ).json()
        assert len(body) == 1
        assert body[0]["logger_name"] == "app.a"
        assert body[0]["level"] == "INFO"


class TestStatsEndpoint:
    def test_stats_reports_size_and_maxlen(self, client, installed_handler):
        logging.getLogger("app.x").info("a")
        logging.getLogger("app.x").info("b")
        body = client.get("/api/server-logs/stats").json()
        assert body["size"] == 2
        assert body["maxlen"] == 2000  # production default


class TestInstallIdempotent:
    def test_repeated_install_does_not_stack_handlers(
        self, installed_handler
    ):
        """uvicorn --reload would otherwise stack handlers and double-log
        every record. install() must remove prior RingBufferHandlers
        before adding."""
        h1 = installed_handler
        h2 = install(level=logging.DEBUG)
        root = logging.getLogger()
        ring_handlers = [
            h for h in root.handlers if isinstance(h, RingBufferHandler)
        ]
        try:
            assert len(ring_handlers) == 1
            logging.getLogger("app.idem").info("emit once")
            records = server_log_buffer.query(limit=10)
            assert len(records) == 1
        finally:
            root.removeHandler(h2)

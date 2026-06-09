# Path: tests/test_idle_sweeper_task.py
# File: test_idle_sweeper_task.py
# Created: 2026-06-09
# Purpose: Coverage for the asyncio start/stop wiring of the idle sweeper (DWB-337)
# Caller: pytest
# Callees: app.services.idle_sweeper
# Data In: monkeypatched TESTING env, settings.IDLE_SWEEP_INTERVAL_SECONDS
# Data Out: assertions on task creation / cancellation / sweep invocation
# Last Modified: 2026-06-09

"""The async loop is disabled by default in tests (TESTING=1 -> should_run()
returns False). These tests exercise the start/stop helpers directly so we
know the loop wiring works in production:
- TESTING=1 path: start returns None, no task created
- TESTING=0 + interval=0 path: start returns None even outside test mode
- TESTING=0 + interval>0 path: start creates a task, stop cancels it cleanly

The tests drive asyncio explicitly via `asyncio.run` rather than pulling in
pytest-asyncio. Cheap, dependency-free, and self-contained.
"""

import asyncio
from types import SimpleNamespace

from app.config import settings
from app.services import idle_sweeper


def test_start_skipped_when_testing(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    app = SimpleNamespace(state=SimpleNamespace())
    task = asyncio.run(idle_sweeper.start(app))
    assert task is None


def test_start_skipped_when_interval_zero(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr(settings, "IDLE_SWEEP_INTERVAL_SECONDS", 0)
    app = SimpleNamespace(state=SimpleNamespace())
    task = asyncio.run(idle_sweeper.start(app))
    assert task is None


def test_start_and_stop_lifecycle(monkeypatch):
    """End-to-end: enable the sweeper, start the task, give the loop one
    yield slice, then cancel cleanly via stop(). The interval is huge so
    no actual sweep runs (we just verify task plumbing)."""
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr(settings, "IDLE_SWEEP_INTERVAL_SECONDS", 60)

    async def _run() -> tuple[bool, bool]:
        app = SimpleNamespace(state=SimpleNamespace())
        task = await idle_sweeper.start(app)
        assert task is not None
        assert app.state.idle_sweeper_task is task

        # Yield control once so the task can settle into the asyncio.sleep.
        await asyncio.sleep(0)
        task_running = not task.done()

        await idle_sweeper.stop(app)
        task_done = task.done()
        task_cleared = app.state.idle_sweeper_task is None
        return task_running, (task_done and task_cleared)

    running, cleaned = asyncio.run(_run())
    assert running
    assert cleaned

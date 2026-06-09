# Path: app/services/idle_sweeper.py
# File: idle_sweeper.py
# Created: 2026-06-09
# Purpose: Background asyncio task that periodically auto-closes idle DWB sessions (DWB-337)
# Caller: app/main.py lifespan
# Callees: app.services.dwb_session.sweep_idle_sessions, app.database.SessionLocal
# Data In: settings.IDLE_TIMEOUT_MINUTES, settings.IDLE_SWEEP_INTERVAL_SECONDS
# Data Out: idle-closed DwbSession rows
# Last Modified: 2026-06-09

"""Background sweeper for idle DWB sessions.

Implementation choice: plain `asyncio.create_task` driven from FastAPI's
lifespan, not APScheduler.

Reasoning (justify in PR):
  - One periodic task in one process is the entire job. APScheduler adds a
    dependency, a scheduler instance, jobstore config, and a second
    threadpool, all for what is effectively `while True: sleep; sweep`.
  - The asyncio loop is the request loop; an async task with `asyncio.sleep`
    yields control between sweeps and never blocks request handling.
  - DB work is synchronous (SQLAlchemy 2.0 ORM, sync). It's offloaded to a
    thread via `asyncio.to_thread` so the request loop stays responsive
    even if a sweep query slows down.
  - Uvicorn `--reload` kills the worker process on file change, which
    cancels the task; the fresh worker starts a fresh sweeper from lifespan
    startup. No state to persist across reloads — each sweep is idempotent.
  - Tests disable the loop by setting `IDLE_SWEEP_INTERVAL_SECONDS=0` (or
    via the `TESTING` env var) so it never fights with rolled-back
    transactions in the test DB.

Cancellation is cooperative: on lifespan shutdown we call `task.cancel()`
and await it; the task catches `asyncio.CancelledError` from `sleep` and
exits cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app import database
from app.config import settings
from app.services.dwb_session import sweep_idle_sessions

logger = logging.getLogger(__name__)


def _run_one_sweep_sync(idle_minutes: int) -> int:
    """Run one sweep on a dedicated SessionLocal session.

    Lives in its own function (not a closure) so it can be passed to
    `asyncio.to_thread` and so tests can call it directly without an
    asyncio loop.
    """
    db = database.SessionLocal()
    try:
        closed = sweep_idle_sessions(db, idle_minutes=idle_minutes)
        if closed:
            db.commit()
            logger.info("idle sweeper: closed %d DWB session(s)", closed)
        return closed
    except Exception:
        db.rollback()
        # Don't propagate — sweeper must never crash. Log and try again
        # next cycle.
        logger.exception("idle sweeper: sweep failed")
        return 0
    finally:
        db.close()


async def _sweep_loop() -> None:
    """The recurring sweep loop. Sleeps between sweeps; cancels cleanly."""
    interval = settings.IDLE_SWEEP_INTERVAL_SECONDS
    idle_minutes = settings.IDLE_TIMEOUT_MINUTES
    logger.info(
        "idle sweeper started (interval=%ds, idle_minutes=%d)",
        interval,
        idle_minutes,
    )
    try:
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(_run_one_sweep_sync, idle_minutes)
    except asyncio.CancelledError:
        logger.info("idle sweeper cancelled")
        raise


def should_run() -> bool:
    """Skip the sweeper when running tests, or when interval is set to 0."""
    if os.getenv("TESTING") == "1":
        return False
    if settings.IDLE_SWEEP_INTERVAL_SECONDS <= 0:
        return False
    return True


async def start(app) -> asyncio.Task | None:
    """Start the sweeper task and stash it on `app.state.idle_sweeper_task`
    so the lifespan teardown can cancel it. Returns the task (or None when
    skipped) for callers that want to await / inspect it."""
    if not should_run():
        logger.info("idle sweeper disabled (TESTING or interval<=0)")
        return None
    task = asyncio.create_task(_sweep_loop(), name="idle-sweeper")
    app.state.idle_sweeper_task = task
    return task


async def stop(app) -> None:
    """Cancel the sweeper task (if any) and wait for it to exit."""
    task = getattr(app.state, "idle_sweeper_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app.state.idle_sweeper_task = None

# Path: app/services/marker_sweep_task.py
# File: marker_sweep_task.py
# Created: 2026-06-10
# Purpose: Background asyncio task that periodically sweeps stale marker files (DWB-369)
# Caller: app/main.py lifespan
# Callees: app.services.marker_sweeper.sweep_stale_markers, app.database.SessionLocal
# Data In: settings.MARKER_STALE_MINUTES, settings.MARKER_SWEEP_INTERVAL_SECONDS
# Data Out: counts logged per sweep
# Last Modified: 2026-06-10

"""DWB-369: background marker-file sweeper.

Mirrors the idle_sweeper.py pattern (DWB-337) so the two scheduled jobs
share the same lifecycle conventions:

  - Single periodic asyncio task driven from FastAPI lifespan.
  - Synchronous DB work offloaded to ``asyncio.to_thread``.
  - Disabled when interval=0 or TESTING=1 so tests don't fight with
    the rolled-back transaction fixture.
  - Cooperative cancel on shutdown.

Why a separate task vs piggybacking on idle_sweeper: the marker sweep is
filesystem-heavy (one ``iterdir`` per project) and idle-sweep is
DB-heavy. Keeping them independent means a slow filesystem doesn't
block the DB sweep and vice versa. The interval defaults are also
different (idle every 5 min, marker every 10 min) because marker churn
is slow.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app import database
from app.config import settings
from app.services.marker_sweeper import sweep_stale_markers

logger = logging.getLogger(__name__)


def _run_one_sweep_sync(stale_minutes: int) -> dict:
    """Run one marker sweep on a dedicated SessionLocal session."""
    db = database.SessionLocal()
    try:
        counts = sweep_stale_markers(db, stale_minutes=stale_minutes)
        if counts["pending_removed"] or counts["finalized_removed"]:
            logger.info(
                "marker sweeper: pending=%d, finalized=%d, preserved=%d, skipped=%d",
                counts["pending_removed"],
                counts["finalized_removed"],
                counts["preserved_active"],
                counts["skipped"],
            )
        if counts["errors"]:
            logger.warning(
                "marker sweeper: %d non-fatal errors during sweep",
                len(counts["errors"]),
            )
        return counts
    except Exception:
        db.rollback()
        # Mirror idle_sweeper: never propagate, never crash the loop.
        logger.exception("marker sweeper: sweep failed")
        return {}
    finally:
        db.close()


async def _sweep_loop() -> None:
    interval = settings.MARKER_SWEEP_INTERVAL_SECONDS
    stale_minutes = settings.MARKER_STALE_MINUTES
    logger.info(
        "marker sweeper started (interval=%ds, stale_minutes=%d)",
        interval, stale_minutes,
    )
    try:
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(_run_one_sweep_sync, stale_minutes)
    except asyncio.CancelledError:
        logger.info("marker sweeper cancelled")
        raise


def should_run() -> bool:
    if os.getenv("TESTING") == "1":
        return False
    if settings.MARKER_SWEEP_INTERVAL_SECONDS <= 0:
        return False
    return True


async def start(app) -> asyncio.Task | None:
    if not should_run():
        logger.info("marker sweeper disabled (TESTING or interval<=0)")
        return None
    task = asyncio.create_task(_sweep_loop(), name="marker-sweeper")
    app.state.marker_sweeper_task = task
    return task


async def stop(app) -> None:
    task = getattr(app.state, "marker_sweeper_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app.state.marker_sweeper_task = None

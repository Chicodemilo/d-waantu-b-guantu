# Path: app/main.py
# File: main.py
# Created: 2026-03-29
# Purpose: FastAPI app initialization, CORS, activity logging middleware, and router registration
# Caller: uvicorn entrypoint
# Callees: All routers, app/database.py
# Data In: None
# Data Out: FastAPI app instance
# Last Modified: 2026-06-09

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import Base, engine
from app.middleware.activity_logger import ActivityLoggerMiddleware
from app.middleware.error_logger import ErrorLoggerMiddleware
from app.routers import (
    activity_logs,
    agents,
    alerts,
    comments,
    dwb_sessions,
    epics,
    errors,
    failure_records,
    hooks,
    instructions,
    jira,
    playbooks,
    project_agents,
    projects,
    sprints,
    status,
    test_results,
    tickets,
    tokens,
    tracking,
)
from app.services import idle_sweeper, marker_sweep_task
from app.services.failed_hook import log_failed_hook


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await idle_sweeper.start(app)
    # DWB-369: marker sweeper - cleans pending-* files whose worker died
    # pre-SubagentStop, plus finalized markers tied to completed
    # hook_sessions. Independent lifecycle from the idle sweeper.
    await marker_sweep_task.start(app)
    try:
        yield
    finally:
        await marker_sweep_task.stop(app)
        await idle_sweeper.stop(app)


app = FastAPI(title="Local Agent Tracker", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def hook_payload_validation_handler(request: Request, exc: RequestValidationError):
    """Default 422 handler, plus side-effect: persist a FailedHook row when the
    invalid request hit a hook endpoint. Stops silent hook payload-parse fails."""
    if request.url.path.startswith("/api/hooks/"):
        try:
            raw = await request.body()
        except Exception:
            raw = None
        log_failed_hook(
            hook_event=request.url.path.rsplit("/", 1)[-1],
            status_code=422,
            raw_payload=raw,
            error=f"RequestValidationError: {exc.errors()}",
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

if os.getenv("TESTING") != "1":
    app.add_middleware(ActivityLoggerMiddleware)
    app.add_middleware(ErrorLoggerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(sprints.router)
app.include_router(epics.router)
app.include_router(agents.router)
app.include_router(project_agents.router)
app.include_router(tickets.router)
app.include_router(comments.router)
app.include_router(alerts.router)
app.include_router(instructions.router)
app.include_router(activity_logs.router)
app.include_router(test_results.router)
app.include_router(playbooks.router)
app.include_router(tokens.router)
app.include_router(failure_records.router)
app.include_router(tracking.router)
app.include_router(hooks.router)
app.include_router(errors.router)
app.include_router(status.router)
app.include_router(jira.router)
app.include_router(dwb_sessions.router)
app.include_router(dwb_sessions.project_sessions_router)

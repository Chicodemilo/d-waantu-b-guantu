# Path: app/main.py
# File: main.py
# Created: 2026-03-29
# Purpose: FastAPI app initialization, CORS, activity logging middleware, and router registration
# Caller: uvicorn entrypoint
# Callees: All routers, app/database.py
# Data In: None
# Data Out: FastAPI app instance
# Last Modified: 2026-03-29

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.middleware.activity_logger import ActivityLoggerMiddleware
from app.routers import (
    activity_logs,
    agents,
    alerts,
    comments,
    epics,
    failure_records,
    instructions,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Local Agent Tracker", lifespan=lifespan)

if os.getenv("TESTING") != "1":
    app.add_middleware(ActivityLoggerMiddleware)
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
app.include_router(status.router)

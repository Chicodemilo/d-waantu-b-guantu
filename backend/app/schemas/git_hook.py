# Path: app/schemas/git_hook.py
# File: git_hook.py
# Created: 2026-06-10
# Purpose: Pydantic schemas for the post-commit git hook endpoint (DWB-345)
# Caller: app/routers/hooks.py
# Callees: pydantic
# Data In: HTTP request body / service result dict
# Data Out: PostCommitRequest, PostCommitResponse
# Last Modified: 2026-06-10

from pydantic import BaseModel, Field


class PostCommitRequest(BaseModel):
    repo_path: str = Field(..., description="Absolute path of the repository the commit landed in")
    commit_message: str = Field(..., description="Full commit message body")
    commit_sha: str = Field(..., description="Commit SHA (full or short)")


class ClosedEntry(BaseModel):
    ticket_key: str
    ticket_id: int
    prior_status: str


class SkippedEntry(BaseModel):
    ticket_key: str
    ticket_id: int
    status: str
    reason: str


class PostCommitResponse(BaseModel):
    project_id: int | None = None
    project_prefix: str | None = None
    commit_sha: str
    closed: list[ClosedEntry] = []
    skipped: list[SkippedEntry] = []
    unknown: list[str] = []
    reason: str | None = None

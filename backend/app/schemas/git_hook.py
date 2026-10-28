# Path: app/schemas/git_hook.py
# File: git_hook.py
# Created: 2026-06-10
# Purpose: Pydantic schemas for the post-commit git hook endpoint (DWB-345)
# Caller: app/routers/hooks.py
# Callees: pydantic
# Data In: HTTP request body / service result dict
# Data Out: PostCommitRequest, PostCommitResponse
# Last Modified: 2026-10-28 (DWB-695: optional branch, the one field git cannot recover later)

from pydantic import BaseModel, ConfigDict, Field


class PostCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # DWB-651

    repo_path: str = Field(..., description="Absolute path of the repository the commit landed in")
    commit_message: str = Field(..., description="Full commit message body")
    commit_sha: str = Field(..., description="Commit SHA (full or short)")
    # DWB-695. OPTIONAL, and it is the only new field, because everything else
    # the commit row stores is read back out of the repository by the server -
    # which is why the shipped hook did not have to change and an older hook
    # still works against this endpoint unmodified.
    #
    # Branch is the exception: a branch pointer moves, so asking git later
    # which branches contain a commit answers a different question than which
    # branch was checked out when it landed. It is knowable only at commit
    # time, so it can only arrive from the hook. Absent means NOT REPORTED.
    branch: str | None = Field(
        None, description="Branch checked out when the commit landed, if the hook reports it"
    )


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

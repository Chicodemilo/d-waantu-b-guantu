# Path: app/schemas/repo_browse.py
# File: repo_browse.py
# Created: 2026-09-15
# Purpose: Pydantic response schemas for the read-only repo directory browser (DWB-553).
# Caller: app/routers/repo_browse.py
# Callees: pydantic
# Data In: repo_browse.list_directories dict
# Data Out: RepoDirectoryListing
# Last Modified: 2026-09-15

from pydantic import BaseModel


class RepoDirectory(BaseModel):
    """One child directory. ``path`` is repo-relative and is what the caller
    sends back as ``parent`` to descend, or stores as an exclusion pattern."""

    name: str
    path: str


class RepoDirectoryListing(BaseModel):
    """One level of the tree. ``parent`` echoes the normalized request so a
    client can render a breadcrumb without re-deriving it."""

    parent: str
    directories: list[RepoDirectory] = []

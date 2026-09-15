# Path: app/schemas/node_exclusion.py
# File: node_exclusion.py
# Created: 2026-09-15
# Purpose: Pydantic schemas for the per-project node-scan exclusion API (DWB-549).
# Caller: app/routers/node_exclusions.py
# Callees: pydantic
# Data In: POST body {pattern}; NodeExclusion ORM rows
# Data Out: NodeExclusionRead
# Last Modified: 2026-09-15

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NodeExclusionCreate(BaseModel):
    """Add one exclusion. Repo-relative path or glob; absolute paths and paths
    escaping the repo root are refused with a 400 naming why."""

    pattern: str


class NodeExclusionRead(BaseModel):
    """One stored exclusion row. Seeded defaults are ordinary rows and are not
    marked or protected in any way."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    pattern: str
    created_at: datetime

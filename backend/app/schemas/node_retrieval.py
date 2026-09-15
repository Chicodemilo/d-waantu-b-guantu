# Path: app/schemas/node_retrieval.py
# File: node_retrieval.py
# Created: 2026-09-14
# Purpose: Pydantic response schemas for the retrieval-into-work lane (DWB-524):
#          the ticket related-nodes surface (lessons / sessions / code file refs).
#          Pointers only - never node/memory content.
# Caller: app/routers/tickets.py
# Callees: pydantic
# Data In: node_retrieval.related_nodes dict
# Data Out: RelatedNodesResponse
# Last Modified: 2026-09-14

from pydantic import BaseModel


class LessonRef(BaseModel):
    tag: str
    weight: int
    source_agent: str | None = None
    memory_ref: str
    entry_heading: str | None = None
    date: str | None = None


class SessionRef(BaseModel):
    tag: str
    weight: int
    ref: str


class CodeRef(BaseModel):
    tag: str
    weight: int
    kind: str
    ref: str
    sha: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class RelatedNodesResponse(BaseModel):
    query_tags: list[str] = []
    lessons: list[LessonRef] = []
    sessions: list[SessionRef] = []
    code: list[CodeRef] = []

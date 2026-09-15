# Path: app/services/node_exclusion.py
# File: node_exclusion.py
# Created: 2026-09-15
# Purpose: Per-project node-scan exclusions (DWB-549): seed the shipped defaults once as ordinary deletable rows, read the active pattern list for the grounding lanes, and add/delete rows for the CRUD endpoints.
# Caller: app/routers/node_exclusions.py, app/services/code_pointers.py, app/services/doc_pointers.py
# Callees: app/models/node_exclusion.py, app/models/project.py, app/config/node_scan.py (seed defaults)
# Data In: db: Session, project_id, user-supplied pattern
# Data Out: NodeExclusion rows; tuple[str, ...] of active patterns
# Last Modified: 2026-09-15

"""The exclusion list a project actually scans by (DWB-549).

Seeding is ONCE PER PROJECT, tracked by ``project.node_exclusions_seeded``
rather than by "does this project have zero rows". The difference matters: a
user who deletes every default must end up with an empty list, and inferring
from emptiness would re-add the defaults on the next read and silently undo the
deletion. Seeded rows are ordinary rows - nothing downstream knows or cares
which ones came from the shipped list.

A project with no rows excludes nothing, which is exactly the pre-DWB-549
behaviour.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.node_scan import DEFAULT_NODE_SCAN_EXCLUDES
from app.models.node_exclusion import NodeExclusion
from app.models.project import Project

logger = logging.getLogger(__name__)


class InvalidExclusionPattern(ValueError):
    """A pattern a user may not store. Carries the reason, which the router
    hands back verbatim in the 400 so the message names what was wrong."""


def validate_pattern(pattern: str) -> str:
    """Normalize a user-supplied pattern, or raise InvalidExclusionPattern.

    Patterns are REPO-RELATIVE because that is the shape of a pointer ref: what
    a user sees in the manager is what the matcher compares. Absolute paths and
    anything climbing out of the repo root are refused rather than silently
    rewritten, so a user is never told a rule was stored that would not match
    what they typed.

    Lives here rather than in app/config/node_scan.py: that module owns the
    matcher and the seed defaults and nothing else, and validation is a property
    of what may be PERSISTED, which is this service's business.
    """
    raw = (pattern or "").strip()
    if not raw:
        raise InvalidExclusionPattern("pattern must not be empty")
    if len(raw) > 500:
        raise InvalidExclusionPattern("pattern must be 500 characters or fewer")

    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~"):
        raise InvalidExclusionPattern(
            f"pattern must be repo-relative, not absolute: {raw!r}"
        )
    # Windows drive letters ("C:/x") are absolute too.
    if len(normalized) > 1 and normalized[1] == ":":
        raise InvalidExclusionPattern(
            f"pattern must be repo-relative, not absolute: {raw!r}"
        )
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if ".." in normalized.split("/"):
        raise InvalidExclusionPattern(
            f"pattern must not escape the repo root: {raw!r}"
        )
    if not normalized:
        raise InvalidExclusionPattern("pattern must not be empty")
    return normalized


class NodeExclusionError(Exception):
    """Coded failure the router maps to a status (400 / 404 / 409)."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def ensure_seeded(db: Session, project: Project) -> int:
    """Seed the shipped defaults for a project that has never been seeded.

    Returns the number of rows written (0 when already seeded). Flips the
    project flag so this never runs twice, which is what makes deleting a
    default permanent. Does NOT commit - the caller owns the transaction.
    """
    if project.node_exclusions_seeded:
        return 0

    existing = set(
        db.scalars(
            select(NodeExclusion.pattern).where(
                NodeExclusion.project_id == project.id
            )
        ).all()
    )
    written = 0
    for pattern in DEFAULT_NODE_SCAN_EXCLUDES:
        if pattern in existing:
            continue
        db.add(NodeExclusion(project_id=project.id, pattern=pattern))
        written += 1
    project.node_exclusions_seeded = True
    db.flush()
    logger.info(
        "seeded %s node-scan exclusion defaults for project %s", written, project.id
    )
    return written


def list_exclusions(
    db: Session, project_id: int, *, autoseed: bool = True
) -> list[NodeExclusion]:
    """A project's exclusion rows, oldest first. Seeds the defaults on first use
    unless ``autoseed`` is off. Raises NodeExclusionError('project_not_found')."""
    project = db.get(Project, project_id)
    if project is None:
        raise NodeExclusionError("project_not_found", f"Project {project_id} not found")
    if autoseed:
        ensure_seeded(db, project)
    return list(
        db.scalars(
            select(NodeExclusion)
            .where(NodeExclusion.project_id == project_id)
            .order_by(NodeExclusion.created_at.asc(), NodeExclusion.id.asc())
        ).all()
    )


def patterns_for_project(
    db: Session, project_id: int, *, autoseed: bool = True
) -> tuple[str, ...]:
    """The active pattern list for the grounding lanes.

    Seeds on first use so the first scan of a fresh project applies the shipped
    defaults, then never again. Best-effort: any failure returns an EMPTY tuple
    so a broken exclusion list degrades to "index everything" rather than
    silently dropping a project's whole index.
    """
    if project_id is None:
        # A caller with no project identity (a bare provider stub in a unit
        # test, say) gets no exclusions rather than an AttributeError.
        return ()
    try:
        rows = list_exclusions(db, project_id, autoseed=autoseed)
    except NodeExclusionError:
        return ()
    except Exception:  # noqa: BLE001 - grounding must never die on this
        logger.warning(
            "node exclusion lookup failed for project %s; scanning everything",
            project_id, exc_info=True,
        )
        return ()
    return tuple(r.pattern for r in rows)


def add_exclusion(db: Session, project_id: int, pattern: str) -> NodeExclusion:
    """Validate and store one pattern. Raises NodeExclusionError with code
    'invalid_pattern' (400), 'project_not_found' (404) or 'duplicate' (409)."""
    project = db.get(Project, project_id)
    if project is None:
        raise NodeExclusionError("project_not_found", f"Project {project_id} not found")

    try:
        normalized = validate_pattern(pattern)
    except ValueError as e:
        raise NodeExclusionError("invalid_pattern", str(e)) from e

    # Seed before adding so a user's first manual entry does not suppress the
    # defaults they never saw.
    ensure_seeded(db, project)

    existing = db.scalars(
        select(NodeExclusion).where(
            NodeExclusion.project_id == project_id,
            NodeExclusion.pattern == normalized,
        )
    ).first()
    if existing is not None:
        raise NodeExclusionError(
            "duplicate", f"pattern already excluded for this project: {normalized!r}"
        )

    row = NodeExclusion(project_id=project_id, pattern=normalized)
    db.add(row)
    db.flush()
    return row


def delete_exclusion(db: Session, project_id: int, exclusion_id: int) -> None:
    """Delete one row. Deletion is permanent: the seeded flag is already set, so
    a removed default is never re-added. Raises 'not_found'."""
    row = db.get(NodeExclusion, exclusion_id)
    if row is None or row.project_id != project_id:
        raise NodeExclusionError(
            "not_found",
            f"exclusion {exclusion_id} not found for project {project_id}",
        )
    db.delete(row)
    db.flush()

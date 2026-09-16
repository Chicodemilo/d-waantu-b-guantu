# Path: app/services/node_exclusion.py
# File: node_exclusion.py
# Created: 2026-09-15
# Purpose: Per-project node-scan exclusions (DWB-549): seed the shipped defaults once as ordinary deletable rows, read the active pattern list for the grounding lanes, and add/delete rows for the CRUD endpoints.
# Caller: app/routers/node_exclusions.py, app/services/code_pointers.py, app/services/doc_pointers.py
# Callees: app/models/node_exclusion.py, app/models/project.py, app/config/node_scan.py (seed defaults)
# Data In: db: Session, project_id, user-supplied pattern
# Data Out: NodeExclusion rows; tuple[str, ...] of active patterns
# Last Modified: 2026-09-16 (DWB-567: serialize first-view seeding on the project row; read through the lock so a race loser returns the real list)

"""The exclusion list a project actually scans by (DWB-549).

Seeding is ONCE PER PROJECT, tracked by ``project.node_exclusions_seeded``
rather than by "does this project have zero rows". The difference matters: a
user who deletes every default must end up with an empty list, and inferring
from emptiness would re-add the defaults on the next read and silently undo the
deletion. Seeded rows are ordinary rows - nothing downstream knows or cares
which ones came from the shipped list.

A project with no rows excludes nothing, which is exactly the pre-DWB-549
behaviour.

CONCURRENCY (DWB-567). Seeding is a read-check-write, and the first-ever view of
a project is the window where two requests can run it at once. The existence
pre-read does NOT close that window: under REPEATABLE READ it sees committed
rows only, so two first views both read "nothing seeded" and both insert, and
the loser dies on uq_node_exclusions_project_pattern.

Two things follow, and the second is the one that is easy to miss:

1. Would-be seeders serialize on an exclusive lock on the PROJECT row, taken
   before the flag is re-checked. Only one transaction can be inside the seed at
   a time, so the duplicate insert never happens - the conflict is removed
   rather than recovered from, and nothing here catches IntegrityError.
2. A transaction that entered on a first view has a read view that PREDATES the
   winner's commit, so its ordinary reads cannot see the winner's rows even
   after the winner commits. Rolling back to a savepoint does not refresh it
   either (measured, not assumed). So on that path the rows are read THROUGH
   THE LOCK, which reads the latest committed data. Without this, the loser
   stops returning a 500 and starts returning an empty list instead, which is
   worse: for patterns_for_project an empty list means "index everything".
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

    Returns the number of rows written: 0 when already seeded, and also 0 when a
    concurrent request seeded it while we waited for the lock. Flips the project
    flag so this never runs twice, which is what makes deleting a default
    permanent. Does NOT commit - the caller owns the transaction.

    Callers that entered while the project looked unseeded must read the rows
    back through a lock; see ``_exclusion_rows`` and the module docstring.
    """
    if project.node_exclusions_seeded:
        # Fast path for every view after the first: no lock, no extra query.
        return 0

    # Slow path, reached only on a project's first view. Take the project row
    # exclusively BEFORE re-checking the flag, so concurrent first views queue
    # here instead of racing into duplicate inserts. populate_existing refreshes
    # the flag from the locking read; without it the stale value already loaded
    # in this session's identity map would be reused and the check would pass
    # for both racers, which is the bug in a new costume.
    locked = db.scalars(
        select(Project)
        .where(Project.id == project.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if locked is None or locked.node_exclusions_seeded:
        # Either the project vanished, or we lost the race and the winner has
        # already committed the defaults. Nothing to write in either case.
        return 0

    # Read the already-present patterns through the lock too. A plain read here
    # would use this transaction's stale snapshot and could miss a committed
    # row, putting the duplicate insert right back.
    existing = set(
        db.scalars(
            select(NodeExclusion.pattern)
            .where(NodeExclusion.project_id == project.id)
            .with_for_update()
        ).all()
    )
    written = 0
    for pattern in DEFAULT_NODE_SCAN_EXCLUDES:
        if pattern in existing:
            continue
        db.add(NodeExclusion(project_id=project.id, pattern=pattern))
        written += 1
    locked.node_exclusions_seeded = True
    db.flush()
    logger.info(
        "seeded %s node-scan exclusion defaults for project %s", written, project.id
    )
    return written


def _exclusion_rows(
    db: Session, project_id: int, *, through_lock: bool
) -> list[NodeExclusion]:
    """This project's rows, oldest first.

    ``through_lock`` is set only on a first view, where this transaction's read
    view may predate a concurrent seeder's commit. A shared locking read returns
    the latest committed rows instead of that snapshot, which is what makes the
    race loser return the real list rather than an empty one. Every later view
    takes the plain read and no lock.
    """
    stmt = (
        select(NodeExclusion)
        .where(NodeExclusion.project_id == project_id)
        .order_by(NodeExclusion.created_at.asc(), NodeExclusion.id.asc())
    )
    if through_lock:
        stmt = stmt.with_for_update(read=True)
    return list(db.scalars(stmt).all())


def list_exclusions(
    db: Session, project_id: int, *, autoseed: bool = True
) -> list[NodeExclusion]:
    """A project's exclusion rows, oldest first. Seeds the defaults on first use
    unless ``autoseed`` is off. Raises NodeExclusionError('project_not_found')."""
    project = db.get(Project, project_id)
    if project is None:
        raise NodeExclusionError("project_not_found", f"Project {project_id} not found")
    # Sampled BEFORE seeding: a project that looks unseeded to this transaction
    # is on its first view, the only window in which another request can seed
    # underneath us and leave our snapshot behind.
    first_view = autoseed and not project.node_exclusions_seeded
    if autoseed:
        ensure_seeded(db, project)
    return _exclusion_rows(db, project_id, through_lock=first_view)


def patterns_for_project(
    db: Session, project_id: int, *, autoseed: bool = True
) -> tuple[str, ...]:
    """The active pattern list for the grounding lanes.

    Seeds on first use so the first scan of a fresh project applies the shipped
    defaults, then never again. Best-effort: any failure returns an EMPTY tuple
    so a broken exclusion list degrades to "index everything" rather than
    silently dropping a project's whole index.

    DWB-567: that fallback made the seeding race silent here rather than loud.
    The IntegrityError raised by a losing seeder is not a NodeExclusionError, so
    it fell through to the blanket except below and this returned (), and a scan
    racing a first view indexed the excluded paths with nothing in the log but a
    warning. The fix is upstream - the race no longer produces an exception, and
    a losing reader gets the real list - so the fallback is back to meaning what
    it says: a genuinely broken lookup, not a busy one.
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
    first_view = not project.node_exclusions_seeded
    ensure_seeded(db, project)

    # On a first view the duplicate check has the same stale-snapshot exposure
    # as the list read: without the lock it could miss a pattern a concurrent
    # seeder just committed and turn a clean 409 into a 500 on the insert.
    dup_stmt = select(NodeExclusion).where(
        NodeExclusion.project_id == project_id,
        NodeExclusion.pattern == normalized,
    )
    if first_view:
        dup_stmt = dup_stmt.with_for_update(read=True)
    existing = db.scalars(dup_stmt).first()
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

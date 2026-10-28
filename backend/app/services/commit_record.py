# Path: app/services/commit_record.py
# File: commit_record.py
# Created: 2026-10-28
# Purpose: Persist git commit rows (DWB-695) + the data-availability floor any commit-based detector must respect
# Caller: app/routers/hooks.py (post-commit endpoint)
# Callees: app/models/commit.Commit, app/services/code_pointers (commit_metadata, commit_paths, resolve_full_sha), app/services/git_hook._parse_ticket_keys
# Data In: db: Session, project, repo_path, commit_sha, commit_message, branch
# Data Out: Commit row (or None), coverage datetime, coverage boolean
# Last Modified: 2026-10-28

"""DWB-695: the commit rows DWB has never had, and the floor that stops them
being misread the day they exist.

WHAT THIS IS NOT. It scores nothing and no detector reads it. Measured on this
repo before it was built: 420 of 614 done tickets on project 1 have no commit
carrying their key - 68.4%. A detector keyed on raw key-absence would penalise
two thirds of all completed work, so persisting the data and deciding what it
means are deliberately separate tickets.

THE SERVER READS THE REPOSITORY RATHER THAN TRUSTING THE PAYLOAD, which is why
the shipped hook did not have to change and an old hook still works unmodified.
Everything except the branch is recoverable from `repo_path` + `sha`:
timestamps, author, message, touched paths. That also means this same function
can backfill history - all 284 commits on this repo are still readable - so the
table can be populated for any clone that reaches the machine, not only for
commits made after a hook is armed.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.commit import Commit
from app.models.project import Project
from app.services import code_pointers

logger = logging.getLogger(__name__)


def _naive_utc(value: datetime | None) -> datetime | None:
    """Strip tzinfo after converting to UTC.

    The column is a naive DateTime like every other timestamp in this schema,
    and git hands back tz-aware values from %aI/%cI. Converting rather than
    merely dropping tzinfo matters: a commit authored at 09:30-05:00 is 14:30
    UTC, and discarding the offset would store a time five hours wrong and
    silently shift every window comparison a detector later makes.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    from datetime import UTC

    return value.astimezone(UTC).replace(tzinfo=None)


def record_commit(
    db: Session,
    *,
    project: Project,
    repo_path: str,
    commit_sha: str,
    commit_message: str | None = None,
    branch: str | None = None,
) -> Commit | None:
    """Persist one commit for a project. Idempotent per (project_id, sha).

    Returns the row (new or pre-existing), or None when the sha cannot be
    resolved against the repository - which is the honest outcome for a hook
    firing from a path that is not a readable git work tree. Never raises:
    the caller is the post-commit hook lane, whose contract is to always
    return 200 and never block a commit.

    THE SHA IS EXPANDED BEFORE STORING. The hook sends whatever
    `git rev-parse HEAD` gave it, but a backfill or a human caller may pass a
    short sha, and the unique constraint compares strings - so an unexpanded
    short sha would create a SECOND row for a commit already stored at full
    length, and the duplicate would look like two commits to anything counting.

    IDEMPOTENCE RESTS ON THE CONSTRAINT, NOT ON THE PRE-CHECK. The SELECT below
    is an optimisation that avoids a pointless INSERT in the common re-fire
    case; the IntegrityError branch is what makes two concurrent writers safe.
    A pre-check alone is a race, and this path can be re-entered by a hook
    retry and a backfill at the same time.
    """
    try:
        if not code_pointers._repo_ok(repo_path):
            return None

        full_sha = code_pointers.resolve_full_sha(repo_path, commit_sha)
        if not full_sha:
            # Not a commit this repository knows. Nothing honest to store.
            return None

        existing = db.scalar(
            select(Commit).where(
                Commit.project_id == project.id,
                Commit.commit_sha == full_sha,
            )
        )
        if existing is not None:
            return existing

        meta = code_pointers.commit_metadata(repo_path, full_sha) or {}
        # Parsed by the SAME function that drives the auto-close, imported
        # rather than re-implemented, so the stored keys can never disagree
        # with the keys that actually closed tickets.
        from app.services.git_hook import _parse_ticket_keys

        keys = (
            _parse_ticket_keys(commit_message, project.prefix)
            if commit_message
            else []
        )

        row = Commit(
            project_id=project.id,
            commit_sha=full_sha,
            authored_at=_naive_utc(meta.get("authored_at")),
            committed_at=_naive_utc(meta.get("committed_at")),
            author_name=meta.get("author_name"),
            author_email=meta.get("author_email"),
            message=commit_message,
            branch=branch,
            changed_paths=code_pointers.commit_paths(repo_path, full_sha),
            ticket_keys=keys,
        )
        try:
            # SAVEPOINT, NOT db.rollback(). A bare rollback here would unwind
            # the CALLER's transaction - under the test harness that is the
            # outer transaction the whole test runs in, so losing a race would
            # destroy unrelated work and surface somewhere else entirely.
            # begin_nested confines the undo to this insert.
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            # Lost the race to a concurrent writer; theirs is as good as ours.
            return db.scalar(
                select(Commit).where(
                    Commit.project_id == project.id,
                    Commit.commit_sha == full_sha,
                )
            )
        return row
    except Exception:
        logger.exception(
            "record_commit failed for project_id=%s sha=%s", project.id, commit_sha
        )
        return None


def coverage_start(db: Session, project_id: int) -> datetime | None:
    """The earliest commit DWB holds for a project, or None if it holds none.

    This is the DATA-AVAILABILITY FLOOR, and it is the reason this function
    exists in the same ticket as the table rather than in the detector's.

    Before this table, "no commit references this ticket" was true of every
    ticket ever closed, because no commit was ever stored. Any detector that
    does not consult a floor would therefore fire on all of history on its
    first run - 420 of 614 done tickets on project 1 today - and every one of
    those findings would be an artefact of when the table was created rather
    than a fact about the work.

    Returns None when nothing is stored. A caller must read None as "CANNOT
    ANSWER", never as "no commits exist": the unarmed state and the
    nothing-to-report state are indistinguishable from inside DWB, which is the
    defect this whole lane is about.
    """
    return db.scalar(
        select(Commit.committed_at)
        .where(Commit.project_id == project_id, Commit.committed_at.isnot(None))
        .order_by(Commit.committed_at.asc())
        .limit(1)
    )


def within_commit_coverage(
    db: Session, project_id: int, when: datetime | None
) -> bool:
    """True only when `when` falls inside the window DWB has commit data for.

    The predicate a commit-absence detector must pass before it is entitled to
    conclude anything about a ticket. False when there is no data at all, and
    False for anything that happened before the first commit DWB holds.

    FALSE ON NO DATA IS THE SAFE DIRECTION, deliberately: the failure this
    guards against is concluding "nobody committed" from "nobody told us", and
    those two answer a naive check identically. A `None` timestamp is likewise
    False - a ticket with no close time cannot be placed inside any window, and
    guessing would put the artefact back.
    """
    if when is None:
        return False
    start = coverage_start(db, project_id)
    if start is None:
        return False
    return when >= start

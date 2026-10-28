# Path: app/models/commit.py
# File: commit.py
# Created: 2026-10-28
# Purpose: Commit ORM model - the persisted git commit row (DWB-695), precondition for any bypassed-ticket / no-commit detection
# Caller: app/services/commit_record.py, app/routers/hooks.py (post-commit)
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Commit
# Last Modified: 2026-10-28

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Commit(Base):
    """One git commit, as seen by the post-commit hook.

    DWB-695. Until this existed, `git_hook.process_post_commit` closed tickets
    from commit messages and stored nothing, so "this ticket was closed with no
    commit referencing it" was unanswerable - `scoring_triggers._forgot_reasons`
    names that gap in a comment.

    THIS MODEL SCORES NOTHING AND IS READ BY NO DETECTOR. That is deliberate.
    Measured on this repo before it was built: 420 of 614 done tickets have no
    commit carrying their key (68.4%), so a detector keyed on raw key-absence
    would penalise two thirds of completed work. Persisting the data and
    deciding what it means are separate tickets on purpose.

    Rows are written by the hook lane and are idempotent per
    (project_id, commit_sha): see `commit_record.record_commit`.
    """

    __tablename__ = "commits"
    __table_args__ = (
        # Per PROJECT, not global: two projects can be clones of one
        # repository, and the same commit legitimately exists in both.
        UniqueConstraint("project_id", "commit_sha", name="uq_commits_project_sha"),
        Index("ix_commits_project_committed_at", "project_id", "committed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False
    )

    # Always the FULL 40-char sha. The hook may send a short one; the service
    # expands it against the repository before storing, so two reports of one
    # commit at different abbreviation lengths collapse onto the same row
    # rather than racing the unique constraint as different values.
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)

    # SEPARATE ON PURPOSE. A rebase or amend moves one and not the other, and
    # a future time-window discriminator ("was there a commit inside this
    # ticket's in_progress window") is only as correct as the choice between
    # them. One column would foreclose that choice permanently.
    authored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The one field that cannot be recovered after the fact, which is why it
    # comes from the payload rather than from the repository: a branch pointer
    # moves, so asking git later which branches contain a commit answers a
    # different question than which branch was checked out when it landed.
    # NULL means NOT REPORTED, never "no branch".
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Every path the commit touched, INCLUDING deletions - see
    # `code_pointers.commit_paths` for why that differs from `commit_files`.
    # JSON rather than a child table: nothing joins on an individual path, the
    # only consumer is a set intersection, and a child table would cost a
    # second write per commit for a query nobody has.
    changed_paths: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Denormalised parse of the message, by the SAME function the auto-close
    # path uses, so the stored keys can never disagree with the keys that
    # actually closed tickets.
    ticket_keys: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

# Path: app/models/standards_audit.py
# File: standards_audit.py
# Created: 2026-08-11 (DWB-014)
# Purpose: StandardsAudit ORM model - one recorded PR standards audit (verdict +
#          violations + per-agent scorecard). Storage only; applying the
#          scorecard to reputations is DWB-016's job, which consumes the
#          scorecard JSON shaped here.
# Caller: app/services/standards_audit.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: StandardsAudit, AuditVerdict
# Last Modified: 2026-08-11 (DWB-014)
#
# Violations + scorecard are stored as JSON columns (not a child audit_violation
# table). Per Archie's recon on DWB-014: we do not query individual violations
# relationally - an audit is read as a whole document (verdict + its violations +
# its scorecard). JSON keeps the write atomic and the read a single row. If a
# future ticket needs to query violations across audits, promote violations to a
# child table then.
#   - violations JSON: list of {rule, file, line, note, severity}
#   - scorecard JSON:  list of {agent, delta, reason} - DWB-016 reads this to
#     apply per-agent carrots/sticks.
# `details` is MEDIUMTEXT (mirrors test_result.details, DWB-308) so a large raw
# diff / auditor output does not overflow TEXT's 64KB cap and 500 the POST.

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.sprint import Sprint
    from app.models.ticket import Ticket


class AuditVerdict(str, enum.Enum):
    """Outcome of a PR standards audit. Values are the API-facing strings
    (``pass`` / ``reject``); member names avoid the ``pass`` keyword."""

    passed = "pass"
    rejected = "reject"


class StandardsAudit(Base):
    """One immutable record of a PR standards audit.

    project_id is required; sprint_id / ticket_id are nullable so an audit can
    be recorded before it is tied to a specific sprint or ticket. Verdict is a
    two-value enum. Violations and the per-agent scorecard are JSON documents
    (see module header for the child-table-vs-JSON rationale).
    """

    __tablename__ = "standards_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    sprint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=True, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # PR / branch reference being audited (e.g. "PR#42", "feature/foo").
    pr_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional diff range audited (e.g. "main...HEAD", "abc123..def456").
    diff_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verdict: Mapped[AuditVerdict] = mapped_column(
        # values_callable so the DB stores the enum VALUES ("pass"/"reject"),
        # not the member names - keeps the column human-readable and matches the
        # hand-written migration's ENUM('pass','reject').
        Enum(AuditVerdict, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # list of {rule, file, line, note, severity}
    violations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # list of {agent, delta, reason} - DWB-016 applies these.
    scorecard: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Uniform human-readable scorecard block.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Raw diff / auditor output. MEDIUMTEXT (16MB) so large payloads don't 500
    # the POST - mirrors test_result.details (DWB-308).
    details: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    triggered_by: Mapped[str] = mapped_column(
        String(100), nullable=False, default="manual", server_default="manual"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # One-directional relationships (no back_populates - the parent models don't
    # need to know about audits, so we avoid editing project/sprint/ticket).
    project: Mapped["Project"] = relationship()  # noqa: F821
    sprint: Mapped["Sprint | None"] = relationship()  # noqa: F821
    ticket: Mapped["Ticket | None"] = relationship()  # noqa: F821

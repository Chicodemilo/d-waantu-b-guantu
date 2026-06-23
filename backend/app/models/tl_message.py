# Path: app/models/tl_message.py
# File: tl_message.py
# Created: 2026-06-23
# Purpose: TlMessage + TlMessageRead ORM models (DWB-436) - the cross-project "Archie Channel" team-lead messaging table. NOT project-scoped: queries span every project's team-lead.
# Caller: app/services/tl_channel.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: TlMessage, TlMessageRead
# Last Modified: 2026-06-23

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TlMessage(Base):
    """One message in the cross-project team-lead channel (DWB-436).

    A message is either DIRECT (``to_agent_id`` set) or BROADCAST
    (``to_agent_id`` is NULL = addressed to every other team-lead). Every
    team-lead can SEE every message in the channel regardless of recipient;
    addressing only governs the unread/ping behaviour.

    This table is intentionally NOT project-scoped. ``from_project_id`` records
    where the sender lives, but listing the channel spans all projects.
    """

    __tablename__ = "tl_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    # NULL = broadcast to all other team-leads.
    to_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True, index=True
    )
    from_project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )


class TlMessageRead(Base):
    """Per-(message, agent) read receipt for the team-lead channel (DWB-436).

    A row exists once ``agent_id`` has read ``message_id``. Composite PK
    (message_id, agent_id) makes a re-read idempotent. The message FK cascades
    so deleting a message clears its receipts.
    """

    __tablename__ = "tl_message_reads"

    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tl_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

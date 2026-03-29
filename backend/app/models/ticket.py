import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TicketType(str, enum.Enum):
    task = "task"
    bug = "bug"
    story = "story"


class TicketStatus(str, enum.Enum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    in_review = "in_review"
    done = "done"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    epic_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("epics.id"), nullable=True, index=True
    )
    sprint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=False, index=True
    )
    assigned_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True, index=True
    )
    ticket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ticket_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket_type: Mapped[TicketType] = mapped_column(
        Enum(TicketType), nullable=False, default=TicketType.task
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus), nullable=False, default=TicketStatus.backlog
    )
    tokens_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    time_spent_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    token_source: Mapped[str | None] = mapped_column(String(50), nullable=True, default="unknown")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="tickets")  # noqa: F821
    epic: Mapped["Epic | None"] = relationship(back_populates="tickets")  # noqa: F821
    sprint: Mapped["Sprint"] = relationship(back_populates="tickets")  # noqa: F821
    assigned_agent: Mapped["Agent | None"] = relationship(back_populates="assigned_tickets")  # noqa: F821
    comments: Mapped[list["Comment"]] = relationship(back_populates="ticket")  # noqa: F821
    alerts: Mapped[list["Alert"]] = relationship(back_populates="ticket")  # noqa: F821

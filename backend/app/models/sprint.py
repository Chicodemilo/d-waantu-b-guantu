import enum
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SprintStatus(str, enum.Enum):
    planned = "planned"
    active = "active"
    completed = "completed"


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    epic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("epics.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    sprint_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SprintStatus] = mapped_column(
        Enum(SprintStatus), nullable=False, default=SprintStatus.planned
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="sprints")  # noqa: F821
    epic: Mapped["Epic"] = relationship()  # noqa: F821
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="sprint")  # noqa: F821

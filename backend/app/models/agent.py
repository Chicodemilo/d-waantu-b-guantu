from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project_agents: Mapped[list["ProjectAgent"]] = relationship(back_populates="agent")  # noqa: F821
    assigned_tickets: Mapped[list["Ticket"]] = relationship(back_populates="assigned_agent")  # noqa: F821
    comments: Mapped[list["Comment"]] = relationship(back_populates="author_agent")  # noqa: F821
    raised_alerts: Mapped[list["Alert"]] = relationship(back_populates="raised_by_agent")  # noqa: F821
    instructions: Mapped[list["Instruction"]] = relationship(back_populates="agent")  # noqa: F821
    activity_logs: Mapped[list["ActivityLog"]] = relationship(back_populates="agent")  # noqa: F821

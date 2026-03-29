# Path: app/models/project_agent.py
# File: project_agent.py
# Created: 2026-03-29
# Purpose: ProjectAgent ORM model — agent-project join table
# Caller: app/services/project_agent.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: ProjectAgent
# Last Modified: 2026-03-29

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectAgent(Base):
    __tablename__ = "project_agents"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", name="uq_project_agent"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="project_agents")  # noqa: F821
    agent: Mapped["Agent"] = relationship(back_populates="project_agents")  # noqa: F821

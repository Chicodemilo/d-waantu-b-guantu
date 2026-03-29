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

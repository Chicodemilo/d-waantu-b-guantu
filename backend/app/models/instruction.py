import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InstructionScope(str, enum.Enum):
    global_ = "global"
    project = "project"
    agent = "agent"


class Instruction(Base):
    __tablename__ = "instructions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[InstructionScope] = mapped_column(
        Enum(InstructionScope, values_callable=lambda e: [i.value for i in e]), nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=True, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project | None"] = relationship(back_populates="instructions")  # noqa: F821
    agent: Mapped["Agent | None"] = relationship(back_populates="instructions")  # noqa: F821

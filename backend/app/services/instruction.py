# Path: app/services/instruction.py
# File: instruction.py
# Created: 2026-03-29
# Purpose: Instruction CRUD with scope filtering
# Caller: app/routers/instructions.py
# Callees: app/models/instruction.py
# Data In: db: Session, InstructionCreate/Update
# Data Out: list[Instruction], Instruction
# Last Modified: 2026-03-29

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instruction import Instruction, InstructionScope
from app.schemas.instruction import InstructionCreate, InstructionUpdate


def list_instructions(
    db: Session,
    scope: InstructionScope | None = None,
    project_id: int | None = None,
    agent_id: int | None = None,
) -> list[Instruction]:
    stmt = select(Instruction)
    if scope:
        stmt = stmt.where(Instruction.scope == scope)
    if project_id:
        stmt = stmt.where(Instruction.project_id == project_id)
    if agent_id:
        stmt = stmt.where(Instruction.agent_id == agent_id)
    stmt = stmt.order_by(Instruction.created_at.desc())
    return list(db.scalars(stmt).all())


def get_instruction(db: Session, instruction_id: int) -> Instruction | None:
    return db.get(Instruction, instruction_id)


def create_instruction(db: Session, data: InstructionCreate) -> Instruction:
    instruction = Instruction(**data.model_dump())
    db.add(instruction)
    db.commit()
    db.refresh(instruction)
    return instruction


def update_instruction(
    db: Session, instruction: Instruction, data: InstructionUpdate
) -> Instruction:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(instruction, key, value)
    db.commit()
    db.refresh(instruction)
    return instruction


def delete_instruction(db: Session, instruction: Instruction) -> None:
    db.delete(instruction)
    db.commit()

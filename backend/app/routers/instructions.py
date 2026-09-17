# Path: app/routers/instructions.py
# File: instructions.py
# Created: 2026-03-29
# Purpose: Instruction HTTP endpoints — CRUD, sync-check, sync
# Caller: app/main.py
# Callees: app/services/instruction.py, app/services/sync_check.py
# Data In: HTTP requests
# Data Out: JSON responses (InstructionRead, sync reports)
# Last Modified: 2026-09-17 (DWB-575: sync-check/sync report source_readable/
#   source_error distinctly from a real empty read; POST /sync 400s on an
#   unreadable source instead of returning [] as if there were nothing to do)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.instruction import InstructionScope
from app.schemas.instruction import InstructionCreate, InstructionRead, InstructionUpdate
from app.services import instruction as svc
from app.services import sync_check

router = APIRouter(prefix="/api/instructions", tags=["instructions"])


class SyncMatchOut(BaseModel):
    memory_file: str
    memory_name: str
    instruction_id: int
    instruction_title: str
    similarity: float


class MemoryOnlyOut(BaseModel):
    filename: str
    name: str
    body: str


class DbOnlyOut(BaseModel):
    id: int
    title: str
    scope: str


class SyncCheckResponse(BaseModel):
    matched: list[SyncMatchOut]
    memory_only: list[MemoryOnlyOut]
    db_only: list[DbOnlyOut]
    in_sync: bool
    # DWB-575: distinct from in_sync. False means the memory source could
    # not be read at all (missing dir, unreadable file, ...); in that case
    # in_sync is ALWAYS false too, never a false green from an empty read
    # that never happened. source_error is a short reason, present only
    # when source_readable is False.
    source_readable: bool
    source_error: str | None = None


@router.get("/sync-check", response_model=SyncCheckResponse)
def sync_check_endpoint(db: Session = Depends(get_db)):
    report = sync_check.build_sync_report(db)
    return SyncCheckResponse(
        matched=[
            SyncMatchOut(
                memory_file=m.memory_file,
                memory_name=m.memory_name,
                instruction_id=m.instruction_id,
                instruction_title=m.instruction_title,
                similarity=m.similarity,
            )
            for m in report.matched
        ],
        memory_only=[
            MemoryOnlyOut(filename=m.filename, name=m.name, body=m.body)
            for m in report.memory_only
        ],
        db_only=[
            DbOnlyOut(id=d["id"], title=d["title"], scope=d["scope"])
            for d in report.db_only
        ],
        # DWB-575: in_sync can only be true when the source was actually
        # read AND that read found nothing pending - never on an unreadable
        # source, which used to compute in_sync=True having read zero files.
        in_sync=report.source_readable and len(report.memory_only) == 0,
        source_readable=report.source_readable,
        source_error=report.source_error,
    )


@router.post("/sync", response_model=list[InstructionRead], status_code=201)
def sync_instructions(db: Session = Depends(get_db)):
    # DWB-575: an unreadable memory source must 400, not return [] the same
    # way a source that was read and had nothing pending would.
    try:
        return sync_check.sync_memory_to_db(db)
    except sync_check.SyncSourceUnreadable as exc:
        raise HTTPException(400, f"Cannot sync: {exc}")


@router.get("", response_model=list[InstructionRead])
def list_instructions(
    scope: InstructionScope | None = Query(None),
    project_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_instructions(
        db, scope=scope, project_id=project_id, agent_id=agent_id
    )


@router.get("/{instruction_id}", response_model=InstructionRead)
def get_instruction(instruction_id: int, db: Session = Depends(get_db)):
    instruction = svc.get_instruction(db, instruction_id)
    if not instruction:
        raise HTTPException(404, "Instruction not found")
    return instruction


@router.post("", response_model=InstructionRead, status_code=201)
def create_instruction(data: InstructionCreate, db: Session = Depends(get_db)):
    return svc.create_instruction(db, data)


@router.patch("/{instruction_id}", response_model=InstructionRead)
def update_instruction(
    instruction_id: int, data: InstructionUpdate, db: Session = Depends(get_db)
):
    instruction = svc.get_instruction(db, instruction_id)
    if not instruction:
        raise HTTPException(404, "Instruction not found")
    return svc.update_instruction(db, instruction, data)


@router.delete("/{instruction_id}", status_code=204)
def delete_instruction(instruction_id: int, db: Session = Depends(get_db)):
    instruction = svc.get_instruction(db, instruction_id)
    if not instruction:
        raise HTTPException(404, "Instruction not found")
    svc.delete_instruction(db, instruction)

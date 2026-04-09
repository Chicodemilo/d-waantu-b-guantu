# Path: app/services/sync_check.py
# File: sync_check.py
# Created: 2026-03-29
# Purpose: Compare DB instructions with Claude memory files
# Caller: app/routers/instructions.py
# Callees: app/models/instruction.py, pathlib
# Data In: db: Session
# Data Out: dict (sync status report)
# Last Modified: 2026-03-29

"""Compare Claude memory files with DB instructions and report differences."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.instruction import Instruction, InstructionScope
from app.schemas.instruction import InstructionCreate
from app.services import instruction as instruction_svc

MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-mchick-Dev-d-waantu-b-guantu" / "memory"

FUZZY_THRESHOLD = 0.6


@dataclass
class MemoryEntry:
    filename: str
    name: str
    description: str
    type: str
    body: str


@dataclass
class SyncMatch:
    memory_file: str
    memory_name: str
    instruction_id: int
    instruction_title: str
    similarity: float


@dataclass
class SyncReport:
    matched: list[SyncMatch] = field(default_factory=list)
    memory_only: list[MemoryEntry] = field(default_factory=list)
    db_only: list[dict] = field(default_factory=list)


def parse_memory_file(path: Path) -> MemoryEntry | None:
    """Parse a memory .md file with YAML-ish frontmatter."""
    text = path.read_text(encoding="utf-8")
    # Match frontmatter between --- delimiters
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return None
    frontmatter, body = m.group(1), m.group(2).strip()

    attrs: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            attrs[key.strip()] = val.strip()

    return MemoryEntry(
        filename=path.name,
        name=attrs.get("name", path.stem),
        description=attrs.get("description", ""),
        type=attrs.get("type", "unknown"),
        body=body,
    )


def load_memory_entries(memory_dir: Path | None = None) -> list[MemoryEntry]:
    """Load all feedback-type memory entries from the memory directory."""
    d = memory_dir or MEMORY_DIR
    if not d.is_dir():
        return []
    entries = []
    for f in sorted(d.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        entry = parse_memory_file(f)
        if entry and entry.type == "feedback":
            entries.append(entry)
    return entries


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_match(
    memory: MemoryEntry, instructions: list[Instruction]
) -> tuple[Instruction | None, float]:
    best_inst = None
    best_score = 0.0
    for inst in instructions:
        # Compare both title and body, weight title higher
        title_sim = _similarity(memory.name, inst.title)
        body_sim = _similarity(memory.body, inst.body)
        score = title_sim * 0.6 + body_sim * 0.4
        if score > best_score:
            best_score = score
            best_inst = inst
    return best_inst, best_score


def build_sync_report(db: Session, memory_dir: Path | None = None) -> SyncReport:
    """Compare memory entries against DB instructions and return a report."""
    memories = load_memory_entries(memory_dir)
    db_instructions = instruction_svc.list_instructions(db)

    report = SyncReport()
    matched_instruction_ids: set[int] = set()

    for mem in memories:
        inst, score = _best_match(mem, db_instructions)
        if inst and score >= FUZZY_THRESHOLD:
            report.matched.append(
                SyncMatch(
                    memory_file=mem.filename,
                    memory_name=mem.name,
                    instruction_id=inst.id,
                    instruction_title=inst.title,
                    similarity=round(score, 3),
                )
            )
            matched_instruction_ids.add(inst.id)
        else:
            report.memory_only.append(mem)

    for inst in db_instructions:
        if inst.id not in matched_instruction_ids:
            report.db_only.append(
                {"id": inst.id, "title": inst.title, "scope": inst.scope.value}
            )

    return report


def sync_memory_to_db(db: Session, memory_dir: Path | None = None) -> list[Instruction]:
    """POST any memory-only items to the DB as new instructions."""
    report = build_sync_report(db, memory_dir)
    created = []
    for mem in report.memory_only:
        data = InstructionCreate(
            scope=InstructionScope.global_,
            title=mem.name,
            body=mem.body,
        )
        inst = instruction_svc.create_instruction(db, data)
        created.append(inst)
    return created

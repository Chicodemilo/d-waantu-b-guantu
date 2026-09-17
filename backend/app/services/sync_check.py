# Path: app/services/sync_check.py
# File: sync_check.py
# Created: 2026-03-29
# Purpose: Compare DB instructions with Claude memory files
# Caller: app/routers/instructions.py, scripts/sync_instructions.py
# Callees: app/models/instruction.py, app/config/server_repo.py, pathlib
# Data In: db: Session
# Data Out: dict (sync status report)
# Last Modified: 2026-09-17 (DWB-575: MEMORY_DIR derived from this server's own
#   repo instead of a hardcoded home directory; load/build/sync now distinguish
#   "could not read the source" from "read it, nothing there")

"""Compare Claude memory files with DB instructions and report differences."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy.orm import Session

from app.config.server_repo import REPO_ROOT
from app.models.instruction import Instruction, InstructionScope
from app.schemas.instruction import InstructionCreate
from app.services import instruction as instruction_svc


def _claude_project_slug(repo_path: Path) -> str:
    """Claude Code's own project-memory directory naming: every
    non-alphanumeric character in the absolute repo path becomes a dash
    (DWB-575). Verified against a real ~/.claude/projects/ listing: e.g.
    '/Users/alex/Dev/my-project' -> '-Users-alex-Dev-my-project' (every
    slash becomes a dash, and so does any other non-alphanumeric character
    a real path might contain, such as an underscore)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(repo_path))


def _default_memory_dir() -> Path:
    """This server's own Claude Code memory directory (DWB-575).

    The old constant hardcoded one person's username and one machine's repo
    directory name, which shipped that machine's home-directory layout in a
    repo other people clone, and was wrong on every OTHER clone (including
    this same user on a second machine). Derived instead from REPO_ROOT -
    the repo this server's own code lives in, same source of truth DWB-571
    established - so it is correct wherever DWB is cloned to, with no
    fallback that guesses at a different spelling of the same idea.
    """
    return Path.home() / ".claude" / "projects" / _claude_project_slug(REPO_ROOT) / "memory"


MEMORY_DIR = _default_memory_dir()

FUZZY_THRESHOLD = 0.6


class SyncSourceUnreadable(Exception):
    """Raised by sync_memory_to_db when the memory source could not be read
    at all (DWB-575) - missing directory, a path that isn't a directory, or
    an OS-level read failure. Never silently treated as "nothing to sync":
    that would make an unreadable source indistinguishable from a
    successful read that found zero pending items, which is the exact false
    green this ticket exists to remove. The router converts this to an
    HTTP error; this module never imports FastAPI (see coding-standards.md
    services rule)."""


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
    # DWB-575: True only when the memory source was actually read (even if
    # that read found zero entries). False means memory_only is [] because
    # the source could not be read, not because it was read and empty -
    # the distinction the rest of this ticket exists to make.
    source_readable: bool = True
    source_error: str | None = None


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


def load_memory_entries(
    memory_dir: Path | None = None,
) -> tuple[list[MemoryEntry], str | None]:
    """Load all feedback-type memory entries from the memory directory.

    Returns (entries, error). error is None on a successful read - even one
    that finds zero entries, which is a legitimate "nothing to sync" state -
    and is a short, human-readable string when the source could not be read
    at all: missing directory, a path that is not a directory, or an
    OS-level failure listing or reading it (DWB-575). Callers must not infer
    "nothing pending" from an empty list without also checking error is None.
    """
    d = memory_dir or MEMORY_DIR
    if not d.exists():
        return [], f"memory directory not found: {d}"
    if not d.is_dir():
        return [], f"memory path exists but is not a directory: {d}"

    try:
        files = sorted(d.glob("*.md"))
    except OSError as exc:
        return [], f"could not list memory directory {d}: {exc}"

    entries = []
    for f in files:
        if f.name == "MEMORY.md":
            continue
        try:
            entry = parse_memory_file(f)
        except (OSError, UnicodeDecodeError) as exc:
            return [], f"could not read memory file {f.name}: {exc}"
        if entry and entry.type == "feedback":
            entries.append(entry)
    return entries, None


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
    memories, source_error = load_memory_entries(memory_dir)
    db_instructions = instruction_svc.list_instructions(db)

    report = SyncReport(
        source_readable=source_error is None, source_error=source_error
    )
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
    """POST any memory-only items to the DB as new instructions.

    DWB-575: raises SyncSourceUnreadable when the memory source could not be
    read, rather than returning [] the same way it would for a source that
    was read and genuinely had nothing pending - the write path has the same
    false-green shape as the read path, and callers (the router; the legacy
    CLI in scripts/sync_instructions.py) must not report "nothing to sync"
    on a source that was never actually read.
    """
    report = build_sync_report(db, memory_dir)
    if not report.source_readable:
        raise SyncSourceUnreadable(report.source_error)
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

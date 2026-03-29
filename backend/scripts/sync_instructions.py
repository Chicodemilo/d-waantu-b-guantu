#!/usr/bin/env python3
# Path: backend/scripts/sync_instructions.py
# File: sync_instructions.py
# Created: 2026-03-27
# Purpose: Bidirectional sync between DB instructions and docs/rules/ markdown files
# Caller: Manual CLI
# Callees: app.database.SessionLocal, app.services.instruction, app.services.sync_check
# Data In: CLI args (--export, --import, --sync); DB instructions; docs/rules/*.md files
# Data Out: Markdown files (export) or DB records (import); stdout report
# Last Modified: 2026-03-29
"""Bidirectional sync between DB instructions and docs/rules/ markdown files.

Usage:
    python scripts/sync_instructions.py                # report sync status
    python scripts/sync_instructions.py --export       # DB → docs/rules/ files
    python scripts/sync_instructions.py --import       # docs/rules/ files → DB
    python scripts/sync_instructions.py --sync         # legacy: memory → DB

Environment variables (all optional, inherited from app.config.Settings):
    MYSQL_HOST           — DB host (default: 127.0.0.1)
    MYSQL_PORT           — DB port (default: 3306)
    MYSQL_USER           — DB user (default: lat_user)
    MYSQL_PASSWORD       — DB password (default: lat_dev_password)
    MYSQL_DATABASE       — DB name (default: local_agent_tracker)
    LAT_RULES_DIR        — rules directory (default: <project_root>/docs/rules)

    Note: This script uses SessionLocal from app.database, which reads
    connection settings via pydantic-settings from env vars and ../.env.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.instruction import Instruction, InstructionScope
from app.schemas.instruction import InstructionCreate, InstructionUpdate
from app.services import agent as agent_svc
from app.services import instruction as instruction_svc
from app.services import project as project_svc
from app.services.sync_check import build_sync_report, sync_memory_to_db

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
RULES_DIR = Path(os.environ.get("LAT_RULES_DIR", str(PROJECT_ROOT / "docs" / "rules")))

SCOPE_DIRS = {
    InstructionScope.global_: "global",
    InstructionScope.project: "project",
    InstructionScope.agent: "agent",
}


def slugify(text: str) -> str:
    """Convert a title to a filename-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def build_filename(inst: Instruction, db) -> str:
    """Build a filename for an instruction based on scope and relationships."""
    title_slug = slugify(inst.title)

    if inst.scope == InstructionScope.project and inst.project_id:
        project = project_svc.get_project(db, inst.project_id)
        prefix = project.prefix.lower() if project else f"proj{inst.project_id}"
        return f"{prefix}-{title_slug}.md"

    if inst.scope == InstructionScope.agent and inst.agent_id:
        agent = agent_svc.get_agent(db, inst.agent_id)
        prefix = agent.name.lower() if agent else f"agent{inst.agent_id}"
        return f"{prefix}-{title_slug}.md"

    return f"{title_slug}.md"


def write_rule_file(inst: Instruction, db) -> Path:
    """Write a single instruction to a markdown file in docs/rules/."""
    scope_dir = RULES_DIR / SCOPE_DIRS[inst.scope]
    scope_dir.mkdir(parents=True, exist_ok=True)

    filename = build_filename(inst, db)
    filepath = scope_dir / filename

    # Build frontmatter
    fm_lines = [
        f"id: {inst.id}",
        f"scope: {inst.scope.value}",
    ]
    if inst.project_id:
        project = project_svc.get_project(db, inst.project_id)
        fm_lines.append(f"project_id: {inst.project_id}")
        if project:
            fm_lines.append(f"project: {project.prefix}")
    if inst.agent_id:
        agent = agent_svc.get_agent(db, inst.agent_id)
        fm_lines.append(f"agent_id: {inst.agent_id}")
        if agent:
            fm_lines.append(f"agent: {agent.name}")

    frontmatter = "\n".join(fm_lines)
    content = f"---\n{frontmatter}\n---\n\n# {inst.title}\n\n{inst.body}\n"

    filepath.write_text(content, encoding="utf-8")
    return filepath


def parse_rule_file(path: Path) -> dict | None:
    """Parse a rule markdown file, returning frontmatter + body."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return None

    frontmatter_text, body = m.group(1), m.group(2).strip()

    attrs: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            attrs[key.strip()] = val.strip()

    # Extract title from first heading
    title_match = re.match(r"^#\s+(.+)", body)
    title = title_match.group(1).strip() if title_match else path.stem
    # Body is everything after the heading
    if title_match:
        body = body[title_match.end():].strip()

    return {
        "id": int(attrs["id"]) if "id" in attrs else None,
        "scope": attrs.get("scope", "global"),
        "project_id": int(attrs["project_id"]) if "project_id" in attrs else None,
        "agent_id": int(attrs["agent_id"]) if "agent_id" in attrs else None,
        "title": title,
        "body": body,
        "path": path,
    }


def export_rules(db) -> list[Path]:
    """Export all DB instructions to docs/rules/ files."""
    instructions = instruction_svc.list_instructions(db)
    written = []
    for inst in instructions:
        filepath = write_rule_file(inst, db)
        written.append(filepath)
    return written


def import_rules(db) -> tuple[list[Instruction], list[Instruction]]:
    """Import docs/rules/ files into DB. Creates new or updates existing."""
    created = []
    updated = []

    for scope_enum, dirname in SCOPE_DIRS.items():
        scope_dir = RULES_DIR / dirname
        if not scope_dir.is_dir():
            continue
        for md_file in sorted(scope_dir.glob("*.md")):
            parsed = parse_rule_file(md_file)
            if not parsed:
                print(f"  SKIP (no frontmatter): {md_file.name}")
                continue

            # If file has an ID, try to update existing
            if parsed["id"]:
                existing = instruction_svc.get_instruction(db, parsed["id"])
                if existing:
                    data = InstructionUpdate(
                        title=parsed["title"],
                        body=parsed["body"],
                        scope=InstructionScope(parsed["scope"]),
                        project_id=parsed["project_id"],
                        agent_id=parsed["agent_id"],
                    )
                    inst = instruction_svc.update_instruction(db, existing, data)
                    updated.append(inst)
                    continue

            # No ID or ID not found — create new
            scope_val = InstructionScope(parsed["scope"])
            data = InstructionCreate(
                scope=scope_val,
                project_id=parsed["project_id"],
                agent_id=parsed["agent_id"],
                title=parsed["title"],
                body=parsed["body"],
            )
            inst = instruction_svc.create_instruction(db, data)
            created.append(inst)

    return created, updated


def report_status(db):
    """Show which instructions are in DB, in files, or both."""
    instructions = instruction_svc.list_instructions(db)
    db_ids = {inst.id for inst in instructions}

    file_ids: set[int] = set()
    file_only: list[Path] = []

    for dirname in SCOPE_DIRS.values():
        scope_dir = RULES_DIR / dirname
        if not scope_dir.is_dir():
            continue
        for md_file in sorted(scope_dir.glob("*.md")):
            parsed = parse_rule_file(md_file)
            if parsed and parsed["id"]:
                file_ids.add(parsed["id"])
            elif parsed:
                file_only.append(md_file)

    both = db_ids & file_ids
    db_only = db_ids - file_ids

    print(f"\n{'='*60}")
    print("  Rules Sync Status")
    print(f"{'='*60}\n")
    print(f"IN BOTH ({len(both)}):")
    for inst in instructions:
        if inst.id in both:
            print(f"  = [{inst.id}] {inst.title}")
    if not both:
        print("  (none)")

    print(f"\nDB-ONLY ({len(db_only)}):")
    for inst in instructions:
        if inst.id in db_only:
            print(f"  + [{inst.id}] {inst.title} (scope: {inst.scope.value})")
    if not db_only:
        print("  (none)")

    print(f"\nFILE-ONLY ({len(file_only)}):")
    for fp in file_only:
        print(f"  * {fp.relative_to(RULES_DIR)}")
    if not file_only:
        print("  (none)")

    print()
    return len(db_only) + len(file_only)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bidirectional sync: DB instructions ↔ docs/rules/ files"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--export", action="store_true", help="DB → docs/rules/ files")
    group.add_argument("--import", dest="import_rules", action="store_true",
                       help="docs/rules/ files → DB")
    group.add_argument("--sync", action="store_true",
                       help="Legacy: sync Claude memory → DB")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.export:
            written = export_rules(db)
            print(f"\nExported {len(written)} instruction(s) to {RULES_DIR}/")
            for fp in written:
                print(f"  → {fp.relative_to(PROJECT_ROOT)}")
            print()
            return 0

        if args.import_rules:
            if not RULES_DIR.is_dir():
                print(f"ERROR: Rules directory not found: {RULES_DIR}")
                return 1
            created, updated = import_rules(db)
            print(f"\nImported: {len(created)} created, {len(updated)} updated")
            for inst in created:
                print(f"  + [{inst.id}] {inst.title}")
            for inst in updated:
                print(f"  ~ [{inst.id}] {inst.title}")
            print()
            return 0

        if args.sync:
            # Legacy: memory → DB sync
            report = build_sync_report(db)
            if report.memory_only:
                created = sync_memory_to_db(db)
                print(f"Synced {len(created)} instruction(s) from memory:")
                for inst in created:
                    print(f"  + [{inst.id}] {inst.title}")
                return 0
            print("Memory and DB are in sync.")
            return 0

        # Default: report status
        unsynced = report_status(db)
        if unsynced:
            print("Use --export to write DB → files, or --import to read files → DB.")
            return 1
        print("Everything in sync.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

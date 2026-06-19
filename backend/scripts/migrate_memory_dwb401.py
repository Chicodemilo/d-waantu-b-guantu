# Path: scripts/migrate_memory_dwb401.py
# File: migrate_memory_dwb401.py
# Created: 2026-06-19
# Purpose: DWB-401 memory migration - relocate agent memory from .claude/agents/memory to .dwb/memory AND collapse the 4-file model (identity/scratchpad/lessons/recent_sessions) to 2 files (identity + free-form memory.md). COPY-then-cutover; dry-run is the DEFAULT.
# Caller: CLI (operator), run manually; never auto-invoked
# Callees: app.database.SessionLocal, app.models.project.Project, app.models.agent.Agent
# Data In: --apply flag, optional --project-id, optional --repo/--prefix override for throwaway testing
# Data Out: stdout migration plan (dry-run) or copied files under .dwb/memory (apply); returns exit 0
# Last Modified: 2026-06-19

"""DWB-401 memory migration.

Relocates agent memory out of the protected `.claude/` tree (where subagent
writes crash the CC renderer) into `<repo>/.dwb/memory/<prefix>/<name>/`, and
collapses the file model:

    OLD (4 files)                NEW (2 files)
    -------------                -------------
    identity.md       --copy-->  identity.md         (system-regenerated; copied verbatim)
    scratchpad.md  \\
    lessons.md      >--merge-->  memory.md           (single free-form file)
    recent_sessions.md --drop->  (dropped; the DB is the source of truth for the session index)

SAFETY / PROTOCOL (DWB-401, mandated by Archie):
  1. COPY-then-cutover. The old `.claude/agents/memory/...` tree is NEVER
     touched, moved, or deleted by this script. Deleting the old dirs is the
     TL's job (workers crash on `.claude/` writes); this script only writes
     under `.dwb/`.
  2. Dry-run is the DEFAULT. Without `--apply` the script prints the full plan
     (every source -> dest, every merge, every drop) and writes NOTHING.
  3. Idempotent + re-runnable. A destination file that already exists is SKIPPED,
     never overwritten. That makes a second run a no-op AND protects any
     post-cutover writes an agent has already made to the new memory.md.
  4. Writes are atomic (temp file + os.replace) so an interrupted run can't
     leave a half-written destination.

USAGE:
    # Dry-run (default), all projects in the DB:
    python -m scripts.migrate_memory_dwb401

    # Dry-run, single project (canary scoping):
    python -m scripts.migrate_memory_dwb401 --project-id 1

    # Live apply (writes under .dwb/ only), single project:
    python -m scripts.migrate_memory_dwb401 --project-id 1 --apply

    # Throwaway-repo mode (no DB): migrate a single repo+prefix on disk.
    python -m scripts.migrate_memory_dwb401 --repo /tmp/throwaway --prefix TEST

Run from the `backend/` directory (so `app` is importable), e.g.
    cd backend && python -m scripts.migrate_memory_dwb401
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

OLD_SUBPATH = Path(".claude") / "agents" / "memory"
NEW_SUBPATH = Path(".dwb") / "memory"

IDENTITY_FILE = "identity.md"
# Source files that merge into the single new memory.md, in write order.
MERGE_SOURCES = ("lessons.md", "scratchpad.md")
DROPPED_FILES = ("recent_sessions.md",)
NEW_MEMORY_FILE = "memory.md"


@dataclass
class FileAction:
    kind: str            # "copy" | "merge" | "drop" | "skip-exists"
    dest: Path | None
    sources: list[Path] = field(default_factory=list)
    note: str = ""


@dataclass
class AgentPlan:
    prefix: str
    name: str
    old_dir: Path
    new_dir: Path
    actions: list[FileAction] = field(default_factory=list)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _build_memory_md(prefix: str, name: str, lessons: str, scratchpad: str) -> str:
    """Build the merged memory.md body from lessons.md + scratchpad.md.

    Single free-form file (DWB-401). Lessons (durable) lead; scratchpad
    (in-flight notes) follow. Empty sources are omitted so the file stays lean.
    Deterministic: same inputs -> same bytes (no timestamps), so the merge is
    idempotent.
    """
    parts: list[str] = [f"# Memory - {name}", ""]
    parts.append(
        "> Single free-form memory file (DWB-401). Migrated from the former "
        "lessons.md + scratchpad.md. recent_sessions.md was dropped (the DWB "
        "database is the source of truth for the session index)."
    )
    parts.append("")
    lessons = lessons.strip()
    scratchpad = scratchpad.strip()
    if lessons:
        parts.append("## Lessons")
        parts.append("")
        parts.append(lessons)
        parts.append("")
    if scratchpad:
        parts.append("## Working notes")
        parts.append("")
        parts.append(scratchpad)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def plan_agent(prefix: str, name: str, old_dir: Path, new_dir: Path) -> AgentPlan:
    """Compute the (write-nothing) plan for a single agent memory dir."""
    plan = AgentPlan(prefix=prefix, name=name, old_dir=old_dir, new_dir=new_dir)

    # identity.md -> copy verbatim (skip if dest already present)
    src_identity = old_dir / IDENTITY_FILE
    dest_identity = new_dir / IDENTITY_FILE
    if dest_identity.exists():
        plan.actions.append(FileAction("skip-exists", dest_identity, [src_identity],
                                       "identity.md already at destination"))
    elif src_identity.is_file():
        plan.actions.append(FileAction("copy", dest_identity, [src_identity],
                                       "identity.md copied verbatim"))

    # memory.md <- merge(lessons.md, scratchpad.md)
    src_merge = [old_dir / f for f in MERGE_SOURCES if (old_dir / f).is_file()]
    dest_memory = new_dir / NEW_MEMORY_FILE
    if dest_memory.exists():
        plan.actions.append(FileAction("skip-exists", dest_memory, src_merge,
                                       "memory.md already at destination (post-cutover writes preserved)"))
    elif src_merge:
        plan.actions.append(FileAction("merge", dest_memory, src_merge,
                                       "lessons.md + scratchpad.md merged into memory.md"))

    # recent_sessions.md -> dropped
    src_recent = old_dir / DROPPED_FILES[0]
    if src_recent.is_file():
        plan.actions.append(FileAction("drop", None, [src_recent],
                                       "recent_sessions.md dropped (DB holds the index)"))

    return plan


def discover_agent_dirs(repo: Path, prefix: str) -> list[tuple[str, Path]]:
    """Return (agent_name, old_agent_dir) for each memory dir under the old root."""
    old_root = repo / OLD_SUBPATH / prefix
    if not old_root.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for child in sorted(old_root.iterdir()):
        if child.is_dir():
            out.append((child.name, child))
    return out


def _atomic_write(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".dwb401.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, dest)


def apply_plan(plan: AgentPlan) -> None:
    """Execute the write actions for an agent plan (live mode only)."""
    for action in plan.actions:
        if action.kind == "copy":
            _atomic_write(action.dest, _read_text(action.sources[0]))
        elif action.kind == "merge":
            lessons = _read_text(plan.old_dir / "lessons.md")
            scratchpad = _read_text(plan.old_dir / "scratchpad.md")
            _atomic_write(action.dest, _build_memory_md(plan.prefix, plan.name, lessons, scratchpad))
        # "drop" and "skip-exists" write nothing.


def _print_plan(plans: list[AgentPlan], repo: Path, prefix: str, apply: bool) -> None:
    mode = "APPLY (writing under .dwb/ only)" if apply else "DRY-RUN (no writes)"
    print(f"\n=== repo={repo}  prefix={prefix}  mode={mode} ===")
    if not plans:
        print("  (no agent memory dirs found under the old path; nothing to migrate)")
        return
    for p in plans:
        print(f"\n  agent: {p.name}")
        print(f"    from: {p.old_dir}")
        print(f"    to:   {p.new_dir}")
        for a in p.actions:
            if a.kind == "merge":
                srcs = " + ".join(s.name for s in a.sources) or "(none)"
                print(f"      [MERGE]  {srcs} -> {a.dest.name}   ({a.note})")
            elif a.kind == "copy":
                print(f"      [COPY]   {a.sources[0].name} -> {a.dest.name}   ({a.note})")
            elif a.kind == "drop":
                print(f"      [DROP]   {a.sources[0].name}   ({a.note})")
            elif a.kind == "skip-exists":
                print(f"      [SKIP]   {a.dest.name}   ({a.note})")
        if not p.actions:
            print("      (empty memory dir; nothing to do)")


def _iter_targets(args) -> list[tuple[Path, str]]:
    """Return [(repo_path, prefix)] targets to migrate.

    Throwaway mode (--repo + --prefix) bypasses the DB entirely. Otherwise the
    targets come from the DB (all projects with a repo_path, or one --project-id).
    """
    if args.repo:
        if not args.prefix:
            print("ERROR: --repo requires --prefix", file=sys.stderr)
            sys.exit(2)
        return [(Path(args.repo), args.prefix)]

    # DB mode
    from app.database import SessionLocal
    from app.models.project import Project

    db = SessionLocal()
    try:
        q = db.query(Project)
        if args.project_id is not None:
            q = q.filter(Project.id == args.project_id)
        targets: list[tuple[Path, str]] = []
        for proj in q.all():
            if not proj.repo_path:
                print(f"  (skip project {proj.prefix}: no repo_path)")
                continue
            targets.append((Path(proj.repo_path), proj.prefix))
        return targets
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="DWB-401 memory migration (dry-run by default)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write (under .dwb/ only). Omit for a dry-run (default).")
    parser.add_argument("--project-id", type=int, default=None,
                        help="scope to a single project id (canary). DB mode only.")
    parser.add_argument("--repo", default=None,
                        help="throwaway-repo mode: migrate this repo path (requires --prefix, no DB).")
    parser.add_argument("--prefix", default=None,
                        help="project prefix for --repo mode.")
    args = parser.parse_args()

    targets = _iter_targets(args)
    if not targets:
        print("No targets to migrate.")
        return 0

    total_agents = 0
    for repo, prefix in targets:
        agent_dirs = discover_agent_dirs(repo, prefix)
        plans = []
        for name, old_dir in agent_dirs:
            new_dir = repo / NEW_SUBPATH / prefix / name
            plan = plan_agent(prefix, name, old_dir, new_dir)
            plans.append(plan)
            if args.apply:
                apply_plan(plan)
        total_agents += len(plans)
        _print_plan(plans, repo, prefix, args.apply)

    print(f"\n=== {'APPLIED' if args.apply else 'DRY-RUN'}: {total_agents} agent memory dir(s) "
          f"across {len(targets)} repo(s). Old .claude/ memory left UNTOUCHED. ===")
    if not args.apply:
        print("Re-run with --apply to perform the copy (writes under .dwb/ only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

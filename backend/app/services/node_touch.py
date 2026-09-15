# Path: app/services/node_touch.py
# File: node_touch.py
# Created: 2026-09-14 (DWB-527)
# Purpose: The nodeify full pass + the shared event-driven touch-update dispatch.
#          nodeify_project() rebuilds a project's nodes idempotently by sweeping
#          the memory corpus, docs, and git history through the registration
#          service - refreshing rotted line refs to the current sha and pruning
#          pointers whose targets vanished. touch_memory() is the incremental
#          seam: a memory write re-grounds ONLY that entry's own (memory) pointers,
#          leaving code/doc/ticket/session pointers untouched. Source extraction
#          is pluggable via register_source_provider so the DWB-525 (commit) and
#          DWB-526 (doc) lanes can override the default sweep for their domain
#          without co-editing this file.
# Caller: app/routers/nodes.py (nodeify), app/services/agent.py (memory touch)
# Callees: app/services/node_registry (register_sources, SourceUnit), app/models
# Data In: db: Session, project_id / project + repo paths
# Data Out: NodeifyResult; None (touch is best-effort)
# Last Modified: 2026-09-15 (DWB-522 rework - docstring commit correction)

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.models.node import NodePointer, NodePointerKind
from app.models.project import Project
from app.services.node_registry import (
    RegistrationResult,
    SourceUnit,
    register_sources,
)

logger = logging.getLogger(__name__)

# Root docs the doc sweep indexes in addition to everything under docs/.
_ROOT_DOC_NAMES = (
    "README.md",
    "ARCHITECTURE.md",
    "HANDOFF.md",
    "INITIAL.md",
    "CLAUDE.md",
    "CODING_STANDARDS.md",
)

# Cap the git-history walk so nodeify on a large repo stays bounded.
_GIT_LOG_LIMIT = 500

# Where per-agent memory lives (mirrors agent_memory._MEMORY_SUBPATH).
_MEMORY_SUBPATH = ".dwb/memory"


class NodeTouchError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class NodeifyResult:
    """Outcome of a nodeify full pass, for the API response + operator report."""

    project_id: int
    nodeified_at: str
    source_counts: dict = field(default_factory=dict)   # kind -> units swept
    grounded: int = 0
    pruned: int = 0
    suppressed: int = 0
    pointers_written: int = 0


# --- default source providers ------------------------------------------------
# A provider is fn(db, project, repo_path) -> list[SourceUnit]. Providers must be
# side-effect free and best-effort (return [] on any failure); nodeify handles
# grounding + persistence. Override a domain via register_source_provider.

def memory_provider(db: Session, project: Project, repo_path: str) -> list[SourceUnit]:
    """Sweep every agent's memory.md under <repo>/.dwb/memory/<prefix>/*/."""
    base = Path(repo_path) / _MEMORY_SUBPATH / project.prefix
    if not base.is_dir():
        return []
    units: list[SourceUnit] = []
    for mem_file in sorted(base.glob("*/memory.md")):
        text = _read_text_safe(mem_file)
        if not text.strip():
            continue
        units.append(
            SourceUnit(
                kind="memory",
                ref=_relref(mem_file, repo_path),
                text=text,
            )
        )
    return units


def doc_provider(db: Session, project: Project, repo_path: str) -> list[SourceUnit]:
    """Sweep root docs + everything under docs/ (whole-file grounding).

    A LIGHT default so nodeify works standalone. The DWB-526 lane may override
    this with a line-range-aware doc indexer via register_source_provider('doc').
    """
    repo = Path(repo_path)
    seen: set[Path] = set()
    units: list[SourceUnit] = []

    candidates: list[Path] = [repo / name for name in _ROOT_DOC_NAMES]
    docs_dir = repo / "docs"
    if docs_dir.is_dir():
        candidates.extend(sorted(docs_dir.rglob("*.md")))

    for path in candidates:
        rp = path.resolve()
        if rp in seen or not path.is_file():
            continue
        seen.add(rp)
        text = _read_text_safe(path)
        if not text.strip():
            continue
        units.append(
            SourceUnit(kind="doc", ref=_relref(path, repo_path), text=text)
        )
    return units


def code_provider(db: Session, project: Project, repo_path: str) -> list[SourceUnit]:
    """Sweep recent git commit messages (kind=code, ref=sha).

    A LIGHT default (message-only, no diff hunks). The DWB-525 lane may override
    with a diff-hunk line-range walk via register_source_provider('code').
    """
    commits = _git_log(repo_path, limit=_GIT_LOG_LIMIT)
    return [
        SourceUnit(kind="code", ref=sha, text=message, sha=sha)
        for sha, message in commits
        if message.strip()
    ]


_DEFAULT_PROVIDERS: dict[str, object] = {
    "memory": memory_provider,
    "doc": doc_provider,
    "code": code_provider,
}

# Overrides registered by other lanes (DWB-525/526). Keyed by kind; wins over the
# default for that kind.
_PROVIDER_OVERRIDES: dict[str, object] = {}


def register_source_provider(kind: str, fn) -> None:
    """Register/override the full-pass source provider for a pointer domain.

    Lets the DWB-525 (code) and DWB-526 (doc) lanes plug their richer extractors
    into nodeify without editing this module (the agreed dispatch seam)."""
    if kind not in {k.value for k in NodePointerKind}:
        raise NodeTouchError("invalid_kind", f"unknown pointer kind '{kind}'")
    _PROVIDER_OVERRIDES[kind] = fn


def _providers() -> dict:
    merged = dict(_DEFAULT_PROVIDERS)
    merged.update(_PROVIDER_OVERRIDES)
    return merged


# --- the full pass -----------------------------------------------------------

def nodeify_project(db: Session, project_id: int) -> NodeifyResult:
    """Operator-invoked idempotent full pass (nodeify / renodify, DWB-527).

    Sweeps every registered source provider (memory + docs + git by default),
    then rebuilds the project's nodes for the swept domains: ALL existing pointers
    of those domains are cleared and re-inserted from the fresh sweep in one
    registration call, so re-running is a no-op, rotted line/sha refs refresh, and
    pointers whose source vanished are pruned. Pointers in domains NOT swept
    (e.g. ticket/session, or a domain whose provider was unregistered) are left
    intact and still count toward grounding. Stamps project.nodeified_at.

    COMMITS its own transaction (db.commit() below). get_db does NOT auto-commit
    in this codebase and the router just returns the service result, so without an
    explicit commit here the node pointers + nodeified_at would never persist (a
    live-only bug: TestClient's shared transaction hides it). Callers that need to
    stay inside a larger uncommitted transaction must not use this entry point.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise NodeTouchError("project_not_found", f"project id {project_id} not found")
    if not project.repo_path:
        raise NodeTouchError(
            "repo_path_missing",
            f"project '{project.prefix}' has no repo_path - cannot nodeify",
        )
    repo = Path(project.repo_path)
    if not repo.is_dir():
        raise NodeTouchError(
            "repo_missing",
            f"repo_path does not exist or is not a directory: {project.repo_path}",
        )

    providers = _providers()
    swept_kinds = {NodePointerKind(k) for k in providers}
    all_units: list[SourceUnit] = []
    source_counts: dict[str, int] = {}
    for kind, fn in sorted(providers.items()):
        try:
            units = fn(db, project, str(repo))
        except Exception:
            logger.warning(
                "nodeify source provider '%s' failed for project %s; skipping",
                kind, project_id, exc_info=True,
            )
            units = []
        source_counts[kind] = len(units)
        all_units.extend(units)

    # Prune scope = every existing pointer of a swept domain. Combined with the
    # fresh units this makes the pass a clean rebuild of those domains: vanished
    # refs drop, surviving refs refresh, and grounding is recomputed.
    existing = db.execute(
        select(distinct(NodePointer.kind), NodePointer.ref).where(
            NodePointer.project_id == project_id,
            NodePointer.kind.in_(swept_kinds),
        )
    ).all()
    prune_scope = {(kind.value, ref) for kind, ref in existing}

    reg: RegistrationResult = register_sources(
        db, project_id, all_units, prune_scope=prune_scope, suppress_generic=True
    )

    nodeified_at = datetime.now(timezone.utc)
    project.nodeified_at = nodeified_at
    db.commit()

    return NodeifyResult(
        project_id=project_id,
        nodeified_at=nodeified_at.isoformat(timespec="seconds"),
        source_counts=source_counts,
        grounded=len(reg.grounded_tags),
        pruned=len(reg.pruned_tags),
        suppressed=len(reg.suppressed_tags),
        pointers_written=reg.pointers_written,
    )


# --- the incremental touch seam ----------------------------------------------

def touch_memory(
    db: Session,
    *,
    project_id: int,
    repo_path: str | None,
    memory_file: Path,
) -> None:
    """Re-ground one agent's memory.md after a memory write (DWB-527).

    The (memory, <memory.md relpath>) pointer set is the refresh unit: this
    re-mines the whole file and replaces ONLY that ref's memory pointers, leaving
    every other domain's pointers alone. Best-effort - never raises, so a node
    failure cannot break the memory write it hangs off of. Does not commit.
    """
    if not repo_path:
        return
    try:
        if not memory_file.is_file():
            return
        text = _read_text_safe(memory_file)
        ref = _relref(memory_file, repo_path)
        if not text.strip():
            # Empty file: prune any stale memory pointers for this ref.
            register_sources(db, project_id, [], prune_scope={("memory", ref)})
        else:
            register_sources(
                db,
                project_id,
                [SourceUnit(kind="memory", ref=ref, text=text)],
            )
        # The memory write's router does not commit (it historically only wrote a
        # file); persist the pointer changes here. Best-effort: on failure roll
        # back only the node work - the memory file write already succeeded.
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "touch_memory failed for project %s file %s; skipping",
            project_id, memory_file, exc_info=True,
        )


# --- helpers -----------------------------------------------------------------

def _relref(path: Path, repo_path: str) -> str:
    """Repo-relative ref for a file, so pointers are portable across clones."""
    try:
        return os.path.relpath(str(path), repo_path)
    except ValueError:
        return str(path)


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _git_env() -> dict:
    """A git-safe copy of the environment. Strips GIT_* vars that redirect git at
    a different repo/index/config (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, etc.).
    Ambient values (from a hook, a parent git invocation, or a leaky test) would
    silently point our `git log` at the wrong place and return nothing."""
    redirecting = (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
    )
    return {k: v for k, v in os.environ.items() if k not in redirecting}


def _git_log(repo_path: str, *, limit: int) -> list[tuple[str, str]]:
    """Return [(sha, message)] for the last ``limit`` commits, or [] on any error
    (not a git repo, git absent, etc.). Uses a NUL record/field separator so
    multi-line commit bodies survive parsing intact. Pins the repo with both -C
    and cwd, sanitizes the env, and marks the dir safe so a dubious-ownership
    check can't silently zero the output."""
    try:
        out = subprocess.run(
            [
                "git",
                "-C", repo_path,
                "-c", f"safe.directory={repo_path}",
                "log",
                f"-n{limit}",
                "--no-color",
                "--format=%H%x1f%B%x1e",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0 or not out.stdout:
        return []
    commits: list[tuple[str, str]] = []
    for record in out.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, message = record.partition("\x1f")
        sha = sha.strip()
        if sha:
            commits.append((sha, message))
    return commits

# Path: app/services/doc_drift.py
# File: doc_drift.py
# Created: 2026-09-16
# Purpose: DWB-569 — a mechanical check that fails when the docs describe code that was deleted. Two independent checks, both catching REFERENCES that no longer resolve (not semantic claims that quietly went false with no dangling reference — see module docstring for the honest boundary): (a) backticked symbols/endpoints in the TL-owned "gated" docs must still resolve against the current codebase; (b) DWB's own deployed `.claude/*_playbook.md` must byte-match what deploy_bundle would render from `docs/*_playbook.md`, catching a reverted or skipped redeploy.
# Caller: backend/tests/test_doc_drift_dwb569.py
# Callees: app.services.playbook_deploy (render helpers + doc paths), app.main (FastAPI route introspection for Check A's endpoint half), grep (subprocess, for Check A's symbol half)
# Data In: repo doc files on disk (.md), the live FastAPI route table
# Data Out: list[str] of drifted playbook filenames (Check B); list[UnresolvedRef] (Check A)
# Last Modified: 2026-09-16 (DWB-569)

"""DWB-569: stop the next sweep from being needed.

BE HONEST ABOUT THE BOUNDARY (this is load-bearing, not a comment): both
checks here are mechanical reference-resolution, nothing more. Check A can
only see a doc that names a symbol, module, or endpoint and that name no
longer resolving. It CANNOT see a semantic claim going stale with no
dangling reference — e.g. ".claude/project_rules_pm.md:38 — '0-token done
tickets, info alert fires automatically'" names no symbol at all, so no
mechanical check built this way will ever catch it. That was one of six
known instances found by hand in the DWB-568 sweep. Catching the resolvable
half is still worth it: it is exactly what would have caught `_ALERT_ROLES`
being described in four docs after its code was deleted.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.playbook_deploy import (
    DOCS_DIR,
    DWB_REPO_ROOT,
    PLAYBOOK_FILES,
    _prepend_banner_if_needed,
    _scrub_for_jira_target,
)

DWB_CLAUDE_DIR = DWB_REPO_ROOT / ".claude"

# ---------------------------------------------------------------------------
# Check B: deployed .claude/*_playbook.md vs. what deploy_bundle would render
# from docs/*_playbook.md right now. This is the cheap check — it would have
# caught the live failure from 2026-09-16: the deployed PM playbook still
# carried a rule DWB-560 had replaced in docs/, and nothing noticed until an
# agent was spawned and read the superseded instruction.
# ---------------------------------------------------------------------------


def find_playbook_deploy_drift(
    *,
    claude_dir: Path,
    docs_dir: Path = DOCS_DIR,
    jira_enabled: bool,
) -> list[str]:
    """Filenames (of PLAYBOOK_FILES) under ``claude_dir`` whose content
    differs from what ``deploy_bundle`` would write there from ``docs_dir``
    for a project with the given ``jira_enabled`` flag. Empty list means the
    deployed copies are in sync with source.

    A file missing on either side is not reported here — existence is a
    different failure mode (deploy has never run / docs/ file was deleted);
    this check is specifically about CONTENT drift between two copies that
    both already exist, which is exactly the "redeploy got skipped or
    reverted" failure mode DWB-569 exists to catch.
    """
    drifted = []
    for filename in PLAYBOOK_FILES.values():
        src = docs_dir / filename
        dst = claude_dir / filename
        if not src.is_file() or not dst.is_file():
            continue
        rendered = _scrub_for_jira_target(
            src.read_text(encoding="utf-8"), jira_enabled=jira_enabled
        )
        rendered = _prepend_banner_if_needed(rendered, jira_enabled=jira_enabled)
        if dst.read_text(encoding="utf-8") != rendered:
            drifted.append(filename)
    return drifted


# ---------------------------------------------------------------------------
# Check A: backticked symbol / endpoint references in the gated docs must
# resolve against the current codebase.
# ---------------------------------------------------------------------------

# The TL-owned "budgeted" doc tier (worker_playbook.md § The Doc Model): root
# docs + the three project_rules files. Playbooks are EXEMPT from that tier
# and are covered separately by Check B above, not here — deliberate split,
# not an oversight (a playbook's own drift-from-source is a different failure
# mode than a playbook's prose naming a deleted symbol; the latter IS in
# scope for Check A too, on the deployed .claude/*_playbook.md copies, see
# GATED_DOCS below).
GATED_DOCS: list[Path] = [
    DWB_REPO_ROOT / "CLAUDE.md",
    DWB_REPO_ROOT / "ARCHITECTURE.md",
    DWB_REPO_ROOT / "README.md",
    DWB_REPO_ROOT / "HANDOFF.md",
    DWB_REPO_ROOT / "INITIAL.md",
    DWB_CLAUDE_DIR / "project_rules_team_lead.md",
    DWB_CLAUDE_DIR / "project_rules_pm.md",
    DWB_CLAUDE_DIR / "project_rules_worker.md",
]

# Directories/files grepped when resolving a bare symbol. Kept narrow and
# explicit rather than gitignore-aware, since this runs inside the pytest
# process rather than via git.
_SYMBOL_SEARCH_DIRS = ["backend", "frontend/src", "docs", "scripts"]
_SYMBOL_SEARCH_FILES = ["docker-compose.yml", ".env.example"]
_GREP_EXCLUDES = [
    "--exclude-dir=.venv",
    "--exclude-dir=node_modules",
    "--exclude-dir=__pycache__",
    "--exclude-dir=.git",
]

_BACKTICK_RE = re.compile(r"`([^`\n]{1,160})`")
_IDENT_RE = re.compile(r"^_{0,2}[A-Za-z][A-Za-z0-9_]*$")
_HTTP_METHOD_RE = re.compile(r"^(GET|POST|PATCH|PUT|DELETE)\s+")


@dataclass(frozen=True)
class UnresolvedRef:
    doc: str  # path relative to repo root, e.g. "ARCHITECTURE.md"
    symbol: str  # the backticked text exactly as written in the doc
    kind: str  # "symbol" | "api_path"


@dataclass(frozen=True)
class AllowlistEntry:
    doc: str  # filename (matched by suffix against the doc's repo-relative path)
    symbol: str  # exact backticked text this entry excuses
    reason: str  # REQUIRED, non-empty — validated by test_allowlist_entries_have_reasons


# DWB-569 AC3: every entry needs a reason. "Growth has to be visible" (per
# the ticket) means visible to code review — this list is an ordinary,
# diffable part of the module; an entry added without a real reason is a
# review miss, the mechanism itself cannot stop that, only make it legible.
# Two legitimate categories, both named in the ticket:
#   - tombstones: code deliberately retired and documented as retired
#     (none yet as of this pass — `ai_classifier` is described as retired in
#     prose without a backticked symbol span, so it doesn't hit Check A at
#     all; noted here so a future symbol-shaped tombstone isn't a surprise).
#   - historical / illustrative prose: a worked example, a naming-pattern
#     sample, or a deliberate postmortem reference to code that no longer
#     exists — never a claim that the exact text resolves today.
ALLOWLIST: list[AllowlistEntry] = [
    AllowlistEntry(
        doc="HANDOFF.md",
        symbol="_find_agent_by_role",
        reason=(
            "Postmortem in HANDOFF.md naming the DWB-566 root-cause function "
            "that commit d48bd59 deleted. Historical record of why the mint "
            "bug happened, not a claim that the function still exists."
        ),
    ),
    AllowlistEntry(
        doc="ARCHITECTURE.md",
        symbol="component__element",
        reason="Illustrative BEM naming-convention pattern, not a literal component name.",
    ),
    AllowlistEntry(
        doc="ARCHITECTURE.md",
        symbol="tl_",
        reason=(
            "Truncated prefix in prose ('tl_/pm_overhead_tokens'); the real "
            "field tl_overhead_tokens resolves on its own."
        ),
    ),
    AllowlistEntry(
        doc=".claude/project_rules_worker.md",
        symbol="LAT_",
        reason=(
            "Prefix-pattern example; the real names (LAT_API_URL etc., "
            "listed two lines later) resolve on their own."
        ),
    ),
    AllowlistEntry(
        doc=".claude/project_rules_worker.md",
        symbol="test_create_ticket_auto_assigns_sprint",
        reason="Illustrative example of the descriptive test-naming convention, not an assertion the test exists.",
    ),
    AllowlistEntry(
        doc=".claude/project_rules_worker.md",
        symbol="test_sprint_close_blocked_by_unresolved_failures",
        reason="Illustrative example of the descriptive test-naming convention, not an assertion the test exists.",
    ),
    AllowlistEntry(
        doc=".claude/project_rules_worker.md",
        symbol="test_1",
        reason='Explicit counter-example ("Not `test_1`") for bad naming, never meant to resolve.',
    ),
    AllowlistEntry(
        doc="README.md",
        symbol="/api/tracking/*",
        reason="Wildcard shorthand for a documented endpoint family, not a literal path.",
    ),
    AllowlistEntry(
        doc="README.md",
        symbol="/api/hooks/*",
        reason="Wildcard shorthand for a documented endpoint family, not a literal path.",
    ),
]


def _is_allowlisted(doc_rel: str, symbol: str) -> bool:
    for entry in ALLOWLIST:
        if entry.symbol == symbol and doc_rel.endswith(entry.doc):
            if not entry.reason.strip():
                raise ValueError(f"allowlist entry for {symbol!r} has no reason")
            return True
    return False


def _grep_whole_word(word: str, *, repo_root: Path = DWB_REPO_ROOT) -> bool:
    """True if ``word`` appears as a whole word anywhere in the search
    corpus (backend, frontend/src, docs, scripts, plus the two env-style
    files) under ``repo_root``."""
    targets = [
        str(repo_root / d) for d in _SYMBOL_SEARCH_DIRS if (repo_root / d).exists()
    ]
    targets += [
        str(repo_root / f) for f in _SYMBOL_SEARCH_FILES if (repo_root / f).is_file()
    ]
    if not targets:
        return False
    result = subprocess.run(
        ["grep", "-rlw"] + _GREP_EXCLUDES + [word] + targets,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return bool(result.stdout.strip())


def _registered_api_path_templates() -> set[tuple[str, ...]]:
    """Segment-tuples of every route FastAPI has registered, with each
    ``{param}`` segment normalized to a single wildcard marker ``"{}"``."""
    from app.main import app  # local import: avoid DB/app import at collection time

    templates: set[tuple[str, ...]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        segs = tuple(
            "{}" if seg.startswith("{") and seg.endswith("}") else seg
            for seg in path.strip("/").split("/")
        )
        templates.add(segs)
    return templates


def _path_only(span: str) -> str:
    """Strip an optional leading HTTP method, a trailing query string, and
    anything after the path itself (docs sometimes tack on an example JSON
    body, e.g. ``PATCH /api/sprints/X {"status": "completed"}``)."""
    stripped = _HTTP_METHOD_RE.sub("", span.strip())
    if not stripped:
        return ""
    token = stripped.split(None, 1)[0]
    return token.split("?", 1)[0]


def _is_api_path_candidate(span: str) -> bool:
    p = _path_only(span)
    return p.startswith("/api/") or p == "/api"


def _api_path_resolves(span: str, templates: set[tuple[str, ...]]) -> bool:
    """A doc path resolves if some registered route has the same length and
    the same literal segments in every non-param slot. A doc segment at a
    param slot is accepted as-is — docs commonly give a worked example with
    a real id (``/api/projects/5/team``) or a placeholder letter
    (``/api/sprints/X``) rather than FastAPI's own ``{param_name}`` spelling,
    and neither is drift."""
    doc_segs = _path_only(span).strip("/").split("/")
    for route_segs in templates:
        if len(route_segs) != len(doc_segs):
            continue
        if all(rs == "{}" or rs == ds for rs, ds in zip(route_segs, doc_segs)):
            return True
    return False


def _is_symbol_candidate(span: str) -> bool:
    return (
        bool(_IDENT_RE.fullmatch(span))
        and "_" in span
        and not span.endswith((".md", ".py"))
    )


def _extract_candidates(text: str) -> list[tuple[str, str]]:
    """[(kind, raw_backticked_span), ...] for every span worth checking.

    Deliberately narrow: a bare snake_case-with-underscore identifier, or an
    ``/api/...`` path (optionally method-prefixed). Anything else (a JSON
    key alone, a shell flag, a filename, a plain English word) is not a
    resolvable-reference claim this pass tries to verify — see the module
    docstring's boundary note. Dotted module-path references
    (``services/foo.py::bar``) are also out of scope for this pass.
    """
    out = []
    for m in _BACKTICK_RE.finditer(text):
        span = m.group(1)
        if _is_api_path_candidate(span):
            out.append(("api_path", span))
        elif _is_symbol_candidate(span):
            out.append(("symbol", span))
    return out


def find_unresolved_references(
    docs: list[Path] | None = None,
    *,
    repo_root: Path = DWB_REPO_ROOT,
) -> list[UnresolvedRef]:
    """Backticked symbol/endpoint references across ``docs`` (default:
    GATED_DOCS) that don't resolve against the current codebase, minus the
    allowlist. See the module docstring for what this cannot see."""
    if docs is None:
        docs = GATED_DOCS
    templates = None
    unresolved: list[UnresolvedRef] = []
    for doc in docs:
        if not doc.is_file():
            continue
        try:
            doc_rel = str(doc.relative_to(repo_root))
        except ValueError:
            doc_rel = str(doc)
        text = doc.read_text(encoding="utf-8")
        seen_in_doc: set[str] = set()
        for kind, span in _extract_candidates(text):
            if span in seen_in_doc:
                continue
            seen_in_doc.add(span)
            if _is_allowlisted(doc_rel, span):
                continue
            if kind == "api_path":
                if templates is None:
                    templates = _registered_api_path_templates()
                resolved = _api_path_resolves(span, templates)
            else:
                resolved = _grep_whole_word(span, repo_root=repo_root)
            if not resolved:
                unresolved.append(UnresolvedRef(doc=doc_rel, symbol=span, kind=kind))
    return unresolved

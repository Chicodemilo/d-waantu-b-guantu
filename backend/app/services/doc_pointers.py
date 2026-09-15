# Path: app/services/doc_pointers.py
# File: doc_pointers.py
# Created: 2026-09-14
# Purpose: Doc-pointer grounding lane (DWB-526). Enumerates the project's doc
#          corpus (root docs + docs/*.md) and BUILDS doc-kind SourceUnits for the
#          node registry (DWB-522): one unit per non-blank line (ref=doc relpath,
#          kind=doc, line_start=line_end=N, text=line) so register_sources mines
#          each doc's tags with cheap line refs. Re-registered on deploy-playbooks
#          events (root-doc touch); the (doc, relpath) refresh scope re-grounds a
#          doc in place. Docs carry no sha (working-tree state). Degrades to empty
#          on missing repo_path.
# Caller: DWB-527 event dispatch (deploy touch) -> node_registry.register_sources
# Callees: pathlib, app/services/node_registry.SourceUnit
# Data In: repo_path
# Data Out: (list[SourceUnit], prune_scope set)
# Last Modified: 2026-09-15 (DWB-549: node-scan exclusions at enumeration)

from pathlib import Path
from typing import TYPE_CHECKING

from app.config.node_scan import is_excluded
from app.services.node_registry import SourceUnit

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.node_registry import RegistrationResult

# Root-level docs treated as doc-kind pointer targets. Order is stable so a
# re-ground produces a deterministic target list. HANDOFF/README/ARCHITECTURE
# etc. are TL-owned root docs; grounding them is read-only.
ROOT_DOCS = (
    "ARCHITECTURE.md",
    "HANDOFF.md",
    "README.md",
    "INITIAL.md",
    "CLAUDE.md",
    "CODING_STANDARDS.md",
)

# Subdirectory whose *.md files also join the doc corpus.
DOCS_SUBDIR = "docs"


def enumerate_doc_targets(
    repo_path: str | None,
    *,
    exclusions: tuple[str, ...] | list[str] = (),
    include_excluded: bool = False,
) -> list[str]:
    """Repo-relative paths of every doc-kind target that exists on disk.

    Root docs (fixed list) plus every ``docs/*.md`` (sorted for determinism).
    Returns [] when repo_path is missing or does not exist - the caller then
    grounds nothing rather than erroring.

    DWB-549: paths matching the node-scan exclusion list are dropped here, at
    enumeration, so an excluded doc never becomes a SourceUnit.
    ``include_excluded=True`` returns the unfiltered candidate list, which
    build_doc_units uses to build a prune scope that still covers newly-excluded
    docs (their existing pointers must drop, not linger).
    """
    if not repo_path:
        return []
    root = Path(repo_path)
    if not root.exists():
        return []

    targets: list[str] = []
    for name in ROOT_DOCS:
        if (root / name).is_file():
            targets.append(name)

    docs_dir = root / DOCS_SUBDIR
    if docs_dir.is_dir():
        for md in sorted(docs_dir.glob("*.md")):
            targets.append(f"{DOCS_SUBDIR}/{md.name}")

    if include_excluded:
        return targets
    return [t for t in targets if not is_excluded(t, exclusions)]


def _read_lines(root: Path, rel: str) -> list[str] | None:
    try:
        return (root / rel).read_text(errors="replace").splitlines()
    except (OSError, UnicodeError):
        return None


def build_doc_units(
    repo_path: str | None,
    *,
    exclusions: tuple[str, ...] | list[str] = (),
) -> tuple[list[SourceUnit], set[tuple[str, str]]]:
    """Build doc-kind SourceUnits across the whole doc corpus, plus the prune
    scope covering every target (DWB-526).

    One SourceUnit per non-blank line of each doc: ``kind="doc"``,
    ``ref=<doc relpath>``, ``line_start == line_end == <1-based line no>``,
    ``text=<line content>``, no sha (docs are working-tree state, re-grounded on
    deploy events rather than sha-stamped). node_registry mines each line's tags,
    so a doc term grounds to its line - the "line refs where cheap" of DWB-526.

    The prune scope is every enumerated ``(doc, relpath)`` target, so re-running
    the pass replaces each doc's pointers with its current content (rotted line
    refs move, vanished terms prune). Returns ``([], set())`` when repo_path is
    missing/invalid.
    """
    # DWB-549: the prune scope spans every CANDIDATE doc, including ones the
    # exclusion list now drops, so switching an exclusion on removes the
    # pointers that doc already had instead of leaving them stranded.
    candidates = enumerate_doc_targets(repo_path, include_excluded=True)
    targets = [t for t in candidates if not is_excluded(t, exclusions)]
    if not candidates:
        return [], set()
    assert repo_path is not None  # enumerate returns [] when repo_path falsy
    root = Path(repo_path)

    units: list[SourceUnit] = []
    prune_scope: set[tuple[str, str]] = {("doc", t) for t in candidates}
    for rel in targets:
        lines = _read_lines(root, rel)
        if lines is None:
            continue
        for lineno, text in enumerate(lines, start=1):
            if not text.strip():
                continue
            units.append(
                SourceUnit(
                    kind="doc",
                    ref=rel,
                    text=text,
                    line_start=lineno,
                    line_end=lineno,
                )
            )
    return units, prune_scope


def ground_docs(
    db: "Session",
    project_id: int,
    repo_path: str | None,
) -> "RegistrationResult":
    """Re-ground doc pointers across the whole doc corpus (DWB-526).

    The deploy-playbooks touch update: rebuild doc-kind units for every root doc
    + docs/*.md and register them, replacing each doc's pointers in place. Does
    NOT commit (caller owns the transaction). Degrades to an empty result when
    repo_path is unusable / the corpus is empty.
    """
    from app.services.node_registry import RegistrationResult, register_sources

    from app.services.node_exclusion import patterns_for_project

    exclusions = patterns_for_project(db, project_id)
    units, prune = build_doc_units(repo_path, exclusions=exclusions)
    if not units and not prune:
        return RegistrationResult()
    return register_sources(db, project_id, units, prune_scope=prune)


# --- full-pass provider (DWB-527 nodeify seam) -------------------------------


def doc_provider(db: "Session", project, repo_path: str) -> list["SourceUnit"]:
    """Full-pass doc source provider for node_touch.nodeify (DWB-526/527).

    Registered via node_touch.register_source_provider('doc', ...) to REPLACE the
    light whole-file default with the line-ref-aware per-line indexer. Returns
    only the units (nodeify computes the prune scope + registers); best-effort
    ([] on any failure) per the provider contract.
    """
    from app.services.node_exclusion import patterns_for_project

    exclusions = patterns_for_project(db, getattr(project, "id", None))
    units, _ = build_doc_units(repo_path, exclusions=exclusions)
    return units


def _register_provider() -> None:
    """Plug doc_provider into the nodeify full pass (DWB-527 seam).

    Import-time side effect: importing this module (at app startup via
    playbook_deploy's top-level import) registers the richer doc extractor over
    node_touch's light default. Wrapped so it can never crash import.
    """
    try:
        from app.services import node_touch

        node_touch.register_source_provider("doc", doc_provider)
    except Exception:  # noqa: BLE001 - provider registration is best-effort
        import logging

        logging.getLogger(__name__).warning(
            "doc_provider registration skipped", exc_info=True
        )


# Landing the override (DWB-526): REPLACES node_touch's light whole-file
# doc_provider with the per-line line-ref indexer. Safe to register globally -
# node_touch's nodeify tests clear _PROVIDER_OVERRIDES via an autouse fixture, so
# this only takes effect in production (imported at startup via playbook_deploy).
_register_provider()

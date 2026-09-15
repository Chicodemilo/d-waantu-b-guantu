# Path: app/services/node_registry.py
# File: node_registry.py
# Created: 2026-09-14
# Purpose: Node registration (DWB-522). Turns tagged source text into LIGHT nodes
#          + pointers. Normalizes tags (lowercase + light stemming, reusing the
#          S76 keyword-extraction tokenizer/stopwords), merges normalized
#          collisions onto one node, and enforces the 2-DOMAIN GROUNDING RULE: a
#          tag becomes a node only once its pointers span 2+ distinct pointer
#          domains (code|memory|doc|ticket|session). No node-to-node edges are
#          stored - connection is derived from shared pointer refs (DWB-523). The
#          (project_id, kind, ref) triple is the refresh scope: re-registering a
#          ref replaces its pointers, so the pass is idempotent and rots/prunes
#          cleanly (DWB-527).
# Caller: app/services/node_match.py (read), app/routers/nodes.py, the nodeify
#         full pass + event-driven touch updates (DWB-527)
# Callees: app/services/keyword_extraction (tokenize, STOPWORDS), app/models/node
# Data In: db: Session, project_id: int, SourceUnit list (+ optional prune scope)
# Data Out: RegistrationResult (grounded / pruned / skipped tag counts)
# Last Modified: 2026-09-14

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.node import Node, NodePointer, NodePointerKind
from app.services.keyword_extraction import STOPWORDS, is_ticket_key, tokenize

# The 2-domain grounding threshold (Miles ruling). A tag registers as a node only
# once its pointers span at least this many distinct domains.
GROUNDING_MIN_DOMAINS = 2

# Valid pointer domains (mirrors NodePointerKind); used to validate SourceUnit.kind.
VALID_KINDS = frozenset(k.value for k in NodePointerKind)

# DWB-522 generic-tag suppression (Miles: no junk nodes). The 2-domain rule can't
# kill domain-generic words (doc, project, add, fix, test) - they ground
# EVERYWHERE, so they clear grounding trivially and then crown the weight
# ranking. This reuses the S76 TF-IDF insight: a tag whose document frequency is
# a large fraction of the whole corpus is boilerplate (IDF -> 0), anti-signal, and
# must NOT register as a node. Applied ONLY in the corpus-wide full pass
# (nodeify passes suppress_generic=True); incremental touches see too few docs for
# DF to mean anything and never suppress. A suppressed generic has no pointers, so
# an incremental touch can never resurrect it (it would need a surviving 2nd-domain
# pointer, which suppression removed) - the two paths stay consistent.
#
# GENERIC_DF_RATIO: suppress a tag present in >= this fraction of all corpus
#   documents (distinct (kind, ref) sources).
# GENERIC_MIN_DOCS: below this many documents, DF is not meaningful - never
#   suppress (protects small corpora + tests).
GENERIC_DF_RATIO = 0.30
GENERIC_MIN_DOCS = 8


def light_stem(word: str) -> str:
    """Conservative English stemmer for node normalization (DWB-522).

    Deliberately LIGHT - it collapses the common inflections that would
    otherwise split one concept across several tags (node/nodes, pointer/
    pointers, ground/grounding) without the aggressive truncation of a full
    Porter stemmer. Ticket keys never reach this (the caller skips them).

    Rules (first match wins), only for tokens longer than 3 chars:
      - '...ies' -> '...y'      (registries -> registry)
      - '...ing' -> '...'       (grounding -> ground)     [>=3 char stem]
      - '...ed'  -> '...'       (grounded -> ground)      [>=3 char stem]
      - '...es'  -> '...'       ONLY after a sibilant       (boxes -> box,
                                 matches -> match); otherwise falls through
      - '...s'   -> '...'       plain plural (nodes -> node, pointers -> pointer),
                                guarded against ss/us/is/os/as endings so
                                'status'/'analysis'/'class' survive intact.
    """
    w = word
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) - 3 >= 3:
        return w[:-3]
    if w.endswith("ed") and len(w) - 2 >= 3:
        return w[:-2]
    if w.endswith("es"):
        stem = w[:-2]
        if stem.endswith(("s", "x", "z", "ch", "sh")):
            return stem
        # else fall through to the plain-plural rule (nodes -> node, not nod)
    if (
        w.endswith("s")
        and not w.endswith(("ss", "us", "is", "os", "as"))
        and len(w) > 3
    ):
        return w[:-1]
    return w


def node_tokens(text: str) -> set[str]:
    """Normalize free text into a SET of node tags (DWB-522).

    Pipeline: reuse the S76 tokenizer (lowercase + kebab; ticket keys verbatim),
    drop English stopwords, then apply light stemming to non-ticket-key terms.
    Returns a set (per-source dedupe) so a term repeated within one source yields
    a single pointer for that source.
    """
    out: set[str] = set()
    for tok in tokenize(text):
        if is_ticket_key(tok):
            out.add(tok)
            continue
        if tok in STOPWORDS:
            continue
        stemmed = light_stem(tok)
        if stemmed and stemmed not in STOPWORDS:
            out.add(stemmed)
    return out


@dataclass
class SourceUnit:
    """One unit of source text to mine, tagged with WHERE it lives.

    text is mined for tags; every tag found gets a candidate pointer carrying
    this unit's (kind, ref, sha, line range). Multiple units may share a ref
    (e.g. distinct line ranges of one file) - each contributes its own pointers.
    """

    kind: str
    ref: str
    text: str
    sha: str | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass
class RegistrationResult:
    """Outcome of a registration pass, for telemetry + the nodeify report."""

    grounded_tags: list[str] = field(default_factory=list)   # tag now a live node
    pruned_tags: list[str] = field(default_factory=list)      # node removed (<2 domains)
    skipped_tags: list[str] = field(default_factory=list)     # candidate never grounded
    suppressed_tags: list[str] = field(default_factory=list)  # dropped as generic (high DF)
    pointers_written: int = 0
    scope_refs: int = 0


class NodeRegistryError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class _Candidate:
    kind: str
    ref: str
    sha: str | None
    line_start: int | None
    line_end: int | None


def register_sources(
    db: Session,
    project_id: int,
    units: list[SourceUnit],
    *,
    prune_scope: set[tuple[str, str]] | None = None,
    suppress_generic: bool = False,
) -> RegistrationResult:
    """Register a batch of source units into nodes + pointers (DWB-522).

    The unit of refresh is the (kind, ref) pair. Every (kind, ref) present in
    ``units`` - plus any pair passed in ``prune_scope`` - is CLEARED of its
    existing pointers first, then the batch's fresh pointers are inserted for
    grounded tags only. This makes the pass idempotent (re-running yields the
    same rows), refreshes rotted sha/line ranges, and prunes a ref's tags that
    vanished from the source. ``prune_scope`` lets a caller drop a ref that
    produced NO units this pass (a deleted file / vanished commit).

    Grounding is recomputed for every affected tag against the union of its
    surviving DB pointers and this batch's pointers: >= GROUNDING_MIN_DOMAINS
    distinct domains -> the tag is (or stays) a node with all its pointers
    persisted; below threshold -> any existing node is removed and its pointers
    dropped (a one-domain word is not a node).

    ``suppress_generic`` (set by the corpus-wide nodeify pass) additionally drops
    domain-generic tags whose document frequency across THIS batch is >=
    GENERIC_DF_RATIO of all documents - boilerplate the grounding rule can't kill
    on its own (see the constants). It is meaningful only when the batch spans the
    whole corpus; incremental callers leave it False.

    This function does NOT commit; the caller (router via get_db) owns the
    transaction, per the service-layer rule.
    """
    result = RegistrationResult()

    # 1. Validate kinds + group this batch's candidate pointers by tag.
    batch: dict[str, list[_Candidate]] = {}
    scope: set[tuple[str, str]] = set(prune_scope or set())
    for u in units:
        if u.kind not in VALID_KINDS:
            raise NodeRegistryError(
                "invalid_kind",
                f"pointer kind '{u.kind}' is not one of {sorted(VALID_KINDS)}",
            )
        if not u.ref or not u.ref.strip():
            raise NodeRegistryError("invalid_ref", "source unit ref is empty")
        scope.add((u.kind, u.ref))
        for tag in node_tokens(u.text):
            batch.setdefault(tag, []).append(
                _Candidate(u.kind, u.ref, u.sha, u.line_start, u.line_end)
            )
    result.scope_refs = len(scope)

    # 1b. Generic-tag suppression (corpus pass only). Document frequency = number
    # of distinct (kind, ref) documents a tag appears in; total_docs = distinct
    # documents in the batch. A tag over the ratio is boilerplate and is excluded
    # from grounding below (and pruned if it somehow already has a node).
    generic_tags: set[str] = set()
    if suppress_generic:
        all_docs = {(c.kind, c.ref) for ptrs in batch.values() for c in ptrs}
        total_docs = len(all_docs)
        if total_docs >= GENERIC_MIN_DOCS:
            threshold = GENERIC_DF_RATIO * total_docs
            for tag, ptrs in batch.items():
                df = len({(c.kind, c.ref) for c in ptrs})
                if df >= threshold:
                    generic_tags.add(tag)

    # 2. Clear the refresh scope. Capture the tags whose pointers we drop so they
    #    get re-grounded below even if this batch produced nothing for them.
    affected_tags: set[str] = set(batch.keys())
    if scope:
        cleared = db.execute(
            select(NodePointer.tag).where(
                NodePointer.project_id == project_id,
                _scope_predicate(scope),
            )
        ).scalars().all()
        affected_tags.update(cleared)
        db.execute(
            delete(NodePointer).where(
                NodePointer.project_id == project_id,
                _scope_predicate(scope),
            )
        )
        db.flush()

    # 3. Re-ground every affected tag against surviving pointers + this batch.
    for tag in sorted(affected_tags):
        surviving = db.execute(
            select(NodePointer).where(
                NodePointer.project_id == project_id,
                NodePointer.tag == tag,
            )
        ).scalars().all()
        surviving_kinds = {p.kind.value for p in surviving}
        batch_ptrs = batch.get(tag, [])
        batch_kinds = {c.kind for c in batch_ptrs}
        total_kinds = surviving_kinds | batch_kinds

        node = _get_node(db, project_id, tag)

        # Generic boilerplate (corpus pass): never a node. Prune if one exists.
        if tag in generic_tags:
            if node is not None:
                db.delete(node)
                db.flush()
            result.suppressed_tags.append(tag)
            continue

        if len(total_kinds) >= GROUNDING_MIN_DOMAINS:
            if node is None:
                node = Node(project_id=project_id, tag=tag, weight=1)
                db.add(node)
                db.flush()
            for c in batch_ptrs:
                db.add(
                    NodePointer(
                        project_id=project_id,
                        node_id=node.id,
                        tag=tag,
                        kind=NodePointerKind(c.kind),
                        ref=c.ref,
                        sha=c.sha,
                        line_start=c.line_start,
                        line_end=c.line_end,
                    )
                )
                result.pointers_written += 1
            # weight = number of DISTINCT (kind, ref) groundings, NOT the raw
            # pointer count. This keeps ranking a measure of how many distinct
            # places ground a tag (grounding breadth) rather than letting a lane
            # that emits per-line pointers (DWB-525/526) inflate a common tag's
            # weight by how many lines of one file mention it.
            distinct_sources = {(p.kind.value, p.ref) for p in surviving} | {
                (c.kind, c.ref) for c in batch_ptrs
            }
            node.weight = len(distinct_sources)
            db.flush()
            result.grounded_tags.append(tag)
        else:
            # Below the grounding threshold: not a node. Drop any existing node
            # (its surviving pointers cascade) and skip the batch pointers.
            if node is not None:
                db.delete(node)
                db.flush()
                result.pruned_tags.append(tag)
            else:
                result.skipped_tags.append(tag)

    return result


def _scope_predicate(scope: set[tuple[str, str]]):
    """Build a predicate matching any (kind, ref) pair in the scope."""
    from sqlalchemy import tuple_

    # Use a tuple IN for a compact, index-friendly predicate.
    pairs = [(NodePointerKind(k), r) for (k, r) in scope]
    return tuple_(NodePointer.kind, NodePointer.ref).in_(pairs)


def _get_node(db: Session, project_id: int, tag: str) -> Node | None:
    return db.execute(
        select(Node).where(Node.project_id == project_id, Node.tag == tag)
    ).scalar_one_or_none()

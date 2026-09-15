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
# Last Modified: 2026-09-15 (DWB-538 suppression floor; DWB-545 node_token_counts)

from __future__ import annotations

import math
import re
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
#
# DWB-522 rework: dropped from 0.30 to 0.12. At corpus scale the denominator is
# thousands of distinct code-file refs, so even a boilerplate token like 'key'
# only appears in ~7% of docs and slipped under 0.30 - suppression was a no-op
# and the top-20 stayed generic mush. Ratio-suppression alone is a coarse net
# (it only catches truly corpus-wide terms); the real fix is the TF-IDF weight
# below (ubiquitous terms score toward 0) plus the NODE_STOPWORDS list. 0.12
# now catches the clearly-ubiquitous long tail without touching domain vocab.
GENERIC_DF_RATIO = 0.12
GENERIC_MIN_DOCS = 8

# DWB-538: absolute document-frequency FLOOR for suppression. The ratio alone
# collapses on small corpora: at 8 docs the threshold is 0.96 (every tag is
# "generic"), and for 9-16 docs it is under 2, which is the df every grounded
# tag has BY DEFINITION under the 2-domain rule - so nodeify on an 8..16-doc
# project suppressed every node it had just grounded. A tag seen in only two
# documents can never be boilerplate; requiring df >= 3 as well as df >= ratio*N
# ties suppression to "strictly more than the grounding minimum" at every scale
# (a floor, unlike a higher GENERIC_MIN_DOCS, has no cliff where suppression
# switches off entirely for a mid-sized corpus). Above ~25 docs the ratio term
# dominates and behaviour is unchanged.
GENERIC_MIN_DF = 3

# DWB-522 rework: project-agnostic node stoplist. These are generic
# code-keyword / English-boilerplate terms that ground in 2+ domains in ANY
# software project (they appear in code AND memory AND docs everywhere) yet carry
# no wayfinding signal - a node called "value" or "return" points nowhere useful.
# The S76 STOPWORDS list deliberately excludes DWB domain vocab (ticket, sprint,
# agent) because TF-IDF is supposed to sink cross-session boilerplate; here the
# corpus is code+memory+docs of a single project where those same generic-code
# terms are the noise floor, so we filter them at tokenization. This is
# INTENTIONALLY narrow: language/structural keywords and pure-filler nouns only,
# NOT anything that could be a project's actual subject. Applied unconditionally
# in node_tokens (both full pass and incremental) so a generic term never even
# becomes a candidate pointer. Kept separate from STOPWORDS so the session-tag
# ranker (which wants "agent"/"ticket") is unaffected.
NODE_STOPWORDS: frozenset[str] = frozenset(
    {
        # language / structural keywords
        "true", "false", "none", "null", "return", "def", "class", "self",
        "import", "from", "function", "func", "var", "let", "const", "async",
        "await", "yield", "lambda", "pass", "raise", "except", "try", "finally",
        "elif", "else", "for", "while", "break", "continue", "global", "type",
        "int", "str", "bool", "float", "list", "dict", "set", "tuple", "enum",
        # generic code-vocab nouns/verbs that ground everywhere with no signal
        "value", "values", "key", "keys", "name", "names", "id", "ids", "field",
        "fields", "param", "params", "arg", "args", "kwarg", "kwargs", "result",
        "results", "data", "item", "items", "object", "objects", "instance",
        "method", "methods", "call", "calls", "get", "add", "remove",
        "create", "update", "delete", "write", "read", "run", "make", "use",
        "used", "using", "check", "handle", "fail", "fix", "detail",
        "details", "summary", "content", "text", "string", "number", "count",
        "total", "line", "lines", "path", "file", "files", "row", "rows",
        "column", "columns", "record", "records", "entry", "entries",
        # generic status / boolean-ish adjectives
        "active", "inactive", "open", "close", "closed", "done", "todo",
        "valid", "invalid", "default", "optional", "required",
        # generic connective / structural filler surfaced in code+prose
        "block", "rule", "rules", "link", "note", "notes", "case", "step",
        "steps", "part", "parts", "point", "points", "flag", "flags", "mode",
        # DWB-522 rework: generic filler that crowned the live top-20 (project 1).
        # These span code+memory+docs everywhere yet point to no concept. Kept
        # OUT deliberately (they ARE real DWB concepts): spawn, roster, index,
        # scope, command, contract, score, feed, guard.
        "top", "unique", "fresh", "found", "next", "end", "base", "written",
        "manual", "action", "edit", "user", "plain", "stale", "dropped",
        "resolve", "resolved", "updated", "current", "full", "clean",
        "single", "double", "raw", "live", "dead", "hard", "soft", "plus",
        "minus", "old", "big", "small", "long", "short", "first", "last",
        "same", "each", "every", "still", "back", "away", "within", "across",
        "per-line", "one-domain", "two-domain", "cross-session",
        # light_stem artifacts of generic verbs above (the post-stem check sees
        # these forms, not the source word): resolved/resolving -> "resolv",
        # dropped -> "dropp", updated/updating -> "updat", removed -> "remov",
        # returned -> "return" (already listed), handled -> "handl".
        "resolv", "dropp", "updat", "remov", "handl", "creat", "delet",
        # DWB-522 rework, second live pass: remaining generic filler in top-25.
        "instead", "left", "right", "window", "reference", "can-t", "won-t",
        "don-t", "isn-t", "doesn-t", "wasn-t", "aren-t", "lets", "goes",
        "went", "gets", "puts", "kept", "keep", "keeps", "given", "gives",
        "seen", "saw", "says", "said", "want", "wants", "need", "needs",
        "instead-of", "rather", "either", "neither", "whether",
    }
)


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


# DWB-522 rework: minimum length for a non-ticket-key node tag. Single/double
# letters ("d" and "b" from "d'waantu b'guantu", stray code identifiers) are pure
# noise - they grounded in 2+ domains and crowded the ranking. Ticket keys bypass
# this (they are always meaningful).
MIN_TAG_LEN = 3

# DWB-522 rework: reject tokens that are a hex-sha-like blob (git short/long shas
# like "4c8f7a8" / "93c5fd" surfaced as df=2 IDF noise) or a bare number+unit
# measure ("10000m", "14m", "60min", "2-second"). These carry no wayfinding value
# and never denote a concept. A token qualifies as sha-like when it is all hex
# digits (a-f + 0-9), 6-40 chars long, AND carries BOTH a letter and a DIGIT: the
# digit requirement (Archie's review catch) is what separates a real sha from a
# pure-a-f English word - "facade"/"decade"/"deface"/"accede" are all valid hex
# strings but have no digit, so they survive; real shas virtually always mix in a
# digit. Pure-digit tokens are already dropped earlier (normalize_term rejects
# no-alpha tokens); this branch is only about the mixed hex blobs.
_HEXSHA_RE = re.compile(r"^[0-9a-f]{6,40}$")
_MEASURE_RE = re.compile(r"^\d+(?:-?[a-z]{1,4})?$")


def _is_noise_tag(tag: str) -> bool:
    """True for tokens that ground but carry no concept (DWB-522 rework)."""
    if len(tag) < MIN_TAG_LEN:
        return True
    core = tag.replace("-", "")
    if _MEASURE_RE.match(tag):
        return True
    # hex-sha-like: hex-only AND contains BOTH a letter and a digit (catches
    # "4c8f7a8"/"93c5fd" while sparing pure-a-f words like "facade"/"decade").
    if (
        _HEXSHA_RE.match(core)
        and any(c.isalpha() for c in core)
        and any(c.isdigit() for c in core)
    ):
        return True
    return False


def node_token_counts(text: str) -> dict[str, int]:
    """Normalize free text into node tags WITH their occurrence counts.

    The single definition of the tag pipeline: reuse the S76 tokenizer (lowercase
    + kebab; ticket keys verbatim), drop English stopwords + NODE_STOPWORDS +
    noise tokens, then apply light stemming to non-ticket-key terms.

    Registration only needs the tag SET (see node_tokens) because a term repeated
    within one source still yields one pointer for that source. Retrieval
    (DWB-545) also wants the counts: a tag a ticket mentions repeatedly is what
    the ticket is ABOUT, which is the term-frequency half of ranking.
    """
    out: dict[str, int] = {}
    for tok in tokenize(text):
        if is_ticket_key(tok):
            out[tok] = out.get(tok, 0) + 1
            continue
        if tok in STOPWORDS or tok in NODE_STOPWORDS or _is_noise_tag(tok):
            continue
        stemmed = light_stem(tok)
        # Re-check all filters post-stem so a plural of a stopword
        # ("values" -> "value") or a stem that fell below MIN_TAG_LEN is dropped.
        if (
            stemmed
            and stemmed not in STOPWORDS
            and stemmed not in NODE_STOPWORDS
            and not _is_noise_tag(stemmed)
        ):
            out[stemmed] = out.get(stemmed, 0) + 1
    return out


def node_tokens(text: str) -> set[str]:
    """Normalize free text into a SET of node tags (DWB-522).

    Per-source dedupe: a term repeated within one source yields a single pointer
    for that source. Thin wrapper over node_token_counts so the pipeline has one
    definition (DWB-545).
    """
    return set(node_token_counts(text))


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
            # DWB-538: floor the ratio threshold so a small corpus never treats
            # the 2-domain grounding minimum itself as generic.
            threshold = max(GENERIC_DF_RATIO * total_docs, GENERIC_MIN_DF)
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

    # 2b. Corpus size N = distinct (kind, ref) documents across ALL of the
    # project's surviving pointers, PLUS this batch's docs (batch pointers are not
    # in the DB yet). Sourced from the DB (not just the batch) so the TF-IDF
    # weight below is consistent whether this is a corpus-wide nodeify pass or a
    # single-ref incremental touch - both rank against the same denominator.
    #
    # PERF NOTE (DWB-522 review): this is a full DISTINCT (kind, ref) scan of the
    # project's node_pointers on EVERY call, including single-file incremental
    # touches. It's cheap at current scale (~15k pointers) and the index on
    # (project_id, kind, ref) covers it. If incremental commits ever feel slow,
    # this is the spot to optimize - memoize N per request or maintain a running
    # distinct-doc counter rather than re-scanning here.
    db_docs = set(
        db.execute(
            select(NodePointer.kind, NodePointer.ref).where(
                NodePointer.project_id == project_id
            ).distinct()
        ).all()
    )
    corpus_docs = {(k.value if hasattr(k, "value") else k, r) for k, r in db_docs}
    corpus_docs |= {(c.kind, c.ref) for ptrs in batch.values() for c in ptrs}
    total_corpus_docs = len(corpus_docs)

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
            # weight = TF-IDF RELEVANCE SCORE (DWB-522 rework), not raw grounding
            # breadth. df = distinct (kind, ref) groundings for this tag (still
            # counting per-line pointers of one file ONCE - DWB-525/526 can't
            # inflate a tag); N = total distinct docs in the corpus. Old weight =
            # df alone crowned the most ubiquitous terms; here IDF = log((N+1)/
            # (df+1)) sinks them, so score = df * IDF peaks for terms that ground
            # in a MEANINGFUL-but-not-universal number of places. A term in nearly
            # every doc -> IDF ~ 0 -> low score; a term in one specific spot pair
            # -> low df -> low score; the middle band (a real cross-cutting
            # concept) wins. Reuses the S76 rank_tfidf shape (keyword_extraction).
            distinct_sources = {(p.kind.value, p.ref) for p in surviving} | {
                (c.kind, c.ref) for c in batch_ptrs
            }
            df = len(distinct_sources)
            idf = math.log((total_corpus_docs + 1) / (df + 1))
            node.weight = max(1, round(df * idf))
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

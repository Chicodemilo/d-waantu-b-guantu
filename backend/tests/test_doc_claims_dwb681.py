# Path: tests/test_doc_claims_dwb681.py
# File: test_doc_claims_dwb681.py
# Created: 2026-10-12 (DWB-681)
# Purpose: Fail when a doc asserts a file path that is not true for the reader
#          it is written for. Class 1 (exists) and class 2 (reader-relative).
# Caller: pytest
# Callees: app.services.playbook_deploy (the deploy manifest, imported not restated)
# Data In: CLAUDE.md, README.md, ARCHITECTURE.md, the three docs/ playbooks
# Data Out: assertions naming file, line, asserted path and failed class
# Last Modified: 2026-10-12 (DWB-681)

"""Mechanical guard against docs that assert paths which do not exist.

WHY THIS EXISTS. Every doc defect found on 2026-10-12 was found by a person
reading carefully, and there was no mechanism. `.claude/hooks/guard-root-docs.py`
was asserted as shipping via deploy-playbooks and had never existed anywhere;
three paths every agent is told to read could not exist on this repo because
deploy skips itself. Both shapes are mechanically checkable and neither was
being checked.

THE TWO CLASSES.

  CLASS 1, EXISTS. A path asserted in any of the six documents resolves
  somewhere in this repo.

  CLASS 2, READER-RELATIVE. The question is not whether a path exists HERE, it
  is whether it exists WHERE THE READER IS. The three playbooks are deployed to
  consumer repos, so they have six readers: this repo and five consumers. A
  path correct here and absent on consumers is as broken as the reverse, and
  2026-10-12 produced one defect in each direction.

THE DISCRIMINATOR, WHICH IS THE WHOLE REASON THIS SURVIVES.

  An INSTRUCTION must resolve where the reader is.
  A PROVENANCE CITATION must resolve where the behaviour lives.

Dolores checked 64 references by hand and found ten present here and absent on
every consumer, of which exactly ONE was a defect; the other nine cite server
internals (`backend/app/...`, `services/...`) that nobody is asked to open. A
check that cannot tell those apart fails on nine false positives and gets
deleted inside a week. The rule encoded below splits on the first path segment:
`.claude/`, `.dwb/` and `scripts/hooks/` are things a reader opens, so they are
reader-relative; everything else is provenance and is only required to exist
here. Measured against the same corpus, that rule yields exactly ten provenance
paths, matching her hand count.

A reader-relative path satisfies the DWB reader either by existing here OR by
the same line carrying a provenance alternative that exists here, which is the
`(in the DWB repo itself, docs/...)` pattern the DWB-675 fixes established.

RUNTIME STATE IS NOT A BROKEN PATH, AND THE REPO DECIDES WHICH IS WHICH.
`.claude/ALERTS_PENDING.md` is written by an endpoint and deleted when alerts
clear, so it is usually absent and that is correct. Rather than an exclusion
list, which is where the next defect hides, this defers to git: a path the repo
ignores is declared runtime state by the repo itself and is not existence
checked. `.gitignore:41` is that declaration for ALERTS_PENDING.md.

WHAT THIS DOES NOT CATCH, AND THE MISREADING TO EXPECT.

THIS FILE BEING GREEN IS NOT EVIDENCE THAT THE DOCUMENTATION IS CORRECT. It is
evidence that the things the documentation POINTS AT are there. Those are very
different claims, and the predictable failure after this ships is someone
treating a green suite as coverage of the doc layer and skipping the human pass.
Do not cite this file as that coverage. If you are about to write "the doc
checks pass" as a reason not to read something, you have hit the exact gap this
paragraph exists to flag.

  It proves things EXIST. It cannot prove the sentence around them is true.
  `gate-status` resolved perfectly while being documented as covering a set of
  nine gates when it returned six. Every token in that sentence checked out; the
  sentence was still false. No existence check would ever have seen it, and this
  one would have reported the file clean.

  It cannot catch a document contradicting itself. The team_lead playbook once
  said three owned root docs in one paragraph and five 580 lines later, and
  every identifier in both sentences resolved. Both halves of a
  self-contradiction have valid referents, which is exactly why no sweep sees
  it.

  MOST OF THE PLAYBOOK TEXT HAS NO EXTRACTION HANDLE AT ALL. This test proves
  that things EXIST and that a cited path RESOLVES. It never proves a sentence
  is true. Prose that describes behaviour without naming a path, route or
  symbol gives nothing to extract, so nothing here reaches it, and that is the
  majority of these documents by volume. Dolores's wording, added because the
  people who most need it are reading this file rather than a closed ticket.

  Concretely: the meaning defects found on 2026-10-12 were claims whose every
  identifier resolved perfectly, and this suite is green on all of them. The
  `token_budget.py` comment contradicting its own constants forty lines later
  is not even in this corpus, which is six documents and no `.py` files.

  `project_rules_*.md` ARE NOT IN SCOPE, on any box. Deploy never overwrites
  them, they are per-box, and no sweep run from this repo can read the five
  consumer copies. There is a live hand-copy variant of the reader-relative
  defect that lands there: an agent reproduced an instruction out of a playbook
  into its own `project_rules_*.md`, which strips the provenance that would have
  prompted a reachability check, and deploy cannot ship a correction to it.
  Blast radius was swept and is clean; the SHAPE is open and this test cannot
  see it.

Those remain human work; they are DWB-676's two passes.
"""

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from app.services.playbook_deploy import (
    AGENT_DEF_FILES, AUX_DOCS, DWB_COMMANDS_DIR, DWB_HOOK_SCRIPTS_DIR,
    PLAYBOOK_FILES, _ROOT_DOC_STUBS, _scrub_variant_blocks,
)

# The doc corpus root. Overridable so the corpus can be pointed at a HISTORICAL
# checkout while the import graph above stays satisfiable from the current tree.
# DWB-676 shape 4: a test that characterises a before state must be collectable
# in that state, and this module imports names that did not exist before today.
# Checking out an old tree wholesale would die at collection with an ImportError
# - still red, but proving "this file does not import" rather than "the docs
# were wrong", which is a failure that looks like the right failure.
REPO_ROOT = Path(os.environ.get("DWB_DOC_ROOT") or Path(__file__).resolve().parents[2])

# The three playbooks are DEPLOYED, so they are read on six repos.
DEPLOYED_DOCS = [f"docs/{fn}" for fn in PLAYBOOK_FILES.values()]
# These are this repo's own reference docs; their only reader is here.
LOCAL_DOCS = ["CLAUDE.md", "README.md", "ARCHITECTURE.md"]
ALL_DOCS = LOCAL_DOCS + DEPLOYED_DOCS

# Roots a path in these docs may legitimately be written relative to.
SEARCH_ROOTS = [
    REPO_ROOT, REPO_ROOT / "backend", REPO_ROOT / "backend" / "app",
    REPO_ROOT / "frontend", REPO_ROOT / "frontend" / "src",
]

# First path segments a READER opens. Everything else is provenance.
READER_SEGMENTS = {".claude", ".dwb"}
READER_PREFIXES = ("scripts/hooks",)

_TICK = re.compile(r"`([^`\n]+)`")
_TEMPLATE = set("<>~$*?{}|")
_FILE_EXT = (
    ".py", ".md", ".json", ".sh", ".js", ".jsx", ".css",
    ".yml", ".yaml", ".toml", ".txt", ".ini", ".cfg",
)


def _as_path_assertion(token: str) -> str | None:
    """A literal path assertion, or None.

    Deliberately narrow. A token with no separator is a NAME, not a path; a
    token with no extension and no trailing slash is a route tail or a symbol
    (`memory/append`, `hooks/useFuzzyFilter`) and belongs to classes 3 and 4.
    Narrowing here is the scope cut the ticket asks for in place of an
    exclusion list.
    """
    t = token.strip()
    if not t or " " in t or "/" not in t:
        return None
    if _TEMPLATE & set(t):            # <repo>/..., ~/..., $VAR/...
        return None
    if "..." in t:                    # elided route fragment
        return None
    if t.startswith(("http://", "https://", "/api/", "api/")):
        return None
    t = t.removeprefix("./")
    if t.startswith("/"):             # absolute: machine-specific, not ours
        return None
    is_dir_ref = t.endswith("/")
    t = t.rstrip("/")
    if not t:
        return None
    if not (t.endswith(_FILE_EXT) or is_dir_ref):
        return None
    return t


@lru_cache(maxsize=None)
def _git_ignored(rel: str) -> bool:
    """Does this repo declare `rel` to be generated state?

    Deferring to .gitignore rather than keeping a list of runtime files: the
    repo already records which paths it generates, and a second list would go
    stale independently.

    BOTH FORMS ARE TRIED, and the reason is not cosmetic. A gitignore pattern
    written `dir/` matches only a DIRECTORY, and git decides that by looking at
    disk - so `check-ignore .dwb` misses while `check-ignore .dwb/` hits, on a
    tree where `.dwb` has not been created yet. Testing only the stripped form
    makes this function's answer depend on whether the generated thing happens
    to exist right now, which is exactly the question it is supposed to be
    independent of. Found when the corpus was pointed at a fresh worktree.
    """
    for form in (rel, rel + "/"):
        try:
            r = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", form],
                capture_output=True, timeout=15,
            )
            if r.returncode == 0:
                return True
        except Exception:      # pragma: no cover - git absent
            return False
    return False


@lru_cache(maxsize=None)
def _resolves_here(rel: str) -> bool:
    return any((root / rel).exists() for root in SEARCH_ROOTS)


def _is_reader_relative(rel: str) -> bool:
    return rel.split("/")[0] in READER_SEGMENTS or rel.startswith(READER_PREFIXES)


def _consumer_view() -> set[str]:
    """Every path a CONSUMER repo has, derived from the deploy manifest.

    Imported from playbook_deploy rather than restated, so a change to what
    deploy ships cannot silently diverge from what this test believes it ships.
    """
    paths: set[str] = {".claude", ".dwb", "scripts/hooks"}
    for fn in PLAYBOOK_FILES.values():
        paths.add(f".claude/{fn}")
    for rel in AUX_DOCS:
        paths.add(f".claude/{rel}")
        paths.add(str(Path(f".claude/{rel}").parent))
    paths.add(".claude/agents")
    for fn in AGENT_DEF_FILES:
        paths.add(f".claude/agents/{fn}")
    paths.add(".claude/commands")
    if DWB_COMMANDS_DIR.is_dir():
        for src in DWB_COMMANDS_DIR.glob("*.md"):
            paths.add(f".claude/commands/{src.name}")
    for n in ("team_lead", "pm", "worker"):
        paths.add(f".claude/project_rules_{n}.md")
    paths.add(".claude/settings.json")
    paths.add(".claude/settings.local.json")
    if DWB_HOOK_SCRIPTS_DIR.is_dir():
        for src in DWB_HOOK_SCRIPTS_DIR.iterdir():
            if src.is_file() and not src.name.startswith("."):
                paths.add(f"scripts/hooks/{src.name}")
    paths.update(_ROOT_DOC_STUBS)
    paths.add("CODING_STANDARDS.md")
    paths.add(".dwb/memory")
    return paths


@lru_cache(maxsize=None)
def _source_lines(doc: str) -> tuple:
    p = REPO_ROOT / doc
    return tuple(p.read_text(encoding="utf-8").splitlines()) if p.is_file() else ()


def _source_lineno(doc: str, raw: str) -> int | None:
    """Line number in the SOURCE file for a token seen in a rendered copy.

    Scrubbing a variant block shifts every line after it, so a line number taken
    from the rendered text points at the wrong line in `docs/` - which is worse
    than no line number, because it looks actionable and is not. The raw token
    is distinctive enough to find its way home.
    """
    needle = f"`{raw}`"
    for i, line in enumerate(_source_lines(doc), 1):
        if needle in line:
            return i
    return None


def _loc(doc: str, raw: str, rendered_lineno: int) -> str:
    n = _source_lineno(doc, raw)
    return f"{doc}:{n}" if n else f"{doc}:~{rendered_lineno} (rendered)"


def _scan_text(d, text):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in _TICK.finditer(line):
            rel = _as_path_assertion(m.group(1))
            if rel:
                out.append((d, i, m.group(1).strip(), rel, line))
    return out


def _collect(docs):
    """[(doc, lineno, raw_token, rel_path, whole_line)] for every assertion."""
    out = []
    for d in docs:
        p = REPO_ROOT / d
        if not p.is_file():
            continue
        out.extend(_scan_text(d, p.read_text(encoding="utf-8")))
    return out


# The four variant renders deploy can produce, as (jira_enabled, human_memory).
# Every live project is one of these.
VARIANTS = [(False, True), (False, False), (True, True), (True, False)]
# This repo's own keys: non-Jira, human_memory.
DWB_VARIANT = (False, True)


def _collect_rendered(docs, jira_enabled, human_memory):
    """Assertions as a reader IN THAT MODE actually sees them.

    A MODE-GATED CLAIM CANNOT BE CHECKED FROM THE `docs/` SOURCE, and this is
    the whole reason this function exists rather than `_collect`. Both branches
    of every variant block live in the source, so a stock-only instruction reads
    there as an unqualified one. Deploy strips the branch that does not apply,
    so the question "is this true for its reader" is only answerable against the
    scrubbed text.

    Dolores hit this on DWB-676 and nearly filed it: stick redemption is
    documented against `POST /api/agents/{id}/memory/append`, which is sealed at
    409 under human_memory, and from `docs/` that reads as a documented remedy
    that cannot be exercised. It is not a defect - the deployed human_memory
    copy carries "Redeeming a stick does not work on this project" in a
    `human-memory-only` block, and deploy strips the stock branch. A check that
    fires on something correctly documented gets suppressed within a week, and
    then it is not guarding its real class either.

    Measured on this corpus: nine path assertions sit inside variant blocks
    today (`stock-memory-only` and `human-memory-only`). None is a false
    positive yet, which is exactly why this is done BY CONSTRUCTION rather than
    left to whoever edits the playbooks next to remember.

    Rendering from source with the mode keys rather than reading `.claude/`
    directly: the render is deterministic and cannot be stale, and
    test_doc_drift_dwb569 already guards `.claude/` against drifting from
    `docs/`. `_scrub_variant_blocks` is imported, never restated.
    """
    out = []
    for d in docs:
        p = REPO_ROOT / d
        if not p.is_file():
            continue
        rendered = _scrub_variant_blocks(
            p.read_text(encoding="utf-8"),
            jira_enabled=jira_enabled, human_memory=human_memory,
        )
        out.extend(_scan_text(d, rendered))
    return out


def _has_provenance_alternative(line: str, rel: str) -> bool:
    """Does this line also name a path that EXISTS HERE and is not `rel`?

    This is the `(in the DWB repo itself, docs/...)` pattern the DWB-675 fixes
    established: the instruction names the consumer path, and the parenthetical
    tells a reader on this repo where the same content actually is.

    IT KEYS ON RESOLUTION, NEVER ON PHRASING, and that is deliberate. Dolores
    audited this same family with an exact-substring check for the canonical
    clause and got two wrong answers in five minutes, in opposite directions:
    one run called a correct line broken because the author had written the
    clause as a running sentence instead of a parenthetical, and a second run
    with a broken normalisation called all six broken. The documents were fine
    both times. `docs/worker_playbook.md:510` is that line and it is still
    phrased differently today; this function passes it, while a substring check
    for "(in the DWB repo itself," still reports it missing.

    Three authors across three files will not converge on one wording, so any
    check that keys on the words fails the first time somebody rewrites a
    sentence correctly - and a check that fires on correct prose gets suppressed,
    which costs the real defect class too.
    """
    for m in _TICK.finditer(line):
        other = _as_path_assertion(m.group(1))
        if other and other != rel and _resolves_here(other):
            return True
    return False


class TestDocsExist:
    """CLASS 1: an asserted path resolves in this repo."""

    def test_the_scan_sees_the_documents(self):
        """Anti-vacuous. If the corpus is empty every assertion below is free,
        and a silently-empty sweep is how this whole defect family reads green."""
        missing = [d for d in ALL_DOCS if not (REPO_ROOT / d).is_file()]
        assert not missing, f"documents named by this test do not exist: {missing}"
        rows = _collect(ALL_DOCS)
        assert len(rows) >= 50, (
            f"only {len(rows)} path assertions found across {len(ALL_DOCS)} docs; "
            "the extractor has probably stopped matching"
        )

    def test_every_asserted_path_exists(self):
        """The discriminator applies here too, and this is the one place it is
        easy to get wrong. A reader-relative path inside a DEPLOYED doc is not
        required to exist here - that is precisely the case class 2 judges, and
        checking it twice under class 1 would report six false positives on
        paths that are correct for the consumer reading them."""
        broken = []
        for d, i, raw, rel, _line in _collect(ALL_DOCS):
            if _git_ignored(rel):
                continue          # repo declares this generated, see docstring
            if d in DEPLOYED_DOCS and _is_reader_relative(rel):
                continue          # class 2 owns this one, both directions
            if not _resolves_here(rel):
                broken.append(f"{d}:{i}  asserts `{raw}`  [CLASS 1: path does "
                              f"not exist in this repo]")
        assert not broken, (
            "Documents assert file paths that do not exist:\n  "
            + "\n  ".join(sorted(set(broken)))
            + "\n\nCLASS 1 means the path could not be found under any of: "
            + ", ".join(str(r.relative_to(REPO_ROOT.parent)) for r in SEARCH_ROOTS)
        )


class TestDocsResolveForTheirReader:
    """CLASS 2: a deployed doc's path resolves where its READER is."""

    def test_the_discriminator_still_splits_the_corpus(self):
        """Anti-vacuous for class 2. If nothing classifies as reader-relative
        the test below asserts nothing, which is the failure mode that matters:
        this check exists precisely because the reader is not here."""
        rows = _collect_rendered(DEPLOYED_DOCS, *DWB_VARIANT)
        reader = [r for r in rows if _is_reader_relative(r[3])]
        prov = [r for r in rows if not _is_reader_relative(r[3])]
        assert reader, "no reader-relative paths found in the deployed playbooks"
        assert prov, "no provenance paths found; the discriminator is not splitting"

    def test_consumer_readers_can_resolve_every_instruction(self):
        """A path a consumer agent is told to open must be something deploy
        actually puts on their box."""
        broken = []
        consumer = _consumer_view()
        for jira, human in VARIANTS:
            mode = f"jira={jira} human_memory={human}"
            for d, i, raw, rel, _line in _collect_rendered(DEPLOYED_DOCS, jira, human):
                if not _is_reader_relative(rel):
                    continue
                if _git_ignored(rel):
                    continue
                if rel not in consumer:
                    broken.append(
                        f"{_loc(d, raw, i)} ({mode}) asserts `{raw}`  "
                        f"[CLASS 2: deployed doc tells a consumer to open a "
                        f"path deploy does not ship]")
        assert not broken, (
            "Deployed playbooks instruct consumer readers to open paths that do "
            "not exist on a consumer repo:\n  " + "\n  ".join(sorted(set(broken)))
            + "\n\nThe consumer view is derived from playbook_deploy's own "
              "manifest, so either deploy should ship it or the doc should not "
              "name it."
        )

    def test_this_repos_readers_can_resolve_every_instruction(self):
        """The mirror, and the one DWB-368 shipped for months: a path correct on
        consumers and impossible here, because deploy skips itself. Satisfied
        either by existing here or by a same-line provenance alternative."""
        broken = []
        for d, i, raw, rel, line in _collect_rendered(DEPLOYED_DOCS, *DWB_VARIANT):
            if not _is_reader_relative(rel):
                continue
            if _git_ignored(rel) or _resolves_here(rel):
                continue
            if _has_provenance_alternative(line, rel):
                continue
            broken.append(
                f"{_loc(d, raw, i)}  asserts `{raw}`  [CLASS 2: path cannot "
                f"exist in this repo and the line offers no alternative "
                f"that does]")
        assert not broken, (
            "Deployed playbooks instruct a reader on THIS repo to open paths "
            "that cannot exist here:\n  " + "\n  ".join(sorted(set(broken)))
            + "\n\nDeploy does not copy the .claude/ bundle into DWB itself, so "
              "these resolve on the five consumer repos and nowhere here. Fix by "
              "naming the local equivalent on the same line, the pattern used "
              "elsewhere: `.claude/x.md` (in the DWB repo itself, `docs/x.md`)."
        )

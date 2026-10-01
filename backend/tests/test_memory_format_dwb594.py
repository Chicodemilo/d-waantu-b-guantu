# Path: tests/test_memory_format_dwb594.py
# File: test_memory_format_dwb594.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Guard the ONE format module both the adopt splitter and the revert
#          renderer import - determinism, the round trip that proves they
#          agree, and that no candidate is ever a timestamp or a section title.
# Caller: pytest
# Callees: app.services.memory_format
# Data In: the real memory.md files in this repo, copied into tmp_path
# Data Out: assertions
# Last Modified: 2026-09-30 (DWB-594)

"""DWB-594's format half, which is the part with no schema dependency.

Pam's rule is the thesis of the file: a splitter and a renderer that agree are
the only proof that either is right. Two private parsers would disagree, and the
disagreement surfaces only on a revert-after-adopt - the least exercised path in
the lane.

THE FIXTURES ARE THE REAL FILES. Every `memory.md` in `.dwb/memory/` is used as
a corpus, copied into tmp_path first so no test can write to live memory. A
hand-written fixture would carry only the shapes I already thought of, and the
finding that drove this module's design - that topic headings outnumber ISO
headings 70 to 40, so a file can have exactly one block - came from counting the
real corpus and would not have come from a fixture I invented.

The corpus is also allowed to be EMPTY on a clone that has never run an agent,
so every corpus test skips loudly rather than passing on nothing.
"""

import shutil
from pathlib import Path

import pytest

from app.services.memory_format import (
    ISO_HEADING,
    MemoryEntry,
    render,
    split,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIVE_MEMORY_DIR = REPO_ROOT / ".dwb" / "memory"


@pytest.fixture(scope="module")
def corpus_paths() -> list[Path]:
    return sorted(LIVE_MEMORY_DIR.glob("*/*/memory.md"))


@pytest.fixture
def corpus(corpus_paths, tmp_path) -> list[tuple[str, str]]:
    """(name, text) for every real memory.md, copied out of the live tree.

    Copied rather than read in place so that a test which ever gains a write
    cannot touch a live agent's memory. Reading would be enough today; the copy
    is the guard against the version of this file that grows a write later.
    """
    if not corpus_paths:
        pytest.skip(
            f"no memory.md files under {LIVE_MEMORY_DIR}; the corpus tests need "
            "at least one real file and must not pass against an empty set"
        )
    out = []
    for src in corpus_paths:
        dst = tmp_path / src.parent.name / "memory.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        out.append((src.parent.name, dst.read_text(encoding="utf-8")))
    return out


# ---------------------------------------------------------------------------
# The round trip. The reason the module exists.
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """WHAT THE ROUND TRIP DOES AND DOES NOT PROVE.

    It proves the splitter and the renderer AGREE. It does not prove either is
    correct: a change made to the splitter alone still round-trips, because both
    passes use the same splitter and the renderer faithfully echoes whatever it
    was handed. A mutation loosening TOP_BULLET to swallow nested bullets passed
    every test in this class.

    So the round trip is a consistency check, and the granularity tests below
    are the correctness checks. Both are needed, and neither substitutes for the
    other - which is the same reason this module exists at all.
    """

    def test_render_then_split_is_an_identity(self, corpus):
        """``split(render(entries)) == entries``.

        This is the assertion that catches the splitter and the renderer
        drifting apart. It is an identity in this direction and is asserted
        strictly.

        The other direction is NOT asserted anywhere in this file: a revert
        reorders by tier then score and drops at the ceiling, so
        ``render(split(text)) == text`` is false by design. Asserting it would
        force someone to weaken it later, and a weakened round-trip test is
        worse than no round-trip test.
        """
        for name, text in corpus:
            parsed = split(text)
            rendered = render(
                parsed.entries,
                provenance=parsed.provenance,
                preamble=parsed.preamble,
            )
            reparsed = split(rendered)
            assert reparsed.entries == parsed.entries, (
                f"{name}: re-splitting the rendered output produced different "
                f"entries ({len(parsed.entries)} -> {len(reparsed.entries)})"
            )

    def test_a_single_entry_with_its_heading_chain_round_trips_exactly(self):
        """THE PROPERTY `source_excerpt` DEPENDS ON, pinned on its own.

        DWB-594 stores each candidate as `render([entry])` in a single column
        rather than adding a `heading_path` column, so the chain rides inside
        the excerpt and `split()` has to recover it exactly. Barry named the
        real risk in that trade: if `render` and `split` ever stop being exact
        inverses, the excerpt degrades SILENTLY rather than failing.

        The corpus identity above would catch it, but only as one of eight files
        failing for an unexplained reason. This names the property at the
        granularity the adopt path actually uses: ONE entry, alone, with its
        chain.

        Scoped to entries `split` CAN PRODUCE - see the invariant test below for
        the one shape it cannot, and why that is not a gap.
        """
        for chain in [
            (),
            ("Verification discipline",),
            ("Outer", "Inner"),
            ("Outer", "Inner", "Deepest"),
        ]:
            bodies = [
                ("bullet", "a lesson that wraps\n  onto a second line"),
                ("bullet", "a lesson\n  - with a nested point"),
            ]
            if chain:
                # A chainless PARAGRAPH is not a shape split emits; see below.
                bodies.append(
                    ("paragraph", "prose under a heading.\nSecond line of it.")
                )
            for kind, body in bodies:
                entry = MemoryEntry(body=body, heading_path=chain, kind=kind)
                recovered = split(render([entry])).entries
                assert recovered == [entry], (
                    f"chain={chain} kind={kind}: {recovered!r} != [{entry!r}]"
                )

    def test_every_entry_split_produces_round_trips_through_render(self, corpus):
        """THE PROPERTY `source_excerpt` STORAGE ACTUALLY RESTS ON.

        `memory_adopt` stores `render([entry])` and `memory_decide._body_of`
        splits it back, so every entry split can produce must survive that round
        trip ALONE. This asserts it directly, per entry, over the live corpus.

        DWB-620 REPLACED A PROXY WITH THIS, AND THE PROXY'S REASON HAD BECOME
        FALSE. The test here used to assert that split never emits a CHAINLESS
        PARAGRAPH entry, on the stated grounds that "a paragraph with no heading
        chain does not round-trip: render emits bare prose, and split reads
        prose above the first heading as PREAMBLE, so it comes back as zero
        entries." That was true and it is no longer: `render` now emits a
        section break ahead of such a paragraph and `split` treats that break as
        structure, so the entry comes back as itself.

        The proxy also had to go rather than be relaxed, because fixing the
        splitter made chainless entries a NORMAL result - content appended under
        a write-stamp is written under no section, and saying so is the point of
        the fix. Asserting they cannot exist would have forced the splitter back
        into inventing a heading for them.

        This is strictly stronger than what it replaced: the old assertion
        covered one shape that was suspected of not round-tripping, this one
        covers every shape the corpus actually contains.
        """
        for name, text in corpus:
            for entry in split(text).entries:
                back = split(render([entry])).entries
                assert back == [entry], (
                    f"{name}: an entry did not survive render->split alone, so "
                    f"storing it as a source_excerpt would be lossy: "
                    f"{entry.body[:60]!r} (kind={entry.kind}, "
                    f"heading_path={entry.heading_path}) came back as {back}"
                )

    def test_split_files_pre_heading_prose_as_preamble_not_an_entry(self):
        """The mechanism behind the invariant, asserted directly so the reason
        survives even if the corpus one day contains no such file."""
        parsed = split("# Memory - Someone\n\nDurable lessons only.\n")
        assert parsed.entries == []
        assert any("Durable lessons only." in line for line in parsed.preamble)

    def test_the_round_trip_is_stable_under_repetition(self, corpus):
        """A second pass changes nothing.

        A renderer that adds or eats a blank line each pass would satisfy one
        round trip and drift on a re-adopt after a revert, which is exactly the
        sequence this lane makes possible.
        """
        for name, text in corpus:
            once = render(**_parts(split(text)))
            twice = render(**_parts(split(once)))
            assert once == twice, f"{name}: render is not idempotent"

    def test_no_entry_body_is_lost(self, corpus):
        for name, text in corpus:
            parsed = split(text)
            bodies = {e.body for e in parsed.entries}
            reparsed = split(render(**_parts(parsed)))
            assert {e.body for e in reparsed.entries} == bodies, name


def _parts(parsed):
    return {
        "entries": parsed.entries,
        "provenance": parsed.provenance,
        "preamble": parsed.preamble,
    }


# ---------------------------------------------------------------------------
# AC1 - determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_splitting_twice_produces_identical_candidates(self, corpus):
        """DWB-594 acceptance 1, over the real corpus."""
        for name, text in corpus:
            a = split(text)
            b = split(text)
            assert a.entries == b.entries, name
            assert a.provenance == b.provenance, name
            assert a.preamble == b.preamble, name

    def test_entry_order_is_source_order(self, corpus):
        for name, text in corpus:
            entries = split(text).entries
            lines = [e.line_number for e in entries if e.line_number]
            assert lines == sorted(lines), name


# ---------------------------------------------------------------------------
# Nobody is asked to tier a timestamp or a section title
# ---------------------------------------------------------------------------


class TestCandidatesAreLessonsOnly:
    def test_the_corpus_actually_exercises_this(self, corpus):
        """Proves the two absence claims below are not vacuous.

        Both are "no candidate looks like X". If the corpus contained no X at
        all they would pass against a broken splitter, which is the absence
        assertion that sees nothing - the failure family this project keeps
        hitting. So assert the corpus HAS ISO headings and section headings
        before asserting that none of them became candidates.
        """
        total_provenance = sum(len(split(t).provenance) for _n, t in corpus)
        total_headed = sum(
            1 for _n, t in corpus for e in split(t).entries if e.heading_path
        )
        assert total_provenance > 0, "corpus has no ISO write-headings to exclude"
        assert total_headed > 0, "corpus has no sectioned entries to exclude"

    def test_no_candidate_is_an_iso_write_heading(self, corpus):
        for name, text in corpus:
            for entry in split(text).entries:
                assert not ISO_HEADING.match(entry.body.splitlines()[0]), (
                    f"{name}: a timestamp became a candidate an agent would be "
                    f"asked to tier: {entry.body[:60]!r}"
                )

    def test_no_candidate_is_a_bare_section_heading(self, corpus):
        for name, text in corpus:
            for entry in split(text).entries:
                first = entry.body.splitlines()[0]
                assert not first.startswith("#"), (
                    f"{name}: a section title became a candidate: {first!r}"
                )

    def test_headings_survive_as_context_not_as_entries(self, corpus):
        """The chain has to reach the entry, or the decide phase shows a lesson
        with no idea what it was filed under."""
        for name, text in corpus:
            entries = split(text).entries
            assert any(e.heading_path for e in entries), (
                f"{name}: no entry carries its heading chain"
            )


# ---------------------------------------------------------------------------
# The granularity finding, pinned so it cannot regress quietly
# ---------------------------------------------------------------------------


class TestGranularity:
    def test_a_prose_only_file_still_yields_candidates(self):
        """One real file (202 lines) has no bullets at all: topic headings and
        prose. A bullet-only parser returns nothing for it, and returning
        nothing looks exactly like a file with no lessons."""
        text = (
            "## 2026-09-29T21:08:25+00:00 - condensed\n"
            "# Memory - Someone\n\n"
            "Durable lessons only.\n\n"
            "## THE FAILURE FAMILY\n"
            "A mechanism that reports it RAN rather than that it LANDED.\n"
            "Ask what the failure would look like from outside.\n\n"
            "## Migrations\n"
            "Autogenerate misses INT to BIGINT widenings; hand-write them.\n"
        )
        parsed = split(text)
        assert len(parsed.entries) == 2, [e.body for e in parsed.entries]
        assert parsed.entries[0].heading_path == ("THE FAILURE FAMILY",)
        assert parsed.entries[1].heading_path == ("Migrations",)
        assert all(e.kind == "paragraph" for e in parsed.entries)

    def test_a_block_of_ten_bullets_is_ten_candidates(self):
        """The decide phase is ONE entry and ONE question.

        Splitting at block granularity would force one answer to ten questions,
        and it breaks tier-down-on-uncertainty: asked about a block, an agent
        tiers to its weakest member and the good lessons sink with it.
        """
        text = "## Working rules\n" + "".join(
            f"- lesson number {i}\n" for i in range(10)
        )
        entries = split(text).entries
        assert len(entries) == 10
        assert all(e.heading_path == ("Working rules",) for e in entries)

    def test_wrapped_and_nested_lines_stay_with_their_bullet(self):
        """Real files wrap every bullet AND nest sub-points under them. Each
        parent bullet is one lesson, not three.

        An earlier version of this test was named for nesting and contained
        none - only wrapped continuation lines, which do not start with a dash.
        A mutation loosening TOP_BULLET to match indented dashes passed it, and
        passed the round trip too (see the class docstring below on why). The
        indented `  - ` line here is the case that mutation breaks.
        """
        text = (
            "## Topic\n"
            "- **Grep the phrasing variants.** A ticket's hit list is\n"
            "  only ever whatever someone else's grep found, so re-derive it\n"
            "  from HEAD before trusting the count.\n"
            "  - worked example: zero-token, 0-token and zero_token are three\n"
            "    separate greps.\n"
            "- A second, unrelated lesson.\n"
        )
        entries = split(text).entries
        assert len(entries) == 2, [e.body for e in entries]
        assert "re-derive it" in entries[0].body
        # The nested bullet belongs to the lesson above it, not to itself. A
        # sub-point promoted to a candidate is handed to an agent stripped of
        # the point it qualifies, which is unanswerable.
        assert "worked example" in entries[0].body
        assert entries[1].body == "A second, unrelated lesson."

    def test_a_nested_bullet_is_never_its_own_candidate(self):
        """Pinned separately from the wrapping case, because they fail
        independently: wrapping is about lines that continue, nesting is about
        lines that look like new entries and are not."""
        text = "## Topic\n- parent lesson\n  - child point\n    - grandchild\n"
        entries = split(text).entries
        assert len(entries) == 1, [e.body for e in entries]
        assert "child point" in entries[0].body
        assert "grandchild" in entries[0].body

    @pytest.mark.parametrize("separator", ["-", "–", "—"])
    def test_both_live_session_heading_separators_are_provenance(self, separator):
        """session-complete writes an EM DASH, condense writes a HYPHEN. Both
        are in live files. A parser knowing only one treats the other as a topic
        heading, which turns provenance into something an agent is asked to
        tier."""
        text = (
            f"## 2026-09-29T20:56:31+00:00 {separator} session aStan-4c86\n"
            "- an actual lesson\n"
        )
        parsed = split(text)
        assert len(parsed.provenance) == 1, parsed.provenance
        assert len(parsed.entries) == 1
        assert parsed.entries[0].body == "an actual lesson"

    def test_stacked_provenance_markers_yield_no_candidates(self):
        """A condense of a condense leaves two ISO headings with empty bodies.
        Neither is a lesson."""
        text = (
            "## 2026-09-29T21:08:25+00:00 - condensed\n"
            "## 2026-09-29T20:50:55+00:00 - condensed\n"
            "# Memory - Someone\n"
        )
        parsed = split(text)
        assert parsed.entries == []
        assert len(parsed.provenance) == 2


class TestEdges:
    def test_empty_file_is_not_an_error(self):
        parsed = split("")
        assert parsed.entries == []
        assert render([]) == "\n"

    def test_a_fenced_block_is_carried_verbatim(self):
        text = (
            "## Topic\n"
            "- run it like this:\n"
            "```bash\n"
            "curl -X POST /api/agents/1/memories\n"
            "```\n"
        )
        entries = split(text).entries
        assert len(entries) == 1
        assert "curl -X POST" in entries[0].body
        assert entries[0].body.count("```") == 2

    def test_deeper_heading_never_renders_without_its_parent(self):
        entries = [
            MemoryEntry(body="one", heading_path=("Outer", "Inner")),
            MemoryEntry(body="two", heading_path=("Outer", "Other")),
        ]
        out = render(entries)
        assert out.index("## Outer") < out.index("### Inner")
        # Re-entering a sibling must not re-emit the parent it already sits in.
        assert out.count("## Outer") == 1
        assert split(out).entries == entries

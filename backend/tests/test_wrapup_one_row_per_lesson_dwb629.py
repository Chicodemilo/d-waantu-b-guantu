# Path: tests/test_wrapup_one_row_per_lesson_dwb629.py
# File: test_wrapup_one_row_per_lesson_dwb629.py
# Created: 2026-10-01 (DWB-629)
# Purpose: A wrap-up carrying several lessons must split into one row per
#          lesson, not one row for the whole wrap-up. Asserted as a ROW COUNT
#          through the real endpoint and the real splitter.
# Caller: pytest
# Callees: POST /api/agents/{id}/session-complete, app.services.memory_format.split
# Data In: tmp_path repo, factory project + agent
# Data Out: assertions on entry counts and bodies after a wrap-up
# Last Modified: 2026-10-01 (DWB-629)

"""One row is one claim, and the wrap-up was writing three claims into one.

`session-complete` wrote a single `- lessons:` bullet with each lesson INDENTED
beneath it. `memory_format.TOP_BULLET` is anchored at column zero on purpose -
an indented dash is a NESTED bullet and belongs to the entry above it - so the
entire wrap-up split into ONE entry. Several unrelated lessons then adopted as a
single row: one tier for all of them, one decay clock, retrieved or not
retrieved as a block. Three lessons that would each have earned their own
strength were averaged into one. Every agent's wrap-up from the adoption run has
that shape.

THE ASSERTION IS A COUNT, BECAUSE A CONTENT TEST PASSES EITHER WAY. "the lesson
text appears in memory.md" is true of the broken version too - all three
lessons were in the file, in one entry. Only the number of entries tells the two
implementations apart, which is why the ticket asks for a row count.

These tests run on a STOCK project. Under human_memory `session-complete` is
sealed (409) and writes nothing, so the file-shape defect is only observable in
the mode that still writes the file - and it is the shape that mattered, because
adoption is what turned these blocks into rows.
"""

import pytest

from app.services.memory_format import split


@pytest.fixture
def agent_on_stock(client, make_project, make_agent, tmp_path):
    project = make_project(prefix="WRP", repo_path=str(tmp_path))
    agent = make_agent(
        project_id=project["id"], name="Wrapper", role="backend-worker"
    )
    return project, agent, tmp_path / ".dwb" / "memory" / "WRP" / "Wrapper" / "memory.md"


def _wrap_up(client, agent_id, lessons, summary="a session happened"):
    body = {"summary": summary}
    if lessons is not None:
        body["lessons"] = lessons
    r = client.post(f"/api/agents/{agent_id}/session-complete", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _entries(path):
    return split(path.read_text(encoding="utf-8")).entries


class TestOneRowPerLesson:
    def test_three_lessons_produce_three_rows(self, client, agent_on_stock):
        """Acceptance 1 and 3. This is the assertion that fails against the
        old formatter, which produced exactly one entry for any number of
        lessons."""
        _project, agent, path = agent_on_stock
        lessons = [
            "the first durable lesson, which stands on its own",
            "the second, entirely unrelated to the first",
            "the third, which would decay on its own clock",
        ]
        _wrap_up(client, agent["id"], lessons)

        entries = _entries(path)
        assert len(entries) == 3, (
            f"expected one row per lesson, got {len(entries)}: "
            f"{[e.body[:40] for e in entries]}"
        )
        assert [e.body for e in entries] == lessons

    def test_each_row_is_a_top_level_bullet_not_a_nested_one(
        self, client, agent_on_stock
    ):
        """The mechanism, pinned separately from the count.

        The count could be made right by some other means; this says WHY it is
        right, so a future change that re-indents the lessons fails here with a
        reason rather than only as a number.
        """
        _project, agent, path = agent_on_stock
        _wrap_up(client, agent["id"], ["alpha", "beta"])

        raw = path.read_text(encoding="utf-8")
        assert "- lessons:" not in raw, (
            "the label is what made every real lesson a nested bullet"
        )
        for line in ("- alpha", "- beta"):
            assert f"\n{line}\n" in raw, f"{line!r} is not a column-zero bullet"

    def test_a_multi_line_lesson_is_still_one_row(self, client, agent_on_stock):
        """Folding is the behaviour we want to KEEP. A wrapped lesson is one
        claim across several lines, and splitting it per line would be the
        opposite defect."""
        _project, agent, path = agent_on_stock
        lesson = (
            "a lesson with a wrapped body\n"
            "continuing on a second line\n"
            "and a third"
        )
        _wrap_up(client, agent["id"], [lesson, "a separate one"])

        entries = _entries(path)
        assert len(entries) == 2
        assert entries[0].body == lesson


class TestTheOtherInputShapesStillWork:
    """Acceptance 2. Both shapes are supported per DWB-582 and both must keep
    working; a fix that only handled lists would 500 a worker sending one."""

    def test_a_single_lesson_in_a_list_produces_exactly_one_row(
        self, client, agent_on_stock
    ):
        _project, agent, path = agent_on_stock
        _wrap_up(client, agent["id"], ["just the one"])
        entries = _entries(path)
        assert len(entries) == 1
        assert entries[0].body == "just the one"

    def test_a_bare_string_produces_exactly_one_row(self, client, agent_on_stock):
        _project, agent, path = agent_on_stock
        _wrap_up(client, agent["id"], "sent as a bare string, not a list")
        entries = _entries(path)
        assert len(entries) == 1
        assert entries[0].body == "sent as a bare string, not a list"

    def test_no_lessons_writes_the_heading_and_no_rows(self, client, agent_on_stock):
        """DWB-560 plus DWB-564: the ISO heading is always stamped even with no
        lessons, because the write-on-close gate reads the file's mtime and an
        untouched file leaves an agent who did everything right looking silent.
        It must still produce no ENTRIES - a heading is not a lesson.
        """
        _project, agent, path = agent_on_stock
        _wrap_up(client, agent["id"], None)

        raw = path.read_text(encoding="utf-8")
        parsed = split(raw)
        assert parsed.entries == []
        assert parsed.provenance, "the ISO heading must still be written"


class TestAdoptionSeesOneCandidatePerLesson:
    """The consequence the ticket is actually about: what adoption would make
    of a wrap-up. The splitter is the adopt path's entry point, so the entry
    count here IS the row count there."""

    def test_a_wrapup_offers_each_lesson_for_tiering_separately(
        self, client, agent_on_stock
    ):
        _project, agent, path = agent_on_stock
        _wrap_up(client, agent["id"], ["one claim", "a different claim"])

        entries = _entries(path)
        assert len(entries) == 2
        # Each is independently tierable: distinct bodies, no shared chain that
        # would bind them together.
        assert len({e.body for e in entries}) == 2
        for entry in entries:
            assert entry.kind == "bullet"

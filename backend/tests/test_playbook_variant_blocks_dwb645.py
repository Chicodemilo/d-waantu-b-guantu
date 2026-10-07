# Path: tests/test_playbook_variant_blocks_dwb645.py
# File: test_playbook_variant_blocks_dwb645.py
# Created: 2026-10-07 (DWB-645)
# Purpose: Guard the memory-mode variant scrub - that mode blocks are stripped
#          by mode, that the jira keys are unchanged, that the two keys COMPOSE
#          when nested, that the scrub is order-independent, that interleaved
#          markers are refused rather than silently leaking, and that the real
#          source playbooks are clean.
# Caller: pytest
# Callees: app.services.playbook_deploy
# Data In: constructed sources, the real docs/*_playbook.md, deployed files
# Data Out: Assertions on scrubbed text and on files written to disk
# Last Modified: 2026-10-07 (DWB-645)

"""DWB-645 acceptance.

CRITERION 2 IS THE ONE THAT GETS WAVED THROUGH, and the TL said so when filing:
each key passes its own test in isolation, so a build where the keys do not
compose still shows two green test classes. `TestTheKeysCompose` therefore holds
BOTH keys at once over all eight (jira, mode, nesting-order) combinations, and
`TestOrderIndependence` asserts the property directly rather than trusting that
the two subs happen to commute.

NESTED COMPOSES; INTERLEAVED DOES NOT. That distinction is load-bearing and is
named in the test names on purpose. "The keys compose" read loosely means "any
arrangement works", which is false: markers that overlap without nesting leak,
in OPPOSITE directions depending on call order, and no regex can fix it because
the input is ambiguous. The supported shape is nested or disjoint; interleaved
is refused by `find_unbalanced_markers`, asserted here over the real sources.

Found by Dolores while modelling the stripper BEFORE it was built, and
reproduced here independently against the shipped implementation rather than
against her model.
"""

import pathlib
import shutil

import pytest

from app.services import playbook_deploy as svc

DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"

JIRA_TEXT = "USE_DWB2JIRA"
NONJIRA_TEXT = "PATCH_THE_API"
HM_TEXT = "YOUR_MEMORY_DECAYS"
STOCK_TEXT = "APPEND_TO_MEMORY_MD"


def _src() -> str:
    """Four disjoint blocks, one per key."""
    return (
        f"HEAD\n"
        f"<!-- jira-only:start -->\n{JIRA_TEXT}\n<!-- jira-only:end -->\n"
        f"<!-- non-jira-only:start -->\n{NONJIRA_TEXT}\n<!-- non-jira-only:end -->\n"
        f"<!-- human-memory-only:start -->\n{HM_TEXT}\n<!-- human-memory-only:end -->\n"
        f"<!-- stock-memory-only:start -->\n{STOCK_TEXT}\n<!-- stock-memory-only:end -->\n"
        f"TAIL\n"
    )


class TestModeBlocksAreStrippedByMode:
    """Criterion 1."""

    @pytest.mark.parametrize("human_memory", [True, False])
    def test_only_the_matching_mode_block_survives(self, human_memory):
        out = svc._scrub_variant_blocks(
            _src(), jira_enabled=False, human_memory=human_memory
        )
        assert (HM_TEXT in out) is human_memory
        assert (STOCK_TEXT in out) is (not human_memory)
        # The unrelated text is untouched either way - a scrub that ate the
        # whole file would satisfy both assertions above on one of the arms.
        assert "HEAD" in out and "TAIL" in out

    def test_the_two_modes_differ(self):
        """Both arms in one test. "Only the matching block survives" passes
        against a build that strips every mode block regardless of mode,
        because each arm only ever sees one side."""
        hm = svc._scrub_variant_blocks(_src(), jira_enabled=False, human_memory=True)
        stock = svc._scrub_variant_blocks(_src(), jira_enabled=False, human_memory=False)
        assert hm != stock
        assert HM_TEXT in hm and HM_TEXT not in stock
        assert STOCK_TEXT in stock and STOCK_TEXT not in hm


class TestJiraBehaviourIsUnchanged:
    """Criterion 7. The existing jira tests are untouched; this pins the pair
    at the new call signature so a mode bug cannot be mistaken for a jira one."""

    @pytest.mark.parametrize("jira_enabled", [True, False])
    @pytest.mark.parametrize("human_memory", [True, False])
    def test_jira_side_is_decided_only_by_jira(self, jira_enabled, human_memory):
        out = svc._scrub_variant_blocks(
            _src(), jira_enabled=jira_enabled, human_memory=human_memory
        )
        assert (JIRA_TEXT in out) is jira_enabled
        assert (NONJIRA_TEXT in out) is (not jira_enabled)


class TestTheKeysCompose:
    """CRITERION 2. A block inside BOTH conditions, over every combination.

    Nested only - that is the supported shape. See TestInterleavedIsRefused for
    the arrangement that is not, and why it cannot be made to work here.
    """

    @staticmethod
    def _nested(outer: str, inner: str) -> str:
        return (
            f"<!-- {outer}:start -->\nOUTER_HEAD\n"
            f"<!-- {inner}:start -->\nINNER\n<!-- {inner}:end -->\n"
            f"OUTER_TAIL\n<!-- {outer}:end -->\nAFTER\n"
        )

    @pytest.mark.parametrize("jira_enabled", [True, False])
    @pytest.mark.parametrize("human_memory", [True, False])
    @pytest.mark.parametrize("mode_inside_jira", [True, False])
    def test_a_block_in_both_conditions_resolves(
        self, jira_enabled, human_memory, mode_inside_jira
    ):
        """INNER survives only when BOTH conditions are met, whichever way the
        two blocks are nested. Eight combinations, and the AND is the point: a
        build that applies only one key passes every single-key test and fails
        exactly here."""
        if mode_inside_jira:
            text = self._nested("jira-only", "human-memory-only")
        else:
            text = self._nested("human-memory-only", "jira-only")

        out = svc._scrub_variant_blocks(
            text, jira_enabled=jira_enabled, human_memory=human_memory
        )
        expected = jira_enabled and human_memory
        assert ("INNER" in out) is expected, (
            f"jira={jira_enabled} human_memory={human_memory} "
            f"mode_inside_jira={mode_inside_jira}: INNER should "
            f"{'survive' if expected else 'be stripped'}"
        )
        # AFTER is outside every block and must always survive; without it an
        # implementation that returned "" would pass all the negative arms.
        assert "AFTER" in out

    def test_the_inner_block_is_dropped_when_only_the_outer_matches(self):
        """The asymmetric case stated directly, because it is the one a reader
        has to reason about: outer kept, inner dropped."""
        text = self._nested("jira-only", "human-memory-only")
        out = svc._scrub_variant_blocks(text, jira_enabled=True, human_memory=False)
        assert "OUTER_HEAD" in out and "OUTER_TAIL" in out
        assert "INNER" not in out


class TestOrderIndependence:
    """The property, asserted rather than assumed.

    `_scrub_variant_blocks` applies its subs in a fixed order today. That order
    is an implementation detail and must not be load-bearing; if it ever
    becomes so, the source is interleaved and the balance checker should
    already have said so.
    """

    @pytest.mark.parametrize("jira_enabled", [True, False])
    @pytest.mark.parametrize("human_memory", [True, False])
    def test_jira_then_mode_equals_mode_then_jira(self, jira_enabled, human_memory):
        text = TestTheKeysCompose._nested("jira-only", "human-memory-only")
        jira_re = (
            svc._NON_JIRA_ONLY_BLOCK_RE if jira_enabled else svc._JIRA_ONLY_BLOCK_RE
        )
        mode_re = (
            svc._STOCK_MEMORY_ONLY_BLOCK_RE
            if human_memory
            else svc._HUMAN_MEMORY_ONLY_BLOCK_RE
        )
        assert jira_re.sub("", mode_re.sub("", text)) == mode_re.sub(
            "", jira_re.sub("", text)
        )


class TestInterleavedIsRefused:
    """The hazard, and the guard that catches it.

    Dolores found this by modelling the stripper before it existed. Reproduced
    here against the SHIPPED implementation: the leak is real, it is
    order-dependent, and the two orders leak in opposite directions - so
    neither call order is a fix.
    """

    INTERLEAVED = (
        "<!-- jira-only:start -->\nJIRA_HEAD\n"
        "<!-- human-memory-only:start -->\nBOTH\n"
        "<!-- jira-only:end -->\nHM_TAIL\n"
        "<!-- human-memory-only:end -->\nAFTER\n"
    )

    def test_the_checker_names_the_interleave_and_its_line(self):
        problems = svc.find_unbalanced_markers(self.INTERLEAVED)
        assert problems, "the checker passed an interleaved source"
        assert any("INTERLEAVED" in p for p in problems)
        assert any("line 5" in p for p in problems), problems

    def test_the_leak_is_real_and_order_dependent(self):
        """Why the checker is not belt-and-braces. Without it this ships."""
        jira_first = svc._HUMAN_MEMORY_ONLY_BLOCK_RE.sub(
            "", svc._JIRA_ONLY_BLOCK_RE.sub("", self.INTERLEAVED)
        )
        mode_first = svc._JIRA_ONLY_BLOCK_RE.sub(
            "", svc._HUMAN_MEMORY_ONLY_BLOCK_RE.sub("", self.INTERLEAVED)
        )
        assert jira_first != mode_first
        # Opposite directions: each order leaves behind what the other removed.
        assert "HM_TAIL" in jira_first and "JIRA_HEAD" not in jira_first
        assert "JIRA_HEAD" in mode_first and "HM_TAIL" not in mode_first

    def test_nested_markers_pass_the_checker(self):
        """The checker must not refuse the shape the feature depends on. A
        checker that rejected nesting too would be 'correct' on this file and
        would make the feature unusable."""
        assert svc.find_unbalanced_markers(
            TestTheKeysCompose._nested("jira-only", "human-memory-only")
        ) == []

    @pytest.mark.parametrize(
        "text,why",
        [
            ("<!-- jira-only:start -->\nx\n", "never closed"),
            ("<!-- jira-only:end -->\n", "closes nothing"),
            ("<!-- jira_only:start -->\nx\n<!-- jira_only:end -->\n", "typo'd key"),
        ],
    )
    def test_other_broken_shapes_are_caught(self, text, why):
        assert svc.find_unbalanced_markers(text), why

    def test_an_ordinary_html_comment_is_not_reported(self):
        """Or the check cries wolf and gets deleted."""
        assert svc.find_unbalanced_markers("<!-- just a note -->\ntext\n") == []


class TestTheRealSourcesAreClean:
    """The checker pointed at the files that actually deploy."""

    def test_every_source_playbook_has_balanced_markers(self):
        offenders = {}
        total_markers = 0
        files = sorted(DOCS.glob("*_playbook.md"))
        # POSITIVE CONTROL. A glob that silently matched nothing would make the
        # assertion below pass perfectly over an empty set.
        assert files, f"no playbooks found under {DOCS}; this check is vacuous"
        for f in files:
            text = f.read_text(encoding="utf-8")
            total_markers += len(svc._MARKER_TOKEN_RE.findall(text))
            problems = svc.find_unbalanced_markers(text)
            if problems:
                offenders[f.name] = problems
        assert total_markers > 0, (
            "no variant markers found in any playbook; the checker is reading "
            "the wrong files or the marker pattern has drifted"
        )
        assert offenders == {}, offenders


class TestTheDeployedFileOnDisk:
    """CRITERIA 3 AND 6, at the level that matters: the file an agent opens.

    Everything above tests the scrub function. This drives the real
    `deploy_bundle` through the real endpoint and reads the bytes that land in
    `.claude/`, because a scrub that is correct and never called is exactly the
    shape this project keeps shipping. A unit test on `_scrub_variant_blocks`
    cannot tell those apart.

    DOCS_DIR is redirected at a tmp playbook carrying all four marker kinds,
    rather than editing the real playbooks: the mode blocks are Dolores's to
    write, and a test that depended on her content would go red on every edit
    she makes. When her content lands, the live two-project read is the final
    acceptance and she runs it independently.
    """

    SOURCE = (
        "# Worker Playbook\n\nALWAYS_PRESENT\n\n"
        "<!-- jira-only:start -->\nUSE_DWB2JIRA\n<!-- jira-only:end -->\n"
        "<!-- non-jira-only:start -->\nPATCH_THE_API\n<!-- non-jira-only:end -->\n"
        "<!-- human-memory-only:start -->\nYOUR_MEMORY_DECAYS\n"
        "<!-- human-memory-only:end -->\n"
        "<!-- stock-memory-only:start -->\nAPPEND_TO_MEMORY_MD\n"
        "<!-- stock-memory-only:end -->\n"
    )

    @pytest.fixture
    def fake_docs(self, tmp_path, monkeypatch):
        """A COPY of the real docs tree with only the playbooks overridden.

        Not an empty directory: `deploy_bundle` reads other things out of
        DOCS_DIR (docs/rules/global/coding-standards.md among them) and dies
        without them. Copying keeps the deploy on its real path and changes
        exactly the one input under test, which is the difference between
        exercising the deploy and exercising a stub of it.
        """
        docs = tmp_path / "docs"
        shutil.copytree(DOCS, docs)
        for filename in svc.PLAYBOOK_FILES.values():
            (docs / filename).write_text(self.SOURCE, encoding="utf-8")
        monkeypatch.setattr(svc, "DOCS_DIR", docs)
        return docs

    def _deploy(self, client, make_project, tmp_path, name, memory_mode):
        repo = tmp_path / name
        repo.mkdir()
        project = make_project(repo_path=str(repo), memory_mode=memory_mode)
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200, r.text
        deployed = repo / ".claude" / "worker_playbook.md"
        assert deployed.is_file(), f"nothing deployed to {deployed}"
        return deployed.read_text(encoding="utf-8")

    def test_a_human_memory_project_gets_no_stock_block(
        self, client, make_project, tmp_path, fake_docs
    ):
        text = self._deploy(client, make_project, tmp_path, "hm", "human_memory")
        assert "YOUR_MEMORY_DECAYS" in text
        assert "APPEND_TO_MEMORY_MD" not in text
        assert "ALWAYS_PRESENT" in text

    def test_a_stock_project_gets_no_human_memory_block(
        self, client, make_project, tmp_path, fake_docs
    ):
        text = self._deploy(client, make_project, tmp_path, "stock", "stock")
        assert "APPEND_TO_MEMORY_MD" in text
        assert "YOUR_MEMORY_DECAYS" not in text
        assert "ALWAYS_PRESENT" in text

    def test_the_two_deployed_files_differ(
        self, client, make_project, tmp_path, fake_docs
    ):
        """Both modes in one test. Each test above sees one mode only, so both
        pass against a deploy that strips every mode block regardless - which
        would leave every agent with neither half rather than the wrong half,
        and would look like success in a grep for the absent string."""
        hm = self._deploy(client, make_project, tmp_path, "hm2", "human_memory")
        stock = self._deploy(client, make_project, tmp_path, "stock2", "stock")
        assert hm != stock
        assert ("YOUR_MEMORY_DECAYS" in hm) and ("YOUR_MEMORY_DECAYS" not in stock)
        assert ("APPEND_TO_MEMORY_MD" in stock) and ("APPEND_TO_MEMORY_MD" not in hm)

    def test_the_jira_key_still_decides_the_jira_blocks_on_disk(
        self, client, make_project, tmp_path, fake_docs
    ):
        """Criterion 7 at the file level: adding the mode key must not have
        moved the jira behaviour. These factory projects are non-Jira."""
        text = self._deploy(client, make_project, tmp_path, "jira", "human_memory")
        assert "PATCH_THE_API" in text
        assert "USE_DWB2JIRA" not in text


class TestUnmarkedContentIsShared:
    """THE DEFAULT, ASSERTED BY NAME (Miles, 2026-10-07).

    Unmarked content ships to every project. It is a decision, not an absence
    of one, and it needs a test carrying its name for the same reason it needs
    a comment: a default nobody wrote down is a default the next author
    re-opens. Every existing line in all three playbooks is unmarked, so any
    other answer empties the playbooks on the first deploy - this test is what
    would go red if someone implemented a "keep only marked blocks" pass.
    """

    SHARED = "THIS_LINE_IS_IN_NO_BLOCK"

    @pytest.mark.parametrize("jira_enabled", [True, False])
    @pytest.mark.parametrize("human_memory", [True, False])
    def test_unmarked_text_survives_every_combination(self, jira_enabled, human_memory):
        text = f"{self.SHARED}\n" + _src()
        out = svc._scrub_variant_blocks(
            text, jira_enabled=jira_enabled, human_memory=human_memory
        )
        assert self.SHARED in out

    def test_a_playbook_with_no_markers_at_all_is_returned_unchanged(self):
        """The strongest form, and the one that catches a keep-pass: a file
        with no markers must come back byte-identical, not empty."""
        text = "# Worker Playbook\n\nEvery line here is unmarked.\n\nAnd this one.\n"
        for jira_enabled in (True, False):
            for human_memory in (True, False):
                assert (
                    svc._scrub_variant_blocks(
                        text, jira_enabled=jira_enabled, human_memory=human_memory
                    )
                    == text
                )

    def test_the_real_playbooks_keep_their_unmarked_bulk(self):
        """Pointed at the files that actually deploy. A scrub that dropped
        unmarked content would take most of each playbook with it, and the
        synthetic cases above would not notice because they are three lines
        long."""
        files = sorted(DOCS.glob("*_playbook.md"))
        assert files, f"no playbooks under {DOCS}; this check is vacuous"
        for f in files:
            text = f.read_text(encoding="utf-8")
            out = svc._scrub_variant_blocks(
                text, jira_enabled=False, human_memory=True
            )
            assert len(out) > len(text) * 0.5, (
                f"{f.name}: scrub removed more than half the file; unmarked "
                "content is shared and must survive"
            )

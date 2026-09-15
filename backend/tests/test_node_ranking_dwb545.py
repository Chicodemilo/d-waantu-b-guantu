# Path: tests/test_node_ranking_dwb545.py
# File: test_node_ranking_dwb545.py
# Created: 2026-09-15
# Purpose: DWB-545 - retrieval ranks by SPECIFICITY, not popularity. Covers the
#          score function (IDF, query term frequency, multi-part boost), the
#          document-frequency helpers, the top-5% popularity cutoff and its
#          only-matches fallback, the per-group caps, and the one-pointer-per-file
#          collapse on related_nodes; plus relevant_lessons ordering and the
#          non-empty spawn case.
# Caller: pytest
# Callees: app/services/node_retrieval, app/services/node_registry
# Data In: pytest fixtures (client, db_session, make_project, make_agent, make_ticket, tmp_path)
# Data Out: assertions
# Last Modified: 2026-09-15

import math

import pytest

from app.models.agent import Agent
from app.models.project import Project
from app.services import node_retrieval as nrv
from app.services.node_match import match_nodes
from app.services.node_registry import (
    SourceUnit,
    node_token_counts,
    node_tokens,
    register_sources,
)


def _ticket(make_ticket, prefix, n, **overrides):
    """make_ticket with an agreeing ticket_number/ticket_key pair."""
    return make_ticket(ticket_number=n, ticket_key=f"{prefix}-{n}", **overrides)


def _mem_ref(prefix, agent):
    return f".dwb/memory/{prefix}/{agent}/memory.md"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestTokenCounts:
    """DWB-545: the tag pipeline has ONE definition; counts feed the TF term."""

    def test_counts_repeats_and_set_wrapper_agrees(self):
        counts = node_token_counts("widget widget gadget")
        assert counts["widget"] == 2 and counts["gadget"] == 1
        assert node_tokens("widget widget gadget") == set(counts)

    def test_counts_apply_the_same_filters_as_tokens(self):
        # Stopwords/noise are dropped from BOTH surfaces.
        text = "the value of updating widgets"
        assert "value" not in node_token_counts(text)
        assert node_tokens(text) == set(node_token_counts(text))

    def test_counts_merge_after_stemming(self):
        assert node_token_counts("widgets widget")["widget"] == 2


class TestSpecificityScore:
    def test_rarer_tag_scores_higher(self):
        rare = nrv.specificity_score("alpha", df=2, total_docs=100)
        common = nrv.specificity_score("alpha", df=50, total_docs=100)
        assert rare > common > 0

    def test_ubiquitous_tag_scores_zero(self):
        assert nrv.specificity_score("alpha", df=100, total_docs=100) == 0.0

    def test_no_pointers_scores_zero(self):
        assert nrv.specificity_score("alpha", df=0, total_docs=100) == 0.0

    def test_multi_part_tag_beats_equally_rare_word(self):
        word = nrv.specificity_score("alpha", df=3, total_docs=100)
        phrase = nrv.specificity_score("alpha-beta", df=3, total_docs=100)
        assert phrase == pytest.approx(word * nrv.MULTI_PART_BOOST)
        assert phrase > word

    def test_query_term_frequency_raises_score_with_damping(self):
        once = nrv.specificity_score("alpha", df=5, total_docs=100, tf=1)
        thrice = nrv.specificity_score("alpha", df=5, total_docs=100, tf=3)
        ten = nrv.specificity_score("alpha", df=5, total_docs=100, tf=10)
        assert thrice > once
        assert ten > thrice
        # Damped: 10 mentions is worth far less than 10x one mention.
        assert ten < once * 10
        assert thrice == pytest.approx(once * (1 + math.log(3)))

    def test_tf_cannot_rescue_a_ubiquitous_tag(self):
        assert nrv.specificity_score("alpha", df=100, total_docs=100, tf=50) == 0.0

    def test_df_larger_than_corpus_is_clamped_not_negative(self):
        assert nrv.specificity_score("alpha", df=10, total_docs=3) == 0.0


class TestDocumentFrequencyHelpers:
    def test_pointer_df_counts_distinct_documents_not_pointers(self, db_session, make_project):
        p = make_project()
        # Five per-line pointers in ONE file plus one memory doc = df 2, not 6.
        units = [
            SourceUnit(kind="code", ref="a.py", text="widget", sha="s", line_start=i, line_end=i)
            for i in range(1, 6)
        ]
        units.append(SourceUnit(kind="memory", ref="m", text="widget"))
        register_sources(db_session, p["id"], units)
        db_session.flush()
        _q, matches = match_nodes(db_session, p["id"], "widget")
        node = matches[0][0]
        assert len(node.pointers) == 6
        assert nrv.pointer_df(node) == 2

    def test_corpus_doc_count_is_distinct_kind_ref(self, db_session, make_project):
        p = make_project()
        assert nrv._corpus_doc_count(db_session, p["id"]) == 0
        register_sources(db_session, p["id"], [
            SourceUnit(kind="code", ref="a.py", text="widget", line_start=1, line_end=1),
            SourceUnit(kind="code", ref="a.py", text="widget", line_start=2, line_end=2),
            SourceUnit(kind="memory", ref="m", text="widget"),
        ])
        db_session.flush()
        assert nrv._corpus_doc_count(db_session, p["id"]) == 2

    def test_corpus_count_is_project_isolated(self, db_session, make_project):
        p1, p2 = make_project(), make_project()
        register_sources(db_session, p2["id"], [
            SourceUnit(kind="code", ref="a.py", text="widget"),
            SourceUnit(kind="memory", ref="m", text="widget"),
        ])
        db_session.flush()
        assert nrv._corpus_doc_count(db_session, p1["id"]) == 0


def _seed_wide_corpus(db, pid, topics=25):
    """A corpus wide enough for a percentile to mean something.

    ``topics`` tags each ground in exactly TWO documents (one code + one doc, the
    2-domain minimum), and 'common' grounds in every document. That yields
    topics+1 nodes - above _POPULARITY_MIN_NODES - with 'common' alone in the top
    5% of document frequency. 'unicorn' rides the first pair as the rare tag.
    """
    units = []
    for i in range(topics):
        words = ["common", f"topic{i}x"]
        if i == 0:
            words.append("unicorn")
        text = " ".join(words)
        units.append(SourceUnit(kind="code", ref=f"c{i}.py", text=text, line_start=1, line_end=1))
        units.append(SourceUnit(kind="doc", ref=f"d{i}.md", text=text, line_start=1, line_end=1))
    register_sources(db, pid, units)
    db.flush()


class TestPopularityCutoff:
    def test_none_below_min_nodes(self, db_session, make_project):
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="code", ref="a.py", text="widget gadget"),
            SourceUnit(kind="memory", ref="m", text="widget gadget"),
        ])
        db_session.flush()
        assert nrv._popularity_cutoff(db_session, p["id"]) is None

    def test_cutoff_is_the_percentile_value(self, db_session, make_project):
        p = make_project()
        _seed_wide_corpus(db_session, p["id"])
        cutoff = nrv._popularity_cutoff(db_session, p["id"])
        assert cutoff is not None
        # The ubiquitous tag sits above it; a two-document tag sits at or below.
        _q, matches = match_nodes(db_session, p["id"], "common unicorn")
        by_tag = {n.tag: nrv.pointer_df(n) for n, _ in matches}
        assert by_tag["common"] > cutoff
        assert by_tag["unicorn"] <= cutoff

    def test_rank_matches_drops_the_popular_tag(self, db_session, make_project):
        p = make_project()
        _seed_wide_corpus(db_session, p["id"])
        _q, matches = match_nodes(db_session, p["id"], "common unicorn")
        ranked = nrv.rank_matches(db_session, p["id"], matches, "common unicorn")
        tags = [n.tag for n, _s in ranked]
        assert "unicorn" in tags
        assert "common" not in tags

    def test_only_matches_survive_the_cutoff(self, db_session, make_project):
        """A query whose ONLY match is a popular tag still gets it - a thin
        answer beats no answer."""
        p = make_project()
        _seed_wide_corpus(db_session, p["id"])
        _q, matches = match_nodes(db_session, p["id"], "common")
        ranked = nrv.rank_matches(db_session, p["id"], matches, "common")
        assert [n.tag for n, _s in ranked] == ["common"]

    def test_ranking_is_specificity_then_tag_ascending(self, db_session, make_project):
        p = make_project()
        _seed_wide_corpus(db_session, p["id"])
        query = "topic0x topic1x topic2x"
        _q, matches = match_nodes(db_session, p["id"], query)
        ranked = nrv.rank_matches(db_session, p["id"], matches, query)
        scores = [s for _n, s in ranked]
        assert scores == sorted(scores, reverse=True)
        tied = [n.tag for n, s in ranked if s == scores[0]]
        assert tied == sorted(tied)

    def test_empty_matches_return_empty(self, db_session, make_project):
        p = make_project()
        assert nrv.rank_matches(db_session, p["id"], [], "anything") == []


class TestRelatedNodesOutput:
    def test_code_pointers_collapse_to_one_per_file(self, db_session, make_project):
        p = make_project()
        units = [
            SourceUnit(kind="code", ref="big.py", text="widget", sha="s", line_start=i, line_end=i)
            for i in range(1, 21)
        ]
        units += [
            SourceUnit(kind="code", ref="other.py", text="widget", sha="s", line_start=5, line_end=5),
            SourceUnit(kind="memory", ref="m", text="widget"),
        ]
        register_sources(db_session, p["id"], units)
        db_session.flush()
        out = nrv.related_nodes(db_session, db_session.get(Project, p["id"]), "widget")
        refs = [c["ref"] for c in out["code"]]
        assert sorted(refs) == ["big.py", "other.py"]
        assert len(refs) == len(set(refs))
        # The kept entry is the file's FIRST line range.
        assert next(c for c in out["code"] if c["ref"] == "big.py")["line_start"] == 1

    def test_every_group_is_capped(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        units = []
        for i in range(15):
            # 15 distinct tags, each grounded in its own memory + code + session doc.
            tag = f"alpha{i}x"
            units.append(SourceUnit(kind="memory", ref=_mem_ref(prefix, f"Agent{i}"), text=tag))
            units.append(SourceUnit(kind="code", ref=f"file{i}.py", text=tag, line_start=1, line_end=1))
            units.append(SourceUnit(kind="session", ref=f"sess-{i}", text=tag))
        register_sources(db_session, pid, units)
        db_session.flush()
        query = " ".join(f"alpha{i}x" for i in range(15))
        out = nrv.related_nodes(db_session, db_session.get(Project, pid), query)
        assert len(out["lessons"]) == nrv.MAX_PER_GROUP
        assert len(out["code"]) == nrv.MAX_PER_GROUP
        assert len(out["sessions"]) == nrv.MAX_PER_GROUP

    def test_top_n_above_cap_is_clamped(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        units = []
        for i in range(15):
            tag = f"beta{i}x"
            units.append(SourceUnit(kind="memory", ref=_mem_ref(prefix, f"Agent{i}"), text=tag))
            units.append(SourceUnit(kind="code", ref=f"f{i}.py", text=tag))
        register_sources(db_session, pid, units)
        db_session.flush()
        query = " ".join(f"beta{i}x" for i in range(15))
        out = nrv.related_nodes(db_session, db_session.get(Project, pid), query, top_n=50)
        assert len(out["lessons"]) == nrv.MAX_PER_GROUP

    def test_entries_carry_a_score_and_are_best_first(self, db_session, make_project):
        p = make_project()
        _seed_wide_corpus(db_session, p["id"])
        out = nrv.related_nodes(
            db_session, db_session.get(Project, p["id"]), "unicorn topic0x"
        )
        scores = [c["score"] for c in out["code"]]
        assert all(s is not None for s in scores)
        assert scores == sorted(scores, reverse=True)

    def test_generic_tag_does_not_lead_the_result(self, db_session, make_project):
        """The DWB-545 repro: a popular tag used to own every group."""
        p = make_project()
        _seed_wide_corpus(db_session, p["id"])
        out = nrv.related_nodes(
            db_session, db_session.get(Project, p["id"]), "common unicorn"
        )
        assert out["code"], "expected the rare tag to still return pointers"
        assert all(c["tag"] != "common" for c in out["code"])

    def test_empty_corpus_still_degrades(self, db_session, make_project):
        p = make_project()
        out = nrv.related_nodes(db_session, db_session.get(Project, p["id"]), "widget")
        assert out["lessons"] == [] and out["code"] == [] and out["sessions"] == []


class TestRelevantLessonsRanking:
    def _objs(self, db, pid, agent_id):
        return db.get(Project, pid), db.get(Agent, agent_id)

    def test_specific_tag_outranks_popular_one(
        self, db_session, make_project, make_agent, make_ticket, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        # 'common' is everywhere; 'unicorn' is in two documents.
        _seed_wide_corpus(db_session, pid)
        ref = _mem_ref(prefix, "Barry")
        _write(tmp_path / ref, "## 2026-09-15T10:00:00+00:00\ncommon unicorn notes\n")
        register_sources(db_session, pid, [
            SourceUnit(kind="memory", ref=ref, text="common unicorn"),
        ])
        db_session.flush()
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        _ticket(make_ticket, prefix, 701, project_id=pid,
                title="common unicorn work", assigned_agent_id=stan["id"], status="todo")
        project, agent = self._objs(db_session, pid, stan["id"])
        lessons = nrv.relevant_lessons(db_session, project, agent)
        assert lessons, "expected a non-empty lesson list"
        assert lessons[0]["tag"] == "unicorn"
        assert all(l["tag"] != "common" for l in lessons)
        assert lessons[0]["score"] is not None

    def test_capped_at_ten(
        self, db_session, make_project, make_agent, make_ticket, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        units, words = [], []
        for i in range(15):
            tag = f"gamma{i}x"
            words.append(tag)
            units.append(SourceUnit(kind="memory", ref=_mem_ref(prefix, f"Agent{i}"), text=tag))
            units.append(SourceUnit(kind="code", ref=f"g{i}.py", text=tag))
            _write(tmp_path / _mem_ref(prefix, f"Agent{i}"),
                   f"## 2026-09-15T00:0{i % 10}:00+00:00\n{tag} lesson\n")
        register_sources(db_session, pid, units)
        db_session.flush()
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        _ticket(make_ticket, prefix, 702, project_id=pid, title=" ".join(words),
                assigned_agent_id=stan["id"], status="todo")
        project, agent = self._objs(db_session, pid, stan["id"])
        assert len(nrv.relevant_lessons(db_session, project, agent)) == nrv.MAX_PER_GROUP

    def test_spawn_prepare_returns_non_empty_lessons(
        self, client, db_session, make_project, make_agent, make_ticket, tmp_path
    ):
        """AC: an agent holding a todo ticket gets lessons when memory matches."""
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        ref = _mem_ref(prefix, "Barry")
        _write(tmp_path / ref, "## 2026-09-15T10:00:00+00:00\nunicorn pipeline lesson\n")
        register_sources(db_session, pid, [
            SourceUnit(kind="memory", ref=ref, text="unicorn pipeline"),
            SourceUnit(kind="code", ref="handler.py", text="unicorn pipeline"),
        ])
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        _ticket(make_ticket, prefix, 703, project_id=pid, title="unicorn pipeline work",
                assigned_agent_id=stan["id"], status="todo")
        db_session.commit()
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Stan", "project_prefix": prefix,
        })
        assert r.status_code == 200, r.text
        lessons = r.json()["relevant_lessons"]
        assert lessons, "relevant_lessons must not be empty when memory nodes match"
        assert "unicorn" in {l["tag"] for l in lessons}


class TestLengthNormalization:
    """DWB-545: a sprawling doc must not outrank a focused source file just by
    mentioning more of the query's vocabulary."""

    def test_long_file_loses_to_focused_file(self, db_session, make_project):
        p = make_project()
        pid = p["id"]
        units = []
        # A focused file: 3 lines, all about the query's two concepts.
        for i, word in enumerate(("widgetize", "gadgetize", "widgetize"), start=1):
            units.append(SourceUnit(kind="code", ref="focused.py", text=word,
                                    line_start=i, line_end=i))
        # A sprawling doc: the same two concepts plus 60 lines of other material.
        units.append(SourceUnit(kind="doc", ref="SPRAWL.md", text="widgetize",
                                line_start=1, line_end=1))
        units.append(SourceUnit(kind="doc", ref="SPRAWL.md", text="gadgetize",
                                line_start=2, line_end=2))
        filler = [f"unrelated{i}x" for i in range(3, 63)]
        for i, word in enumerate(filler, start=3):
            units.append(SourceUnit(kind="doc", ref="SPRAWL.md", text=word,
                                    line_start=i, line_end=i))
        # The filler must GROUND (2-domain rule) or SPRAWL.md carries no pointers
        # and reads as a short file: length here is grounded tag-lines, not bytes.
        units.append(SourceUnit(kind="memory", ref="filler-mem", text=" ".join(filler)))
        units.append(SourceUnit(kind="memory", ref="m", text="widgetize gadgetize"))
        register_sources(db_session, pid, units)
        db_session.flush()
        assert nrv._file_lengths(db_session, pid, ["SPRAWL.md"])["SPRAWL.md"] == 62

        out = nrv.related_nodes(
            db_session, db_session.get(Project, pid), "widgetize gadgetize"
        )
        refs = [c["ref"] for c in out["code"]]
        assert refs[0] == "focused.py", f"expected the focused file first, got {refs}"
        assert "SPRAWL.md" in refs

    def test_file_lengths_helper_counts_pointers_per_ref(self, db_session, make_project):
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="code", ref="a.py", text="widget", line_start=1, line_end=1),
            SourceUnit(kind="code", ref="a.py", text="widget", line_start=2, line_end=2),
            SourceUnit(kind="memory", ref="m", text="widget"),
        ])
        db_session.flush()
        lengths = nrv._file_lengths(db_session, p["id"], ["a.py", "m", "missing.py"])
        assert lengths["a.py"] == 2 and lengths["m"] == 1
        assert "missing.py" not in lengths
        assert nrv._file_lengths(db_session, p["id"], []) == {}

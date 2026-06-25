# Path: tests/test_session_synthesizer.py
# File: test_session_synthesizer.py
# Created: 2026-06-25
# Purpose: Unit tests for the pure session-summary synthesizer (DWB-483). Pure
#          function over a rollup fixture - no DB, no client fixture needed.
# Caller: pytest
# Callees: app.services.session_synthesizer
# Data In: hand-built rollup dicts
# Data Out: assertions
# Last Modified: 2026-06-25

"""DWB-483: deterministic synthesizer unit tests.

The synthesizer is pure (no DB), so these tests build rollup dicts directly and
assert on the three outputs: headline, summary JSON, normalized keywords.
"""

from app.services.session_synthesizer import synthesize_session_summary


def _rollup(**overrides) -> dict:
    base = {
        "headline": None,
        "by_role": [],
        "by_ticket": [],
        "tickets_made": 0,
        "tickets_completed": 0,
        "agents_active": 0,
        "ticket_summary": None,
        "completed_tickets": [],
        "total_tokens": 0,
        "total_time_seconds": 0,
        "keywords": [],
    }
    base.update(overrides)
    return base


class TestHeadline:
    def test_supplied_headline_passes_through_verbatim(self):
        out = synthesize_session_summary(_rollup(
            headline="Shipped the jira dup-key 409 fix",
            tickets_completed=1,
        ))
        assert out["headline"] == "Shipped the jira dup-key 409 fix"

    def test_supplied_headline_is_stripped(self):
        out = synthesize_session_summary(_rollup(headline="  trimmed me  "))
        assert out["headline"] == "trimmed me"

    def test_synthesized_when_null_uses_dominant_epic(self):
        out = synthesize_session_summary(_rollup(
            tickets_completed=3,
            ticket_summary="Help Center (3)",
        ))
        assert out["headline"] == "Completed 3 tickets in Help Center"

    def test_synthesized_falls_back_to_ticket_keys(self):
        out = synthesize_session_summary(_rollup(
            tickets_completed=2,
            by_ticket=[
                {"ticket_key": "DWB-476", "title": "fix", "tokens": 100, "time_seconds": 5},
                {"ticket_key": "DWB-473", "title": "docs", "tokens": 50, "time_seconds": 3},
            ],
        ))
        assert out["headline"] == "Completed 2 tickets: DWB-476, DWB-473"

    def test_synthesized_created_only(self):
        out = synthesize_session_summary(_rollup(tickets_made=4, agents_active=2))
        assert out["headline"] == "Created 4 tickets across 2 agents"

    def test_synthesized_worked_only(self):
        out = synthesize_session_summary(_rollup(
            by_ticket=[{"ticket_key": "DWB-99", "title": "x", "tokens": 10, "time_seconds": 1}],
            agents_active=1,
        ))
        assert out["headline"] == "Worked DWB-99 with 1 agent"

    def test_never_null_when_activity_exists(self):
        # Tokens only, no ticket churn, no agents counted.
        out = synthesize_session_summary(_rollup(total_tokens=5000))
        assert out["headline"] is not None
        assert out["headline"].strip() != ""

    def test_headline_capped_at_ten_words(self):
        out = synthesize_session_summary(_rollup(
            tickets_completed=1,
            ticket_summary="A Very Long Epic Name With Many Many Words Indeed (1)",
        ))
        assert len(out["headline"].split()) <= 10

    def test_none_when_no_activity(self):
        out = synthesize_session_summary(_rollup())
        assert out["headline"] is None
        assert out["summary"]["lead"] == "No tracked activity this session."
        assert out["summary"]["sections"] == []


class TestSummarySections:
    def test_tickets_section_lists_completed_with_names(self):
        out = synthesize_session_summary(_rollup(
            tickets_completed=2,
            tickets_made=1,
            completed_tickets=[
                {"ticket_key": "DWB-476", "title": "jira dup fix"},
                {"ticket_key": "DWB-473", "title": "help content"},
            ],
        ))
        tickets = next(s for s in out["summary"]["sections"] if s["title"] == "Tickets")
        assert tickets["bullets"][0] == "2 completed: DWB-476 jira dup fix; DWB-473 help content"
        assert "1 created" in tickets["bullets"]

    def test_completed_list_truncates_with_more(self):
        completed = [{"ticket_key": f"DWB-{i}", "title": f"t{i}"} for i in range(7)]
        out = synthesize_session_summary(_rollup(
            tickets_completed=7, completed_tickets=completed
        ))
        tickets = next(s for s in out["summary"]["sections"] if s["title"] == "Tickets")
        assert "(+2 more)" in tickets["bullets"][0]

    def test_team_section_aggregates_tokens_by_role(self):
        out = synthesize_session_summary(_rollup(
            agents_active=3,
            by_role=[
                {"agent_id": 1, "agent_name": "A", "role": "backend-worker", "tokens": 100, "time_seconds": 1},
                {"agent_id": 2, "agent_name": "B", "role": "backend-worker", "tokens": 50, "time_seconds": 1},
                {"agent_id": 3, "agent_name": "C", "role": "frontend-worker", "tokens": 200, "time_seconds": 1},
            ],
        ))
        team = next(s for s in out["summary"]["sections"] if s["title"] == "Team")
        assert team["bullets"][0] == "3 agents active"
        # frontend-worker (200) sorts before backend-worker (150).
        assert team["bullets"][1] == "frontend-worker: 200 tokens"
        assert team["bullets"][2] == "backend-worker: 150 tokens"

    def test_cost_section_formats_tokens_and_duration(self):
        out = synthesize_session_summary(_rollup(
            total_tokens=210000, total_time_seconds=3 * 3600 + 12 * 60
        ))
        cost = next(s for s in out["summary"]["sections"] if s["title"] == "Cost")
        assert cost["bullets"] == ["210,000 tokens over 3h 12m"]

    def test_empty_sections_omitted(self):
        out = synthesize_session_summary(_rollup(total_tokens=100))
        titles = [s["title"] for s in out["summary"]["sections"]]
        assert titles == ["Cost"]  # no Tickets, no Team

    def test_lead_mirrors_headline(self):
        out = synthesize_session_summary(_rollup(headline="Did the thing", total_tokens=10))
        assert out["summary"]["lead"] == "Did the thing"


class TestKeywords:
    def test_normalizes_tuples_sorted_desc(self):
        out = synthesize_session_summary(_rollup(
            keywords=[("tmux", 50), ("DWB-468", 7), ("session", 12)]
        ))
        assert out["keywords"] == [
            {"keyword": "tmux", "weight": 50},
            {"keyword": "session", "weight": 12},
            {"keyword": "DWB-468", "weight": 7},
        ]

    def test_accepts_dict_input(self):
        out = synthesize_session_summary(_rollup(
            keywords=[{"keyword": "alpha", "weight": 3}, {"keyword": "beta", "weight": 9}]
        ))
        assert out["keywords"][0] == {"keyword": "beta", "weight": 9}

    def test_tiebreak_keyword_ascending(self):
        out = synthesize_session_summary(_rollup(
            keywords=[("zeta", 5), ("alpha", 5)]
        ))
        assert [k["keyword"] for k in out["keywords"]] == ["alpha", "zeta"]

    def test_drops_blank_and_coerces_bad_weight(self):
        out = synthesize_session_summary(_rollup(
            keywords=[("", 9), ("  ", 3), ("ok", None), ("good", "notanint")]
        ))
        kws = {k["keyword"]: k["weight"] for k in out["keywords"]}
        assert "ok" in kws and kws["ok"] == 0
        assert "good" in kws and kws["good"] == 0
        assert "" not in kws

    def test_caps_at_twenty(self):
        out = synthesize_session_summary(_rollup(
            keywords=[(f"k{i:02d}", 100 - i) for i in range(30)]
        ))
        assert len(out["keywords"]) == 20


class TestDeterminismAndShape:
    def test_same_rollup_same_output(self):
        rollup = _rollup(
            headline=None,
            tickets_completed=2,
            ticket_summary="Epic X (2)",
            by_role=[{"agent_id": 1, "agent_name": "A", "role": "backend-worker", "tokens": 10, "time_seconds": 1}],
            keywords=[("a", 3), ("b", 3)],
            total_tokens=10,
            total_time_seconds=60,
        )
        assert synthesize_session_summary(dict(rollup)) == synthesize_session_summary(dict(rollup))

    def test_output_has_three_keys(self):
        out = synthesize_session_summary(_rollup())
        assert set(out.keys()) == {"headline", "summary", "keywords"}
        assert set(out["summary"].keys()) == {"lead", "sections"}

    def test_none_input_is_safe(self):
        out = synthesize_session_summary(None)
        assert out["headline"] is None
        assert out["summary"]["sections"] == []
        assert out["keywords"] == []

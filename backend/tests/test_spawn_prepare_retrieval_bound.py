# Path: tests/test_spawn_prepare_retrieval_bound.py
# File: test_spawn_prepare_retrieval_bound.py
# Created: 2026-09-29
# Purpose: Guards spawn-prepare against the retrieval stall that blocked every
#          ticketed spawn on S83. relevant_lessons matched an agent's assigned
#          ticket text against the node graph, and match_nodes derived neighbors
#          for EVERY matched node - a per-node join over node_pointers whose
#          results retrieval then discarded. At project scale that was ~0.4s per
#          matched node (263 matched nodes -> 107s), so spawn-prepare read as a
#          hang. These tests pin the contract that matters: spawn-prepare returns
#          within a bounded wall clock for an agent carrying a large volume of
#          assigned ticket text, and an empty retrieval is reported rather than
#          silently indistinguishable from "no lessons found".
# Caller: pytest
# Callees: app/services/agent.spawn_prepare_payload, app/services/node_retrieval
# Data In: fixture project seeded with a corpus shaped like the real node graph
#          (a few large docs that mention everything, plus per-agent memory files)
# Data Out: assertions on elapsed wall clock and on the retrieval status field
# Last Modified: 2026-09-29

"""Wall-clock bound on the spawn-prepare retrieval lane.

The fixture is deliberately built from REAL volumes rather than a toy string.
A toy string is what let the original stall through: it matched a handful of
nodes, so the per-matched-node cost never showed up. The corpus here reproduces
the shape that actually bites - a small number of sprawling documents that
mention most of the project's vocabulary, so nearly every matched node shares
refs with nearly every other one - and the ticket text is sized to the largest
real assignment observed (~19.5k characters across four tickets).
"""

import time

import pytest

from app.models.agent import Agent
from app.models.project import Project
from app.services import agent as agent_svc
from app.services import node_registry as nr
from app.services import node_retrieval

# The observed ceiling for a healthy spawn-prepare is well under a second; the
# broken path took 107s for the same input. Ten seconds is far enough above the
# former and below the latter that it fails for a real regression and not for a
# slow machine or a cold connection pool.
BOUND_SECONDS = 10.0

# Sized from the real S83 blocker: Barry_DWB carried four tickets totalling
# 19545 characters, which tokenized to 557 tags and matched 263 nodes.
_TARGET_TICKET_CHARS = 19500
_VOCAB_SIZE = 400

# Mirrors the real graph's worst feature: docs/team_lead_playbook.md alone held
# 3947 pointers and ARCHITECTURE.md 3015, because a playbook mentions every
# concept in the project. Those shared refs are what make every matched node a
# neighbor of every other one.
_SPRAWLING_DOCS = [
    "docs/team_lead_playbook.md",
    "docs/worker_playbook.md",
    "docs/pm_playbook.md",
    "ARCHITECTURE.md",
    "README.md",
    "HANDOFF.md",
]
_MEMORY_AGENTS = ["Barry", "Freddie", "Stan", "Dolores", "Pam", "Archie"]


def _vocabulary(n=_VOCAB_SIZE):
    """Distinct, non-stopword, multi-part tags.

    Multi-part on purpose: the ranking layer boosts hyphenated tags, so a
    single-word vocabulary would exercise a different ranking path than the real
    corpus does.
    """
    return [f"retrieval-concept-{i:04d}" for i in range(n)]


def _seed_sprawling_corpus(db, pid, prefix, repo_root, vocab):
    """Seed a corpus shaped like the real one: sprawling docs + memory files.

    Every sprawling doc mentions the WHOLE vocabulary (that is what a playbook
    does), and each agent's memory.md mentions a slice of it under an ISO
    heading so the memory-entry resolution path runs for real.
    """
    units = [
        nr.SourceUnit(kind="doc", ref=ref, text=" ".join(vocab))
        for ref in _SPRAWLING_DOCS
    ]

    slice_size = max(1, len(vocab) // len(_MEMORY_AGENTS))
    for idx, name in enumerate(_MEMORY_AGENTS):
        chunk = vocab[idx * slice_size:(idx + 1) * slice_size]
        body = f"## 2026-09-20T0{idx}:00:00+00:00\n" + " ".join(chunk) + "\n"
        path = repo_root / ".dwb" / "memory" / prefix / name / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        units.append(
            nr.SourceUnit(
                kind="memory",
                ref=f".dwb/memory/{prefix}/{name}/memory.md",
                text=body,
            )
        )

    nr.register_sources(db, pid, units)
    db.flush()


def _ticket_text(vocab, target_chars=_TARGET_TICKET_CHARS):
    """Ticket body sized to the real assignment that triggered the stall."""
    body = []
    size = 0
    i = 0
    while size < target_chars:
        term = vocab[i % len(vocab)]
        body.append(term)
        size += len(term) + 1
        i += 1
    return " ".join(body)


@pytest.fixture
def heavy_spawn_agent(db_session, make_project, make_agent, make_ticket, tmp_path):
    """A project with a sprawling corpus and an agent carrying four big tickets."""
    project = make_project(repo_path=str(tmp_path))
    pid = project["id"]
    vocab = _vocabulary()
    _seed_sprawling_corpus(db_session, pid, project["prefix"], tmp_path, vocab)

    spawning = make_agent(project_id=pid, name="HeavyLoad", role="backend-worker")
    text = _ticket_text(vocab)
    per_ticket = len(text) // 4
    for n in range(4):
        make_ticket(
            project_id=pid,
            title=f"retrieval bound fixture ticket {n}",
            description=text[n * per_ticket:(n + 1) * per_ticket],
            assigned_agent_id=spawning["id"],
            status="in_progress",
        )
    db_session.flush()
    return project, spawning


class TestSpawnPrepareBounded:
    def test_returns_within_bound_with_large_ticket_text(
        self, db_session, heavy_spawn_agent
    ):
        """spawn-prepare must return promptly however much ticket text an agent carries.

        RED before the fix: the neighbor derivation inside match_nodes ran once
        per matched node and blew past the bound by an order of magnitude.
        """
        project, spawning = heavy_spawn_agent
        start = time.monotonic()
        payload = agent_svc.spawn_prepare_payload(
            db_session,
            role=spawning["role"],
            name=spawning["name"],
            project_prefix=project["prefix"],
        )
        elapsed = time.monotonic() - start

        assert elapsed < BOUND_SECONDS, (
            f"spawn-prepare took {elapsed:.1f}s for an agent with "
            f"{_TARGET_TICKET_CHARS} characters of assigned ticket text; "
            f"the bound is {BOUND_SECONDS}s"
        )
        assert payload["agent_id"] == spawning["id"]

    def test_retrieval_still_returns_lessons(self, db_session, heavy_spawn_agent):
        """The bound must not be met by silently returning nothing.

        Deleting or short-circuiting the retrieval call would make the timing
        test pass and the product worse, so pin that the lane still produces
        pointers from other agents' memories.
        """
        project, spawning = heavy_spawn_agent
        payload = agent_svc.spawn_prepare_payload(
            db_session,
            role=spawning["role"],
            name=spawning["name"],
            project_prefix=project["prefix"],
        )

        lessons = payload["relevant_lessons"]
        assert lessons, "retrieval returned no lessons for a corpus built to match"
        assert all(lesson["source_agent"] != spawning["name"] for lesson in lessons)
        assert any(lesson["entry_heading"] for lesson in lessons)


class _FakeClock:
    """Deterministic clock: every reading advances by a fixed step.

    The budget is wall-clock, so asserting on it with the real clock would make
    these tests race a loaded machine. Injecting the clock is what buys the
    determinism; the step is what makes expiry arrive at a known reading rather
    than at a known moment.
    """

    def __init__(self, step=1.0, start=0.0):
        self.now = start
        self.step = step
        self.readings = 0

    def __call__(self):
        self.readings += 1
        value = self.now
        self.now += self.step
        return value


class TestRetrievalBudget:
    """The budget inside relevant_lessons, and the status that reports it."""

    def test_budget_truncates_instead_of_running_long(
        self, db_session, heavy_spawn_agent, make_agent
    ):
        """An exhausted budget returns TRUNCATED, not a silently short list."""
        project, spawning = heavy_spawn_agent
        project_obj = db_session.get(Project, project["id"])
        agent_obj = db_session.get(Agent, spawning["id"])

        # Step past the budget on the very first reading, so expiry is certain.
        result = node_retrieval.relevant_lessons(
            db_session, project_obj, agent_obj,
            budget_seconds=0.5, clock=_FakeClock(step=10.0),
        )

        assert result.status == node_retrieval.TRUNCATED
        assert result.truncated is True

    def test_unbounded_budget_runs_to_completion(self, db_session, heavy_spawn_agent):
        """budget_seconds=None disables the bound and reports COMPLETE."""
        project, spawning = heavy_spawn_agent
        project_obj = db_session.get(Project, project["id"])
        agent_obj = db_session.get(Agent, spawning["id"])

        result = node_retrieval.relevant_lessons(
            db_session, project_obj, agent_obj, budget_seconds=None
        )

        assert result.status == node_retrieval.COMPLETE
        assert result.lessons

    def test_no_tickets_is_not_attempted_not_empty_complete(
        self, db_session, heavy_spawn_agent, make_agent
    ):
        """The distinction the old bare list could not express.

        An agent with no tickets produces an empty list, and so does an agent
        whose tickets matched nothing. Those are different facts and the status
        has to tell them apart, because conflating them is what let the retrieval
        lane return nothing for a whole sprint without anyone noticing.
        """
        project, _spawning = heavy_spawn_agent
        idle = make_agent(project_id=project["id"], name="IdleNoTickets",
                          role="backend-worker")
        project_obj = db_session.get(Project, project["id"])
        idle_obj = db_session.get(Agent, idle["id"])

        result = node_retrieval.relevant_lessons(db_session, project_obj, idle_obj)

        assert result.lessons == []
        assert result.status == node_retrieval.NOT_ATTEMPTED

    def test_status_reaches_the_spawn_prepare_payload(
        self, db_session, heavy_spawn_agent
    ):
        """The status must survive the trip to the caller, not stop at the service.

        A status the payload drops is no better than no status at all: the TL
        reads the payload, not the return value.
        """
        project, spawning = heavy_spawn_agent
        payload = agent_svc.spawn_prepare_payload(
            db_session,
            role=spawning["role"],
            name=spawning["name"],
            project_prefix=project["prefix"],
        )

        assert payload["relevant_lessons_status"] == node_retrieval.COMPLETE

    def test_failed_retrieval_is_reported_not_swallowed(
        self, db_session, heavy_spawn_agent, monkeypatch
    ):
        """An exception degrades to FAILED, which is distinct from finding nothing.

        The pre-existing try/except already degraded to an empty list here. What
        was missing is that the empty list looked exactly like success, so the
        spawn bundle could not tell a broken retrieval from a quiet one.
        """
        project, spawning = heavy_spawn_agent

        def boom(*a, **kw):
            raise RuntimeError("retrieval exploded")

        monkeypatch.setattr(node_retrieval, "relevant_lessons", boom)
        payload = agent_svc.spawn_prepare_payload(
            db_session,
            role=spawning["role"],
            name=spawning["name"],
            project_prefix=project["prefix"],
        )

        assert payload["relevant_lessons"] == []
        assert payload["relevant_lessons_status"] == node_retrieval.FAILED

    def test_truncation_keeps_what_it_already_found(
        self, db_session, heavy_spawn_agent
    ):
        """Expiry mid-loop returns the partial result, it does not discard it.

        A bound that throws away completed work to report a clean failure is a
        worse trade than one that hands back what it has and says so. The status
        is what makes the partial list safe to use.
        """
        project, spawning = heavy_spawn_agent
        project_obj = db_session.get(Project, project["id"])
        agent_obj = db_session.get(Agent, spawning["id"])

        # Small step so the early phases pass and expiry lands inside the loop.
        result = node_retrieval.relevant_lessons(
            db_session, project_obj, agent_obj,
            budget_seconds=5.0, clock=_FakeClock(step=0.35),
        )

        assert result.status == node_retrieval.TRUNCATED
        assert result.lessons, "truncation discarded lessons it had already built"

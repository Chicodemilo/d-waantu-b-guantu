# Path: tests/test_memory_usage_rules_mode_aware_dwb638.py
# File: test_memory_usage_rules_mode_aware_dwb638.py
# Created: 2026-10-07
# Purpose: DWB-638 - the inline memory_usage_rules block that identify and spawn-prepare paste into every agent must match the project's memory_mode. A human_memory agent must never be handed the stock block, which teaches the four routes DWB-589 seals at 409.
# Caller: pytest (auto-collected)
# Callees: app.config.memory_rules, app.services.memory_mode, /api/agents/identify, /api/agents/spawn-prepare
# Data In: client fixture, make_project / make_agent factories, tmp_path
# Data Out: pass/fail assertions
# Last Modified: 2026-10-07 (DWB-638)

"""The spawn-time rules block, checked against the seal it has to agree with.

This block reaches further than any markdown file, because the TL pastes the
spawn-prepare payload into the prompt whether or not anybody opens a playbook.
Until DWB-638 it was one constant, served to every agent on every project, and
it named `memory/append`, `session-complete` and `memory/condense` - exactly
the routes `memory_mode.assert_stock_write_allowed` refuses with 409 under
`human_memory`. DWB was the thing teaching the sealed routes.

THE SEALED-ROUTE LIST IS DERIVED, NOT RETYPED. `_WRITE_REPLACEMENT` is the one
definition of what is sealed, so a fifth route sealed later is covered by this
test the day it is added rather than the day someone remembers to update a
literal list here. A hand-written list would pass forever while the surface
grew underneath it.
"""

import pytest

from app.config.memory_rules import (
    HUMAN_MEMORY_USAGE_RULES,
    MEMORY_USAGE_RULES,
    MEMORY_USAGE_RULES_MAX_CHARS,
)
from app.services import memory_mode as memory_mode_svc


def _sealed_route_suffixes() -> set[str]:
    """Every route the seal refuses, derived from the seal's own table."""
    sealed = set(memory_mode_svc._WRITE_REPLACEMENT)
    assert sealed, "the seal table is empty; this test would pass vacuously"
    return sealed


def _project_row(db, project_dict):
    """The ORM row behind a factory's response dict.

    The selector takes a `Project`, not the JSON the factory hands back, and
    passing the dict would raise rather than quietly answer wrong - but it
    would raise in a way that reads as a test bug, so the conversion is
    explicit and named.
    """
    from app.models.project import Project

    row = db.get(Project, project_dict["id"])
    assert row is not None, f"project {project_dict['id']} not in the session"
    return row


class TestTheHumanMemoryBlockNamesNoSealedRoute:
    """AC2/AC3: an agent on a human_memory project is not told to call a 409."""

    def test_human_block_names_no_sealed_route(self):
        named = sorted(s for s in _sealed_route_suffixes() if s in HUMAN_MEMORY_USAGE_RULES)
        assert named == [], (
            f"HUMAN_MEMORY_USAGE_RULES names sealed route(s) {named}. An agent "
            "reading this block would call an endpoint that returns 409."
        )

    def test_human_block_points_at_the_replacement(self):
        """Naming nothing is not enough; the agent needs somewhere to write.

        A block that only said "do not do that" would pass the test above and
        strand every lesson on a human_memory project.
        """
        assert "/memories" in HUMAN_MEMORY_USAGE_RULES
        assert "/api/journal" in HUMAN_MEMORY_USAGE_RULES
        assert "memory/scored" in HUMAN_MEMORY_USAGE_RULES

    def test_human_block_states_the_write_on_close_answer(self):
        """DWB-519 participation, said in the block itself.

        The gate is the one thing an agent must get right before it goes idle,
        and the moment it needs the answer is the moment it is leaving.
        """
        assert "write-on-close" in HUMAN_MEMORY_USAGE_RULES

    def test_the_stock_block_is_unchanged_in_the_ways_that_matter(self):
        """A correctness pass, not an editorial one: stock still teaches stock."""
        assert "memory/append" in MEMORY_USAGE_RULES
        assert "session-complete" in MEMORY_USAGE_RULES
        assert "DURABLE LESSONS ONLY" in MEMORY_USAGE_RULES

    @pytest.mark.parametrize(
        "name,rules",
        [
            ("MEMORY_USAGE_RULES", MEMORY_USAGE_RULES),
            ("HUMAN_MEMORY_USAGE_RULES", HUMAN_MEMORY_USAGE_RULES),
        ],
    )
    def test_both_variants_are_under_the_cap(self, name, rules):
        """A cap only one of two interchangeable payloads meets is not a cap."""
        assert len(rules) <= MEMORY_USAGE_RULES_MAX_CHARS, (
            f"{name} is {len(rules)} chars"
        )


class TestTheSelectorPicksByMode:
    """The unit the two endpoints share."""

    def test_stock_project_gets_the_stock_block(
        self, db_session, make_project, tmp_path,
    ):
        project = _project_row(db_session, make_project(repo_path=str(tmp_path)))
        assert memory_mode_svc.memory_usage_rules_for(project) == MEMORY_USAGE_RULES

    def test_human_memory_project_gets_the_human_block(
        self, db_session, make_project, tmp_path,
    ):
        project = _project_row(
            db_session,
            make_project(repo_path=str(tmp_path), memory_mode="human_memory"),
        )
        assert (
            memory_mode_svc.memory_usage_rules_for(project)
            == HUMAN_MEMORY_USAGE_RULES
        )

    def test_unresolvable_project_gets_the_stock_block(self):
        """None means "cannot tell", and that is not a sealed project.

        Matching `is_human_memory`, which every other caller here already
        treats this way. The mode is opt-in, so stock is the safe default.
        """
        assert memory_mode_svc.memory_usage_rules_for(None) == MEMORY_USAGE_RULES


class TestBothEndpointsServeTheRightBlock:
    """Read it back off the API, not off the constant.

    Both endpoints, because they are separate call sites in separate functions
    and DWB-630's lesson here was precisely that one of a pair can be gated
    while its neighbour fourteen lines away is not.
    """

    def _rules(self, client, path, role, name, prefix):
        r = client.post(
            path, json={"role": role, "name": name, "project_prefix": prefix}
        )
        assert r.status_code == 200, r.text
        return r.json()["memory_usage_rules"]

    @pytest.mark.parametrize(
        "path", ["/api/agents/identify", "/api/agents/spawn-prepare"]
    )
    def test_human_memory_agent_is_never_served_a_sealed_route(
        self, client, make_project, make_agent, tmp_path, path
    ):
        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        agent = make_agent(project_id=project["id"], role="backend-worker")
        rules = self._rules(
            client, path, agent["role"], agent["name"], project["prefix"]
        )
        named = sorted(s for s in _sealed_route_suffixes() if s in rules)
        assert named == [], (
            f"{path} served sealed route(s) {named} to an agent on "
            f"human_memory project {project['prefix']}"
        )
        assert rules == HUMAN_MEMORY_USAGE_RULES

    @pytest.mark.parametrize(
        "path", ["/api/agents/identify", "/api/agents/spawn-prepare"]
    )
    def test_stock_agent_still_gets_the_stock_block(
        self, client, make_project, make_agent, tmp_path, path
    ):
        """The negative control.

        Without it, a selector that returned the human block unconditionally
        would pass every assertion above. The test has to distinguish the
        correct implementation from the plausible wrong one, not merely
        exercise the feature.
        """
        project = make_project(repo_path=str(tmp_path))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        rules = self._rules(
            client, path, agent["role"], agent["name"], project["prefix"]
        )
        assert rules == MEMORY_USAGE_RULES
        assert "memory/append" in rules

    def test_the_two_modes_are_served_different_text(
        self, client, make_project, make_agent, tmp_path
    ):
        """One call, both projects, in the same test.

        Asserting each side separately leaves open the case where the two
        constants are equal, which would satisfy both halves while making the
        whole ticket a no-op.
        """
        stock_p = make_project(repo_path=str(tmp_path / "stock"))
        human_p = make_project(
            repo_path=str(tmp_path / "human"), memory_mode="human_memory"
        )
        stock_a = make_agent(project_id=stock_p["id"], role="backend-worker")
        human_a = make_agent(project_id=human_p["id"], role="backend-worker")

        stock_rules = self._rules(
            client, "/api/agents/spawn-prepare",
            stock_a["role"], stock_a["name"], stock_p["prefix"],
        )
        human_rules = self._rules(
            client, "/api/agents/spawn-prepare",
            human_a["role"], human_a["name"], human_p["prefix"],
        )
        assert stock_rules != human_rules


class TestIdentityMdAgreesWithTheEndpoints:
    """The third surface. identity.md pasted the stock block too."""

    def test_identity_md_on_human_memory_names_no_sealed_route(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.services import agent_memory

        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        agent = make_agent(project_id=project["id"], role="backend-worker")
        agent_memory.scaffold_agent_dir(db_session, agent["id"])

        identity = (
            tmp_path / ".dwb" / "memory" / project["prefix"] / agent["name"] / "identity.md"
        ).read_text(encoding="utf-8")
        named = sorted(s for s in _sealed_route_suffixes() if s in identity)
        assert named == [], f"identity.md names sealed route(s) {named}"
        assert "SEALED" in identity

    def test_identity_md_on_stock_still_teaches_stock(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.services import agent_memory

        project = make_project(repo_path=str(tmp_path))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        agent_memory.scaffold_agent_dir(db_session, agent["id"])

        identity = (
            tmp_path / ".dwb" / "memory" / project["prefix"] / agent["name"] / "identity.md"
        ).read_text(encoding="utf-8")
        assert "memory/append" in identity
        assert "session-complete" in identity

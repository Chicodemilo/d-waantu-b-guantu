# Path: tests/test_gate_refusals_name_reachable_routes_dwb688.py
# File: test_gate_refusals_name_reachable_routes_dwb688.py
# Created: 2026-10-28 (DWB-688)
# Purpose: The three close-gate refusals must name a route the project's
#          memory_mode actually accepts. On human_memory, memory/append,
#          session-complete and memory/compact all 409, so a refusal naming
#          them is a wall whose sign points at another wall.
# Caller: pytest
# Callees: memory_mode.write_on_close_instruction / compaction_agent_clause,
#          sprint-close + session-close endpoints
# Data In: lat_test DB rows, tmp_path repos
# Data Out: assertions
# Last Modified: 2026-10-28 (DWB-688: created)

"""Both directions, per gate, in one file.

WHY THE ABSENCE ASSERTION IS NOT ENOUGH ON ITS OWN, and it is the reason every
test here comes in a pair. "No sealed route appears in this refusal" passes
perfectly against a gate that returns an empty string, against a gate that
stopped firing, and against a project that was never in human_memory mode in
the first place. Each sealed-route assertion is therefore paired with a
positive one in the same test: the refusal must still fire, and must name the
route that DOES work. An absence is only evidence beside the positive set.

AND THE STOCK HALF IS THE CONTROL THAT PROVES THE PREDICATE WAS NOT TOUCHED.
`memory_trace.agent_wrote_since` has been mode-aware since DWB-589 and was
always correct; DWB-688 changed only the sentence. A stock refusal that still
names memory/append, unchanged, is what distinguishes "the text was fixed" from
"somebody widened the gate until it stopped complaining".
"""

from datetime import date, datetime, timedelta, timezone

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.services.memory_mode import HUMAN_MEMORY_REQUIRED_FIELDS

# Every route the seal refuses with 409 under human_memory. Transcribed from
# `memory_mode._WRITE_REPLACEMENT` rather than imported, deliberately: importing
# the mapping this file is checking against would only prove the module equals
# itself. If a route is added there, this list is meant to go stale loudly in
# review rather than silently agree.
SEALED_ROUTES = (
    "memory/append",
    "memory/condense",
    "memory/compact",
    "session-complete",
)


def _assert_no_sealed_route(detail: str) -> None:
    """No sealed route anywhere in the refusal, named by the one that leaked.

    Asserted over the WHOLE string rather than per-fragment: the defect in
    DWB-688 was a route nobody had thought to look for, so a check that walks a
    list of expected fragments is that same list written twice.
    """
    leaked = [r for r in SEALED_ROUTES if r in detail]
    assert not leaked, f"refusal names sealed route(s) {leaked}: {detail}"


def _open_session(db_session, pid, hours_ago=1):
    s = DwbSession(
        project_id=pid,
        opened_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        open_method=DwbOpenMethod.slash,
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def _sprint_setup(make_project, make_agent, make_sprint, make_ticket, tmp_path, **proj):
    project = make_project(
        repo_path=str(tmp_path), force_handoff_md=False, **proj
    )
    agent = make_agent(project_id=project["id"], name="Gus", role="backend-worker")
    sprint = make_sprint(
        project_id=project["id"],
        status="active",
        start_date=(date.today() - timedelta(days=1)).isoformat(),
    )
    make_ticket(
        project_id=project["id"], sprint_id=sprint["id"], assigned_agent_id=agent["id"]
    )
    return project, sprint


class TestSprintWriteOnCloseRefusal:
    """services/sprint.py — the sprint-close write-on-close gate."""

    def test_human_memory_names_memories_and_its_required_fields(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        _, sprint = _sprint_setup(
            make_project, make_agent, make_sprint, make_ticket, tmp_path,
            memory_mode="human_memory",
        )
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        # Positive: the gate still fires, still names the non-writer, and now
        # names the route that works.
        assert "write-on-close gate failed" in detail
        assert "Gus" in detail
        assert "/memories" in detail
        for field in HUMAN_MEMORY_REQUIRED_FIELDS:
            assert field in detail, f"{field} not named in refusal: {detail}"
        # Negative, only meaningful beside the above.
        _assert_no_sealed_route(detail)

    def test_stock_refusal_still_names_memory_append(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        _, sprint = _sprint_setup(
            make_project, make_agent, make_sprint, make_ticket, tmp_path
        )
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "write-on-close gate failed" in detail
        assert "memory/append" in detail
        assert "/session-complete" in detail
        assert "/memories" not in detail

    def test_no_unsubstituted_brace_placeholder(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        """The gate used to emit a literal `{id}` - an f-string someone forgot.

        It names several agents at once and has no single id to interpolate, so
        the fix is an explicit `<agent_id>` placeholder, not interpolation.
        """
        _, sprint = _sprint_setup(
            make_project, make_agent, make_sprint, make_ticket, tmp_path
        )
        detail = client.patch(
            f"/api/sprints/{sprint['id']}", json={"status": "completed"}
        ).json()["detail"]
        assert "{id}" not in detail
        assert "{agent_id}" not in detail
        assert "<agent_id>" in detail


class TestSessionWriteOnCloseRefusal:
    """routers/dwb_sessions.py — the explicit-close write-on-close gate."""

    def _close(self, client, db_session, make_project, make_agent, tmp_path, **proj):
        project = make_project(repo_path=str(tmp_path), **proj)
        make_agent(project_id=project["id"], name="Hal", role="team-lead")
        session = _open_session(db_session, project["id"])
        r = client.post(
            f"/api/sessions/{session.id}/close",
            json={
                "close_method": "slash",
                "close_reason": "explicit",
                "headline": "a probe close",
            },
        )
        assert r.status_code == 422, r.text
        return r.json()["detail"]

    def test_human_memory_names_memories_and_its_required_fields(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        detail = self._close(
            client, db_session, make_project, make_agent, tmp_path,
            memory_mode="human_memory",
        )
        assert "Write-on-close" in detail
        assert "Hal" in detail
        assert "/memories" in detail
        for field in HUMAN_MEMORY_REQUIRED_FIELDS:
            assert field in detail, f"{field} not named in refusal: {detail}"
        _assert_no_sealed_route(detail)

    def test_stock_refusal_is_unchanged(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        """The stock sentence is the control for "only the text moved".

        Asserted as the whole clause, not a fragment: this is the one gate whose
        stock text DWB-688 left byte-identical, so it can be pinned exactly.
        """
        detail = self._close(client, db_session, make_project, make_agent, tmp_path)
        assert "your memory.md via POST /api/agents/" in detail
        assert "/memory/append (or /session-complete), then retry the close." in detail
        assert "/memories" not in detail


class TestCompactionGateRefusal:
    """routers/dwb_sessions.py — the compaction gate.

    Reached only with `force_consolidation` on, a shared root doc over ceiling,
    an ai_* close, and the write-on-close gate above already satisfied. Ordered
    refusals mean a reachability question PER CHECK: a 422 from the wrong gate
    reads exactly like a 422 from this one, so every test here asserts the
    "Compaction gate" prefix before looking at anything else.
    """

    def _over_ceiling_close(
        self, client, db_session, make_project, make_agent, tmp_path, **proj
    ):
        project = make_project(
            repo_path=str(tmp_path), force_consolidation=True, **proj
        )
        agent = make_agent(project_id=project["id"], name="Ivy", role="team-lead")
        for name in ("HANDOFF.md", "ARCHITECTURE.md", "README.md"):
            (tmp_path / name).write_text("# x\n\n" + ("word " * 30000), encoding="utf-8")
        session = _open_session(db_session, project["id"])
        # The write-on-close gate sits in FRONT of this one and answers first,
        # so it has to be satisfied or every test here measures the wrong gate.
        # AND IT MUST BE SATISFIED THE WAY THIS MODE COUNTS: agent_wrote_since
        # reads the human_memory STORE on a human_memory project (DWB-589), so
        # an on-disk memory.md satisfies stock and does nothing here. Writing
        # the file for both modes is what the first version of this fixture
        # did, and it silently measured the write-on-close refusal while
        # claiming to measure compaction.
        if project.get("memory_mode") == "human_memory":
            w = client.post(
                f"/api/agents/{agent['id']}/memories",
                json={
                    "body": "A row landed only to get past the write-on-close gate.",
                    "condensed": "The compaction gate sits behind the write-on-close gate.",
                    "situation": (
                        "I was closing a probe session on a throwaway project "
                        "and the compaction gate needed a memory row first."
                    ),
                    "keywords": ["probe", "compaction", "throwaway", "session"],
                },
                headers={"X-Agent-ID": str(agent["id"])},
            )
            assert w.status_code == 201, f"fixture could not land a row: {w.text}"
        else:
            (tmp_path / ".dwb" / "memory" / project["prefix"] / "Ivy").mkdir(
                parents=True, exist_ok=True
            )
            mem = tmp_path / ".dwb" / "memory" / project["prefix"] / "Ivy" / "memory.md"
            mem.write_text("## now\nwrote\n", encoding="utf-8")
        return client.post(
            f"/api/sessions/{session.id}/close",
            json={
                "close_method": "ai_confident",
                "close_reason": "explicit",
                "headline": "a probe compaction close",
            },
        )

    def test_stock_refusal_still_names_memory_compact(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        r = self._over_ceiling_close(
            client, db_session, make_project, make_agent, tmp_path
        )
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert "Compaction gate" in detail
        assert "memory/compact" in detail
        # The literal `{agent_id}` this string used to emit is now an explicit
        # placeholder.
        assert "{agent_id}" not in detail
        assert "<agent_id>" in detail

    def test_human_memory_names_no_sealed_compaction_route(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        r = self._over_ceiling_close(
            client, db_session, make_project, make_agent, tmp_path,
            memory_mode="human_memory",
        )
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        # Positive: the gate still fires and still says what to do about the
        # root docs, which are the only files that can trigger it.
        assert "Compaction gate" in detail
        assert "the team-lead compacts the shared root docs" in detail
        # Negative: and it no longer sends a human_memory agent at a 409.
        _assert_no_sealed_route(detail)


class TestTheHelperItself:
    """The one definition the three gates share.

    A unit-level pair beside the route-level ones above because the gates are
    expensive to reach (four preconditions for compaction alone) and a future
    gate will call this helper without any of them.
    """

    def test_stock_and_human_memory_differ_and_neither_is_empty(self, make_project, db_session):
        from app.models.project import Project
        from app.services.memory_mode import (
            compaction_agent_clause,
            write_on_close_instruction,
        )

        stock = db_session.get(Project, make_project()["id"])
        human = db_session.get(Project, make_project(memory_mode="human_memory")["id"])

        stock_write = write_on_close_instruction(stock, 7)
        human_write = write_on_close_instruction(human, 7)
        assert "memory/append" in stock_write
        assert "/api/agents/7/memories" in human_write
        _assert_no_sealed_route(human_write)
        assert stock_write != human_write

        assert "memory/compact" in compaction_agent_clause(stock)
        _assert_no_sealed_route(compaction_agent_clause(human))
        assert compaction_agent_clause(human).strip() != ""

    def test_none_project_is_treated_as_stock(self):
        """`None` means "cannot tell", and every other reader here treats that
        as not-sealed. A gate that cannot resolve a project must not start
        telling people their stock memory is sealed."""
        from app.services.memory_mode import (
            compaction_agent_clause,
            write_on_close_instruction,
        )

        assert "memory/append" in write_on_close_instruction(None, 7)
        assert "memory/compact" in compaction_agent_clause(None)

    def test_missing_agent_id_yields_an_explicit_placeholder(self):
        from app.services.memory_mode import write_on_close_instruction

        text = write_on_close_instruction(None)
        assert "<agent_id>" in text
        assert "{id}" not in text and "{agent_id}" not in text

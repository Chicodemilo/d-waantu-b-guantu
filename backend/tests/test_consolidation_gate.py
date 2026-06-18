# Path:          tests/test_consolidation_gate.py
# File:          test_consolidation_gate.py
# Created:       2026-06-04
# Purpose:       Tests for force_consolidation gate — ack endpoint, status endpoint, sprint-close enforcement, DWB-328 trim-or-override teeth
# Caller:        pytest
# Callees:       POST /api/agents/:id/consolidate-complete, DELETE /api/agents/:id/consolidate-complete/:sprint_id,
#                GET /api/projects/:id/consolidation-status, PATCH /api/sprints/:id (close), GET /api/projects/:id/token-budget
# Data In:       Factory-created projects, sprints, agents + a temp repo for owner-mapping cases
# Data Out:      Assertions on ack responses, status payload owner mapping, sprint-close blocks, override enforcement
# Last Modified: 2026-06-05

"""Tests for the consolidation gate (DWB-style untracked feature, 2026-06-04).

Covers:
  - POST /api/agents/:id/consolidate-complete — happy path, 409 already-acked,
    400 inactive agent, 400 wrong-project agent
  - GET /api/projects/:id/consolidation-status — owner mapping for repo files
    and memory files, gate_satisfied flag, per-agent overrides field
  - PATCH /api/sprints/:id status=completed — blocked when force_consolidation
    is on and acks are missing; passes when all agents have acked; ignored
    when toggle is off
  - DWB-328: trim-or-override enforcement at ack time + TL-only DELETE
"""

from pathlib import Path

import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_repo(tmp_path: Path, prefix: str, agent_names: list[str]) -> Path:
    """Build a fake repo with files at each known owner level + memory dirs.

    Word counts are sized FAR above each category's ceiling so the tests don't
    silently regress when a future DWB-327-style rebalance raises the caps.
    Token estimate is ``word_count * 1.3``; the rule is "make files 5-10× over
    cap" so even an aggressive cap raise still leaves status='over'.

    PM-owned + worker-owned playbook/rules files are written too so over-ceiling
    coverage isn't fragile to a cap change on a single category.
    """
    repo = tmp_path / "repo"
    # Root docs — way over any reasonable cap.
    _write(repo / "ARCHITECTURE.md", "word " * 10000)                          # ~13000 tok, cap 4000
    _write(repo / "HANDOFF.md", "word " * 5000)                                # ~6500 tok, cap 1500
    # Agent definitions — assert against any reasonable agent_def ceiling.
    _write(repo / ".claude" / "agents" / "backend-worker.md", "word " * 5000)  # ~6500 tok, cap 1500
    _write(repo / ".claude" / "agents" / "pm.md", "word " * 5000)              # ~6500 tok
    _write(repo / ".claude" / "agents" / "worker.md", "word " * 5000)          # ~6500 tok
    # Playbooks (cap 2500) — sized firmly over.
    _write(repo / ".claude" / "worker_playbook.md", "word " * 5000)            # ~6500 tok, cap 2500
    _write(repo / ".claude" / "pm_playbook.md", "word " * 5000)                # ~6500 tok, cap 2500
    # Project rules (cap 1000) — over.
    _write(repo / ".claude" / "project_rules_pm.md", "word " * 5000)           # ~6500 tok, cap 1000
    _write(repo / ".claude" / "project_rules_worker.md", "word " * 5000)       # ~6500 tok, cap 1000
    # Memory dirs
    for name in agent_names:
        mem = repo / ".claude" / "agents" / "memory" / prefix / name
        _write(mem / "identity.md", "word " * 100)
        _write(mem / "scratchpad.md", "word " * 5000)  # ~6500 tok, cap 2000
        _write(mem / "lessons.md", "")
        _write(mem / "recent_sessions.md", "")
    return repo


def _override_payload(
    client, project_id: int, agent_id: int, sprint_id: int, notes=None
) -> dict:
    """Build a POST body that satisfies DWB-328 trim-or-override enforcement.

    Fetches consolidation-status, finds the named agent, and emits a reason
    for every over-ceiling file they own. Use in tests that just want a clean
    201 ack — for tests of the enforcement itself, build the body by hand.
    """
    status = client.get(
        f"/api/projects/{project_id}/consolidation-status",
        params={"sprint_id": sprint_id},
    ).json()
    block = next(a for a in status["agents"] if a["agent_id"] == agent_id)
    over_files = [f for f in block["owned_over_ceiling_files"] if f["status"] == "over"]
    overrides = {f["name"]: f"test override for {f['name']}" for f in over_files}
    return {"sprint_id": sprint_id, "notes": notes, "overrides": overrides}


def _ack(client, project_id: int, agent_id: int, sprint_id: int, notes=None):
    """POST an ack with auto-built overrides. Returns the raw response."""
    payload = _override_payload(client, project_id, agent_id, sprint_id, notes)
    return client.post(f"/api/agents/{agent_id}/consolidate-complete", json=payload)


@pytest.fixture
def gate_ctx(client, make_project, make_epic, make_sprint, tmp_path):
    """A project + sprint + repo + three active agents, gate ON, all participants.

    Each agent is assigned a ticket in the sprint so DWB-326 participant
    filtering counts them. Tests that want to verify non-participant behavior
    create extra agents directly.
    """
    prefix = "CSG"
    repo = _make_repo(tmp_path, prefix, agent_names=["Archie", "Mona", "Barry"])
    # Disable doc gates so the consolidation gate is the one being exercised.
    project = make_project(
        prefix=prefix,
        repo_path=str(repo),
        force_consolidation=True,
        force_handoff_md=False,
    )
    epic = make_epic(project_id=project["id"])
    sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], sprint_number=1)
    agents = {}
    for name, role in (("Archie", "team-lead"), ("Mona", "pm"), ("Barry", "backend-worker")):
        a = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": name,
            "role": role,
            "api_key": f"csg-{name}-{project['id']}",
        }).json()
        agents[name] = a
        # DWB-326: give each agent a participation signal via an assigned ticket.
        client.post("/api/tickets", json={
            "project_id": project["id"],
            "sprint_id": sprint["id"],
            "epic_id": epic["id"],
            "ticket_number": len(agents),
            "ticket_key": f"{prefix}-{len(agents):03d}",
            "title": f"{name} sprint participation marker",
            "assigned_agent_id": a["id"],
        })
    return {"project": project, "epic": epic, "sprint": sprint, "agents": agents}


# ---------------------------------------------------------------------------
# POST /api/agents/{id}/consolidate-complete
# ---------------------------------------------------------------------------

class TestAckEndpoint:
    def test_happy_path_returns_201(self, client, gate_ctx):
        agent = gate_ctx["agents"]["Archie"]
        payload = _override_payload(
            client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"],
            notes="trimmed CLAUDE.md",
        )
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["agent_id"] == agent["id"]
        assert body["sprint_id"] == gate_ctx["sprint"]["id"]
        assert body["notes"] == "trimmed CLAUDE.md"
        assert body["acked_at"]

    def test_double_ack_returns_409(self, client, gate_ctx):
        agent = gate_ctx["agents"]["Mona"]
        r1 = _ack(client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"])
        assert r1.status_code == 201
        # Second ack with the same overrides → unique constraint hit
        r2 = _ack(client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"])
        assert r2.status_code == 409
        assert "already acked" in r2.json()["detail"].lower()

    def test_inactive_agent_returns_400(self, client, gate_ctx):
        agent = gate_ctx["agents"]["Barry"]
        r = client.patch(f"/api/agents/{agent['id']}", json={"is_active": False})
        assert r.status_code == 200
        r2 = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": gate_ctx["sprint"]["id"],
            "notes": None,
        })
        assert r2.status_code == 400
        assert "not active" in r2.json()["detail"].lower()

    def test_wrong_project_returns_400(self, client, gate_ctx, make_project, make_sprint, make_epic):
        # Sprint belongs to a different project than the agent
        other_proj = make_project(prefix="OTH1")
        other_epic = make_epic(project_id=other_proj["id"])
        other_sprint = make_sprint(
            project_id=other_proj["id"], epic_id=other_epic["id"], sprint_number=1,
        )
        agent = gate_ctx["agents"]["Archie"]  # project = CSG
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": other_sprint["id"],
            "notes": None,
        })
        assert r.status_code == 400
        assert "project" in r.json()["detail"].lower()

    def test_missing_sprint_returns_404(self, client, gate_ctx):
        agent = gate_ctx["agents"]["Archie"]
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": 999999,
            "notes": None,
        })
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/consolidation-status
# ---------------------------------------------------------------------------

class TestConsolidationStatus:
    def test_shape(self, client, gate_ctx):
        r = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sprint_id"] == gate_ctx["sprint"]["id"]
        assert body["force_consolidation"] is True
        assert body["gate_satisfied"] is False  # nobody has acked
        assert {a["name"] for a in body["agents"]} == {"Archie", "Mona", "Barry"}
        for a in body["agents"]:
            assert a["acked"] is False
            assert a["acked_at"] is None
            assert isinstance(a["owned_over_ceiling_files"], list)

    def test_owner_mapping_tl_owns_root_docs(self, client, gate_ctx):
        body = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        archie = next(a for a in body["agents"] if a["name"] == "Archie")
        names = {f["name"] for f in archie["owned_over_ceiling_files"]}
        assert "ARCHITECTURE.md" in names
        assert "HANDOFF.md" in names

    def test_playbooks_not_owned_by_anyone(self, client, gate_ctx):
        """DWB-397: shipped DWB doctrine is advisory, never owned/gated.

        Playbooks (and agent defs) must not appear under ANY agent's
        owned_over_ceiling_files even though the fixture writes them far over
        ceiling.
        """
        body = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        exempt = {".claude/pm_playbook.md", ".claude/worker_playbook.md"}
        for agent in body["agents"]:
            names = {f["name"] for f in agent["owned_over_ceiling_files"]}
            assert exempt.isdisjoint(names), (
                f"{agent['name']} should not own any shipped playbook: "
                f"{names & exempt}"
            )

    def test_project_rules_owned_by_team_lead_only(self, client, gate_ctx):
        """DWB-399: project_rules are budgeted + TL-editable, so they gate
        against the team-lead ONLY. Workers/pm must not be blocked on a file
        only the TL can edit (that was the DWB-397 bug)."""
        body = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        rules = {".claude/project_rules_pm.md", ".claude/project_rules_worker.md"}

        archie = next(a for a in body["agents"] if a["name"] == "Archie")  # TL
        archie_names = {f["name"] for f in archie["owned_over_ceiling_files"]}
        assert rules <= archie_names, (
            f"team-lead should own all project_rules: missing {rules - archie_names}"
        )

        for name in ("Mona", "Barry"):  # pm, backend-worker
            block = next(a for a in body["agents"] if a["name"] == name)
            names = {f["name"] for f in block["owned_over_ceiling_files"]}
            assert rules.isdisjoint(names), (
                f"{name} must not own project_rules (TL-only): {names & rules}"
            )

    def test_owner_mapping_memory_files_belong_to_agent(self, client, gate_ctx):
        body = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        archie = next(a for a in body["agents"] if a["name"] == "Archie")
        archie_files = {f["name"] for f in archie["owned_over_ceiling_files"]}
        assert any(n.startswith("memory/Archie/") for n in archie_files)
        # Archie should not see Barry's memory
        assert not any(n.startswith("memory/Barry/") for n in archie_files)

    def test_after_ack_gate_marks_agent_acked(self, client, gate_ctx):
        agent = gate_ctx["agents"]["Archie"]
        _ack(client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"], notes="done")
        body = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        archie = next(a for a in body["agents"] if a["name"] == "Archie")
        assert archie["acked"] is True
        assert archie["acked_at"] is not None
        # Still not fully satisfied — Mona + Barry haven't acked
        assert body["gate_satisfied"] is False

    def test_all_acked_makes_gate_satisfied(self, client, gate_ctx):
        for name in ("Archie", "Mona", "Barry"):
            agent = gate_ctx["agents"][name]
            r = _ack(client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"])
            assert r.status_code == 201
        body = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        assert body["gate_satisfied"] is True


# ---------------------------------------------------------------------------
# Sprint-close gate enforcement
# ---------------------------------------------------------------------------

class TestSprintCloseGate:
    def test_close_blocked_when_gate_on_and_not_acked(self, client, gate_ctx):
        r = client.patch(
            f"/api/sprints/{gate_ctx['sprint']['id']}",
            json={"status": "completed"},
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "consolidation gate failed" in detail
        assert "3 of 3" in detail

    def test_close_blocked_with_partial_acks(self, client, gate_ctx):
        # Only Archie acks
        archie = gate_ctx["agents"]["Archie"]
        _ack(client, gate_ctx["project"]["id"], archie["id"], gate_ctx["sprint"]["id"])
        r = client.patch(
            f"/api/sprints/{gate_ctx['sprint']['id']}",
            json={"status": "completed"},
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "2 of 3" in detail
        # The unacked names are Mona + Barry
        assert "Mona" in detail
        assert "Barry" in detail

    def test_close_passes_when_all_acked(self, client, gate_ctx):
        for name in ("Archie", "Mona", "Barry"):
            agent = gate_ctx["agents"][name]
            _ack(client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"])
        r = client.patch(
            f"/api/sprints/{gate_ctx['sprint']['id']}",
            json={"status": "completed"},
        )
        # No consolidation block. Other doc gates may still fire — but
        # specifically the consolidation message must NOT be in any error.
        if r.status_code == 400:
            assert "consolidation gate failed" not in r.json()["detail"]
        else:
            assert r.status_code == 200

    def test_close_ignores_gate_when_toggle_off(
        self, client, make_project, make_epic, make_sprint, tmp_path
    ):
        prefix = "CSGOFF"
        repo = _make_repo(tmp_path, prefix, agent_names=["Solo"])
        # Disable several doc gates so they don't interfere with this test —
        # we only care that consolidation does NOT block when off.
        project = make_project(
            prefix=prefix,
            repo_path=str(repo),
            force_consolidation=False,
            force_handoff_md=False,
        )
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], sprint_number=1)
        client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Solo",
            "role": "backend-worker",
            "api_key": f"csgoff-solo-{project['id']}",
        })
        # No ack posted; toggle off → should close without consolidation error
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        if r.status_code != 200:
            assert "consolidation gate failed" not in r.json()["detail"]

    def test_full_canary_enable_block_ack_pass(self, client, gate_ctx):
        """DWB-322 canary: gate enabled → close blocked with named misses →
        every agent acks → close succeeds. Walks the whole regression flow in
        one function so a single failing assert pinpoints the broken step.
        """
        sprint_id = gate_ctx["sprint"]["id"]

        # 1. Gate is on (factory sets force_consolidation=True). Try to close — must fail.
        r = client.patch(f"/api/sprints/{sprint_id}", json={"status": "completed"})
        assert r.status_code == 400, "gate should block close when nobody has acked"
        detail = r.json()["detail"]
        assert "consolidation gate failed" in detail
        # All three names appear in the unacked list
        for name in ("Archie", "Mona", "Barry"):
            assert name in detail, f"{name} missing from unacked list: {detail}"

        # 2. Each agent posts an ack — all 201 (DWB-328 overrides supplied by helper).
        for name in ("Archie", "Mona", "Barry"):
            agent_id = gate_ctx["agents"][name]["id"]
            r = _ack(
                client, gate_ctx["project"]["id"], agent_id, sprint_id,
                notes=f"{name} consolidated",
            )
            assert r.status_code == 201, f"{name} ack failed: {r.text}"

        # 3. Close again — consolidation must NOT block (other doc gates may
        # still surface; we only assert the consolidation message isn't there).
        r = client.patch(f"/api/sprints/{sprint_id}", json={"status": "completed"})
        if r.status_code == 400:
            assert "consolidation gate failed" not in r.json()["detail"]
        else:
            assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# DWB-328 — trim-or-override enforcement on the ack endpoint
# ---------------------------------------------------------------------------


class TestOverCeilingEnforcement:
    """Ack must refuse over-ceiling owned files unless overridden per-file."""

    def test_ack_with_no_overrides_refused(self, client, gate_ctx):
        """Agent owns over-ceiling files and supplies no overrides → 400 with violations."""
        agent = gate_ctx["agents"]["Barry"]
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": gate_ctx["sprint"]["id"],
            "notes": None,
        })
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "over_ceiling_files_must_be_trimmed_or_overridden"
        # DWB-397/399: a worker owns neither playbooks (exempt) nor project_rules
        # (TL-only). The only over-ceiling file Barry still OWNS is his own
        # memory/scratchpad.
        names = {v["file"] for v in detail["violations"]}
        assert any(n.startswith("memory/Barry/") for n in names)
        # Shipped playbook + TL-only project_rules must NOT appear for a worker.
        assert ".claude/worker_playbook.md" not in names
        assert ".claude/project_rules_worker.md" not in names
        for v in detail["violations"]:
            assert isinstance(v["tokens"], int) and v["tokens"] > v["ceiling"]
            assert isinstance(v["ceiling"], int)

    def test_tl_ack_blocked_by_over_ceiling_project_rules(self, client, gate_ctx):
        """DWB-399: the team-lead DOES gate on over-ceiling project_rules
        (TL-editable). They must appear in the TL's ack violations, while
        playbooks (exempt) must not."""
        archie = gate_ctx["agents"]["Archie"]
        r = client.post(f"/api/agents/{archie['id']}/consolidate-complete", json={
            "sprint_id": gate_ctx["sprint"]["id"],
            "notes": None,
        })
        assert r.status_code == 400, r.text
        names = {v["file"] for v in r.json()["detail"]["violations"]}
        assert ".claude/project_rules_pm.md" in names
        assert ".claude/project_rules_worker.md" in names
        # Playbooks stay exempt even for the TL.
        assert ".claude/team_lead_playbook.md" not in names
        assert ".claude/pm_playbook.md" not in names

    def test_ack_with_full_memory_override_succeeds(self, client, gate_ctx):
        """DWB-397: with playbooks exempt, justifying only the owned memory file
        is enough to ack — the agent no longer has to override docs they can't edit."""
        agent = gate_ctx["agents"]["Barry"]
        status = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        barry = next(a for a in status["agents"] if a["agent_id"] == agent["id"])
        over = [f for f in barry["owned_over_ceiling_files"] if f["status"] == "over"]
        # Only memory files remain owned + over for a worker now.
        assert over, "Barry should still own at least his over-ceiling memory file"
        assert all(f["name"].startswith("memory/") for f in over)
        overrides = {f["name"]: "load-bearing in-flight notes" for f in over}
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": gate_ctx["sprint"]["id"],
            "overrides": overrides,
        })
        assert r.status_code == 201, r.text

    def test_ack_with_empty_reason_refused(self, client, gate_ctx):
        """A whitespace-only reason is not a real override → still refused for that file."""
        agent = gate_ctx["agents"]["Archie"]
        status = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        archie_block = next(a for a in status["agents"] if a["agent_id"] == agent["id"])
        # All real reasons except one whitespace string
        overrides = {}
        target_file = None
        for f in archie_block["owned_over_ceiling_files"]:
            if f["status"] != "over":
                continue
            if target_file is None:
                target_file = f["name"]
                overrides[f["name"]] = "   "  # whitespace-only
            else:
                overrides[f["name"]] = "real reason"

        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": gate_ctx["sprint"]["id"],
            "overrides": overrides,
        })
        assert r.status_code == 400, r.text
        violation_names = {v["file"] for v in r.json()["detail"]["violations"]}
        assert target_file in violation_names

    def test_ack_with_full_overrides_succeeds_and_stores(self, client, gate_ctx):
        """Every over-ceiling file justified → 201, override map persisted."""
        agent = gate_ctx["agents"]["Mona"]
        payload = _override_payload(
            client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"],
            notes="reviewed PM files",
        )
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        # Stored override map matches what we sent
        assert body["overrides"] == payload["overrides"]
        assert body["notes"] == "reviewed PM files"

    def test_status_response_includes_overrides_after_ack(self, client, gate_ctx):
        """GET /consolidation-status surfaces the stored override map per agent."""
        agent = gate_ctx["agents"]["Mona"]
        r = _ack(client, gate_ctx["project"]["id"], agent["id"], gate_ctx["sprint"]["id"])
        sent_overrides = r.json()["overrides"]
        status = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        mona_block = next(a for a in status["agents"] if a["agent_id"] == agent["id"])
        assert mona_block["overrides"] == sent_overrides
        # Unacked agents still report overrides as None
        archie_block = next(a for a in status["agents"] if a["name"] == "Archie")
        assert archie_block["overrides"] is None

    def test_clean_project_no_over_ceiling_acks_without_overrides(
        self, client, make_project, make_epic, make_sprint, tmp_path
    ):
        """Project with no over-ceiling owned files: empty body still gets 201."""
        prefix = "CLN"
        repo = tmp_path / "clean_repo"
        repo.mkdir()
        # Tiny files — all 'ok' status
        (repo / "ARCHITECTURE.md").write_text("ok\n")
        project = make_project(
            prefix=prefix,
            repo_path=str(repo),
            force_consolidation=True,
            force_handoff_md=False,
        )
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], sprint_number=1)
        agent = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Solo",
            "role": "backend-worker",
            "api_key": f"cln-solo-{project['id']}",
        }).json()
        r = client.post(f"/api/agents/{agent['id']}/consolidate-complete", json={
            "sprint_id": sprint["id"],
        })
        assert r.status_code == 201, r.text
        assert r.json()["overrides"] is None


class TestTLDeleteAck:
    """DELETE /api/agents/:id/consolidate-complete/:sprint_id — TL only."""

    def _tl_agent(self, client, gate_ctx):
        # gate_ctx creates Archie as the team-lead in this project
        return gate_ctx["agents"]["Archie"]

    def test_tl_can_delete_ack(self, client, gate_ctx):
        """Team-lead caller can reject an ack and force re-trim/re-justify."""
        target = gate_ctx["agents"]["Barry"]
        _ack(client, gate_ctx["project"]["id"], target["id"], gate_ctx["sprint"]["id"])

        tl = self._tl_agent(client, gate_ctx)
        r = client.delete(
            f"/api/agents/{target['id']}/consolidate-complete/{gate_ctx['sprint']['id']}",
            headers={"X-Agent-ID": str(tl["id"])},
        )
        assert r.status_code == 204, r.text

        # Status now shows Barry unacked again
        status = client.get(
            f"/api/projects/{gate_ctx['project']['id']}/consolidation-status",
            params={"sprint_id": gate_ctx["sprint"]["id"]},
        ).json()
        barry_block = next(a for a in status["agents"] if a["agent_id"] == target["id"])
        assert barry_block["acked"] is False

    def test_non_tl_caller_forbidden(self, client, gate_ctx):
        target = gate_ctx["agents"]["Barry"]
        _ack(client, gate_ctx["project"]["id"], target["id"], gate_ctx["sprint"]["id"])

        # PM agent tries to delete — must be refused
        pm = gate_ctx["agents"]["Mona"]
        r = client.delete(
            f"/api/agents/{target['id']}/consolidate-complete/{gate_ctx['sprint']['id']}",
            headers={"X-Agent-ID": str(pm["id"])},
        )
        assert r.status_code == 403, r.text

    def test_missing_x_agent_id_unauthorized(self, client, gate_ctx):
        target = gate_ctx["agents"]["Barry"]
        _ack(client, gate_ctx["project"]["id"], target["id"], gate_ctx["sprint"]["id"])

        r = client.delete(
            f"/api/agents/{target['id']}/consolidate-complete/{gate_ctx['sprint']['id']}",
        )
        assert r.status_code == 401, r.text

    def test_unknown_caller_unauthorized(self, client, gate_ctx):
        target = gate_ctx["agents"]["Barry"]
        _ack(client, gate_ctx["project"]["id"], target["id"], gate_ctx["sprint"]["id"])

        r = client.delete(
            f"/api/agents/{target['id']}/consolidate-complete/{gate_ctx['sprint']['id']}",
            headers={"X-Agent-ID": "999999"},
        )
        assert r.status_code == 401, r.text

    def test_delete_missing_ack_returns_404(self, client, gate_ctx):
        # Nobody has acked yet
        target = gate_ctx["agents"]["Barry"]
        tl = self._tl_agent(client, gate_ctx)
        r = client.delete(
            f"/api/agents/{target['id']}/consolidate-complete/{gate_ctx['sprint']['id']}",
            headers={"X-Agent-ID": str(tl["id"])},
        )
        assert r.status_code == 404, r.text

    def test_after_delete_sprint_close_re_blocks(self, client, gate_ctx):
        """All-acked → close passes; TL deletes one → close re-blocks naming that agent."""
        sprint_id = gate_ctx["sprint"]["id"]
        for name in ("Archie", "Mona", "Barry"):
            agent = gate_ctx["agents"][name]
            _ack(client, gate_ctx["project"]["id"], agent["id"], sprint_id)

        # TL invalidates Barry's ack
        tl = self._tl_agent(client, gate_ctx)
        barry = gate_ctx["agents"]["Barry"]
        client.delete(
            f"/api/agents/{barry['id']}/consolidate-complete/{sprint_id}",
            headers={"X-Agent-ID": str(tl["id"])},
        )

        # Close blocks again, naming Barry
        r = client.patch(f"/api/sprints/{sprint_id}", json={"status": "completed"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "consolidation gate failed" in detail
        assert "Barry" in detail


class TestParticipantScoping:
    """DWB-326: ack required only from sprint participants, not all active agents."""

    def test_non_participants_excluded_from_status(
        self, client, make_project, make_epic, make_sprint, tmp_path
    ):
        """3 participants + 3 active non-participants → status lists 3 agents."""
        prefix = "PRT"
        repo = _make_repo(tmp_path, prefix, agent_names=["Worker1", "Worker2", "Worker3"])
        project = make_project(
            prefix=prefix,
            repo_path=str(repo),
            force_consolidation=True,
            force_handoff_md=False,
        )
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], sprint_number=1)

        # 3 participants — each gets an assigned ticket.
        participants = {}
        for i, name in enumerate(("Worker1", "Worker2", "Worker3"), start=1):
            a = client.post("/api/agents", json={
                "project_id": project["id"],
                "name": name,
                "role": "backend-worker",
                "api_key": f"prt-{name}-{project['id']}",
            }).json()
            participants[name] = a
            client.post("/api/tickets", json={
                "project_id": project["id"],
                "sprint_id": sprint["id"],
                "epic_id": epic["id"],
                "ticket_number": i,
                "ticket_key": f"{prefix}-{i:03d}",
                "title": f"{name} ticket",
                "assigned_agent_id": a["id"],
            })

        # 3 non-participants — active but no sprint signal.
        for i, name in enumerate(("Bystander1", "Bystander2", "Bystander3"), start=1):
            client.post("/api/agents", json={
                "project_id": project["id"],
                "name": name,
                "role": "frontend-worker",
                "api_key": f"prt-by-{name}-{project['id']}",
            })

        status = client.get(
            f"/api/projects/{project['id']}/consolidation-status",
            params={"sprint_id": sprint["id"]},
        ).json()
        names = {a["name"] for a in status["agents"]}
        assert names == {"Worker1", "Worker2", "Worker3"}
        assert "Bystander1" not in names
        assert sorted(status["participants"]) == sorted(p["id"] for p in participants.values())

    def test_close_only_requires_participant_acks(
        self, client, make_project, make_epic, make_sprint, tmp_path
    ):
        """Bystanders don't need to ack — once participants ack, close passes."""
        prefix = "PRTC"
        repo = _make_repo(tmp_path, prefix, agent_names=["Solo"])
        project = make_project(
            prefix=prefix,
            repo_path=str(repo),
            force_consolidation=True,
            force_handoff_md=False,
        )
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], sprint_number=1)

        # 1 participant
        solo = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Solo",
            "role": "backend-worker",
            "api_key": f"prtc-solo-{project['id']}",
        }).json()
        client.post("/api/tickets", json={
            "project_id": project["id"],
            "sprint_id": sprint["id"],
            "epic_id": epic["id"],
            "ticket_number": 1,
            "ticket_key": f"{prefix}-001",
            "title": "Solo ticket",
            "assigned_agent_id": solo["id"],
        })

        # 2 bystanders
        for name in ("ByA", "ByB"):
            client.post("/api/agents", json={
                "project_id": project["id"],
                "name": name,
                "role": "frontend-worker",
                "api_key": f"prtc-{name}-{project['id']}",
            })

        # Close before Solo acks → blocked, naming Solo only (not bystanders).
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "1 of 1" in detail
        assert "Solo" in detail
        assert "ByA" not in detail
        assert "ByB" not in detail

        # Solo acks; nobody else needs to.
        _ack(client, project["id"], solo["id"], sprint["id"])
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        if r.status_code == 400:
            assert "consolidation gate failed" not in r.json()["detail"]
        else:
            assert r.status_code == 200

    def test_consolidate_complete_path_maps_to_dedicated_entity_type(self):
        """DWB-329 middleware leg: _parse_entity_type must return
        'agent_consolidation_ack' for the consolidate-complete subpaths so
        participants_for_sprint can filter ack-only signals out. Direct unit
        test on the path-parsing function because the consolidate-complete
        response schema lacks project_id, so the middleware short-circuits
        before emitting a row today - the tagging is still load-bearing for
        any future path (audit subscription, manual log insert) that takes
        the same URL through the parser.
        """
        from app.middleware.activity_logger import _parse_entity_type

        # POST /api/agents/{id}/consolidate-complete
        assert (
            _parse_entity_type("/api/agents/14/consolidate-complete")
            == "agent_consolidation_ack"
        )
        # DELETE /api/agents/{id}/consolidate-complete/{sprint_id}
        assert (
            _parse_entity_type("/api/agents/14/consolidate-complete/27")
            == "agent_consolidation_ack"
        )
        # Trailing slash variant
        assert (
            _parse_entity_type("/api/agents/14/consolidate-complete/")
            == "agent_consolidation_ack"
        )
        # POST /api/agents itself stays as the generic 'agent' type so agent
        # create/update activity is still attributable.
        assert _parse_entity_type("/api/agents") == "agent"
        assert _parse_entity_type("/api/agents/14") == "agent"
        assert (
            _parse_entity_type("/api/agents/14/memory/append") == "agent"
        )
        # Tickets / sprints unaffected.
        assert _parse_entity_type("/api/tickets/899") == "ticket"
        assert _parse_entity_type("/api/sprints/107") == "sprint"

    def test_ack_only_activity_does_not_make_agent_participant(
        self, client, make_project, make_epic, make_sprint, db_session
    ):
        """DWB-329 service leg: an agent whose ONLY in-window activity is a
        consolidate-complete ack must NOT be counted as a sprint participant.

        Reproduces the S62/S63 bug: Pam acked S62 inside S63's window and
        got pulled into S63's required-ack set despite doing zero S63 work.

        Uses a direct DB insert for the activity_log row so the test doesn't
        couple to the consolidate-complete gate's over-ceiling refusal path -
        the middleware tagging is covered in the sibling test above.
        """
        from datetime import datetime, time, timedelta

        from app.models.activity_log import ActivityLog
        from app.services.agent_consolidation import participants_for_sprint
        from app.models.sprint import Sprint

        project = make_project(prefix="PRT329S")
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(
            project_id=project["id"], epic_id=epic["id"], sprint_number=1,
            start_date="2026-06-01", end_date="2026-06-07",
        )
        sprint_row = db_session.get(Sprint, sprint["id"])
        assert sprint_row.start_date is not None

        worker = client.post("/api/agents", json={
            "project_id": project["id"], "name": "RealWorker",
            "role": "backend-worker", "api_key": f"prt329s-w-{project['id']}",
        }).json()
        pamlike = client.post("/api/agents", json={
            "project_id": project["id"], "name": "AckOnly",
            "role": "pm", "api_key": f"prt329s-p-{project['id']}",
        }).json()

        # Real worker has a ticket on this sprint -> legitimate participant.
        client.post("/api/tickets", json={
            "project_id": project["id"],
            "sprint_id": sprint["id"],
            "epic_id": epic["id"],
            "ticket_number": 1,
            "ticket_key": "PRT329S-001",
            "title": "Real work",
            "assigned_agent_id": worker["id"],
        })

        # Drop two activity_log rows inside the sprint window, both for
        # PamLike: one for a (notional) prior-sprint ack, one for a misc
        # admin action with the generic 'agent' entity_type. The ack row
        # MUST NOT count toward participation; the generic 'agent' row WILL.
        window_ts = datetime.combine(sprint_row.start_date, time(12, 0, 0))
        # Build a sprint window timestamp 1 day into the sprint.
        window_ts = window_ts + timedelta(days=1)
        db_session.add(ActivityLog(
            project_id=project["id"],
            agent_id=pamlike["id"],
            entity_type="agent_consolidation_ack",
            entity_id=999,
            action="created",
            details=None,
            created_at=window_ts,
        ))
        db_session.commit()

        participants = participants_for_sprint(db_session, sprint_row)
        assert worker["id"] in participants
        assert pamlike["id"] not in participants, (
            "agent_consolidation_ack rows must not be counted as "
            "sprint-participation activity"
        )

        # Sanity: a non-ack activity_log row in the same window DOES count.
        # This guards against an over-broad filter (e.g. excluding all
        # entity_type='agent' rows would have caught both real and admin
        # signals).
        db_session.add(ActivityLog(
            project_id=project["id"],
            agent_id=pamlike["id"],
            entity_type="agent",  # different entity_type, still counts
            entity_id=998,
            action="updated",
            details=None,
            created_at=window_ts + timedelta(seconds=1),
        ))
        db_session.commit()

        participants = participants_for_sprint(db_session, sprint_row)
        assert pamlike["id"] in participants, (
            "non-ack activity_log rows must still produce participation"
        )

    def test_comment_author_counts_as_participant(
        self, client, make_project, make_epic, make_sprint, tmp_path
    ):
        """An agent who only commented on a sprint ticket (no assignment) participates."""
        prefix = "PRTM"
        repo = _make_repo(tmp_path, prefix, agent_names=["Assignee", "Commenter"])
        project = make_project(
            prefix=prefix,
            repo_path=str(repo),
            force_consolidation=True,
            force_handoff_md=False,
        )
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], sprint_number=1)

        assignee = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Assignee",
            "role": "backend-worker", "api_key": f"prtm-a-{project['id']}",
        }).json()
        commenter = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Commenter",
            "role": "frontend-worker", "api_key": f"prtm-c-{project['id']}",
        }).json()
        # One ticket assigned to Assignee
        ticket = client.post("/api/tickets", json={
            "project_id": project["id"],
            "sprint_id": sprint["id"],
            "epic_id": epic["id"],
            "ticket_number": 1,
            "ticket_key": f"{prefix}-001",
            "title": "Ticket",
            "assigned_agent_id": assignee["id"],
        }).json()
        # Commenter posts a comment on it
        client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": commenter["id"],
            "body": "looked at this",
        })

        status = client.get(
            f"/api/projects/{project['id']}/consolidation-status",
            params={"sprint_id": sprint["id"]},
        ).json()
        names = {a["name"] for a in status["agents"]}
        assert names == {"Assignee", "Commenter"}



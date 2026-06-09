# Path: tests/test_jira_disabled_gates.py
# File: test_jira_disabled_gates.py
# Created: 2026-06-09
# Purpose: Non-Jira project visibility + hard gates (DWB-332)
# Caller: pytest
# Callees: app.routers.agents (identify), app.routers.tickets (POST/PATCH), app.routers.playbooks (deploy)
# Data In: per-test factory fixtures, tmp_path for repo_path
# Data Out: Assertions on identify response shape, ticket 400 gate, deployed playbook content
# Last Modified: 2026-06-09

"""Coverage for DWB-332:

1. POST /api/agents/identify response includes jira_enabled (bool) reflecting
   project.jira_base_url presence.
2. POST /api/tickets refuses jira_issue_key when project is not Jira-linked.
3. PATCH /api/tickets/{id} refuses jira_issue_key when project is not
   Jira-linked.
4. POST /api/projects/{id}/deploy-playbooks scrubs jira-only blocks and
   prepends a banner on non-Jira targets; preserves them on Jira targets.

The ticket gate uses the same error shape as DWB-333's sprint_id gate —
{error: <code>, message: <human>, field: <name>}.
"""

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. identify response jira_enabled
# ---------------------------------------------------------------------------


class TestIdentifyJiraEnabled:
    def _make_project_agent(
        self, client, *, jira_base_url, prefix, tmp_path
    ):
        # tmp_path gives the project a real repo_path so scaffold paths work
        # even though identify itself doesn't write to disk.
        project = client.post(
            "/api/projects",
            json={
                "prefix": prefix,
                "name": f"{prefix} Test",
                "repo_path": str(tmp_path),
                "jira_base_url": jira_base_url,
            },
        ).json()
        agent = client.post(
            "/api/agents",
            json={
                "project_id": project["id"],
                "name": f"Worker_{prefix}",
                "role": "backend-worker",
                "api_key": f"key-{prefix}",
            },
        ).json()
        return project, agent

    def test_jira_enabled_true_when_jira_base_url_set(
        self, client, tmp_path
    ):
        project, agent = self._make_project_agent(
            client,
            jira_base_url="https://example.atlassian.net",
            prefix="JIRA1",
            tmp_path=tmp_path,
        )
        r = client.post(
            "/api/agents/identify",
            json={
                "role": "backend-worker",
                "name": f"Worker_{project['prefix']}",
                "project_prefix": project["prefix"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["jira_enabled"] is True

    def test_jira_enabled_false_when_jira_base_url_null(
        self, client, tmp_path
    ):
        project, agent = self._make_project_agent(
            client,
            jira_base_url=None,
            prefix="NJIRA",
            tmp_path=tmp_path,
        )
        r = client.post(
            "/api/agents/identify",
            json={
                "role": "backend-worker",
                "name": f"Worker_{project['prefix']}",
                "project_prefix": project["prefix"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["jira_enabled"] is False


# ---------------------------------------------------------------------------
# 2 + 3. Ticket gate — POST and PATCH refuse jira_issue_key on non-Jira project
# ---------------------------------------------------------------------------


class TestTicketGateJiraDisabled:
    def _make_non_jira_project_setup(self, client):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "NJ",
                "name": "Non-Jira",
                "jira_base_url": None,
            },
        ).json()
        epic = client.post(
            "/api/epics",
            json={"project_id": project["id"], "name": "Epic"},
        ).json()
        sprint = client.post(
            "/api/sprints",
            json={
                "project_id": project["id"],
                "epic_id": epic["id"],
                "sprint_number": 1,
                "status": "active",
            },
        ).json()
        return project, sprint

    def _make_jira_project_setup(self, client):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "JR",
                "name": "Jira",
                "jira_base_url": "https://example.atlassian.net",
            },
        ).json()
        epic = client.post(
            "/api/epics",
            json={"project_id": project["id"], "name": "Epic"},
        ).json()
        sprint = client.post(
            "/api/sprints",
            json={
                "project_id": project["id"],
                "epic_id": epic["id"],
                "sprint_number": 1,
                "status": "active",
            },
        ).json()
        return project, sprint

    def test_post_with_jira_key_on_non_jira_project_returns_400(
        self, client
    ):
        project, sprint = self._make_non_jira_project_setup(client)
        r = client.post(
            "/api/tickets",
            json={
                "project_id": project["id"],
                "sprint_id": sprint["id"],
                "ticket_number": 1,
                "ticket_key": "NJ-001",
                "title": "Blocked link",
                "jira_issue_key": "POR-9999",
            },
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", {})
        assert detail["error"] == "jira_disabled_for_project"
        assert detail["field"] == "jira_issue_key"
        assert detail["project_id"] == project["id"]

    def test_post_without_jira_key_on_non_jira_project_passes(
        self, client
    ):
        project, sprint = self._make_non_jira_project_setup(client)
        r = client.post(
            "/api/tickets",
            json={
                "project_id": project["id"],
                "sprint_id": sprint["id"],
                "ticket_number": 1,
                "ticket_key": "NJ-002",
                "title": "Local-only",
            },
        )
        assert r.status_code == 201, r.text

    def test_post_with_jira_key_on_jira_project_passes(self, client):
        project, sprint = self._make_jira_project_setup(client)
        r = client.post(
            "/api/tickets",
            json={
                "project_id": project["id"],
                "sprint_id": sprint["id"],
                "ticket_number": 1,
                "ticket_key": "JR-001",
                "title": "Linked",
                "jira_issue_key": "POR-1234",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["jira_issue_key"] == "POR-1234"

    def test_patch_with_jira_key_on_non_jira_project_returns_400(
        self, client
    ):
        project, sprint = self._make_non_jira_project_setup(client)
        ticket = client.post(
            "/api/tickets",
            json={
                "project_id": project["id"],
                "sprint_id": sprint["id"],
                "ticket_number": 1,
                "ticket_key": "NJ-003",
                "title": "Will try to link",
            },
        ).json()

        r = client.patch(
            f"/api/tickets/{ticket['id']}",
            json={"jira_issue_key": "POR-9999"},
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", {})
        assert detail["error"] == "jira_disabled_for_project"
        assert detail["field"] == "jira_issue_key"

        # Field stayed null — no partial write.
        after = client.get(f"/api/tickets/{ticket['id']}").json()
        assert after["jira_issue_key"] is None

    def test_patch_with_null_jira_key_on_non_jira_project_passes(
        self, client
    ):
        """Explicit null on jira_issue_key is a no-op clear (the field is
        nullable in the model). The gate must NOT trip on a null write."""
        project, sprint = self._make_non_jira_project_setup(client)
        ticket = client.post(
            "/api/tickets",
            json={
                "project_id": project["id"],
                "sprint_id": sprint["id"],
                "ticket_number": 1,
                "ticket_key": "NJ-004",
                "title": "Clear",
            },
        ).json()

        r = client.patch(
            f"/api/tickets/{ticket['id']}",
            json={"jira_issue_key": None},
        )
        assert r.status_code == 200, r.text

    def test_multi_project_isolation_on_ticket_gate(self, client):
        """Setting jira_issue_key on a Jira project must succeed even when a
        non-Jira project exists elsewhere with the same gate active."""
        non_jira_project, non_jira_sprint = self._make_non_jira_project_setup(
            client
        )
        jira_project, jira_sprint = self._make_jira_project_setup(client)

        # Non-Jira side refuses.
        r1 = client.post(
            "/api/tickets",
            json={
                "project_id": non_jira_project["id"],
                "sprint_id": non_jira_sprint["id"],
                "ticket_number": 1,
                "ticket_key": "NJ-X",
                "title": "Refused",
                "jira_issue_key": "POR-X",
            },
        )
        assert r1.status_code == 400

        # Jira side still works.
        r2 = client.post(
            "/api/tickets",
            json={
                "project_id": jira_project["id"],
                "sprint_id": jira_sprint["id"],
                "ticket_number": 1,
                "ticket_key": "JR-X",
                "title": "Allowed",
                "jira_issue_key": "POR-Y",
            },
        )
        assert r2.status_code == 201


# ---------------------------------------------------------------------------
# 4. Playbook deploy variant + banner
# ---------------------------------------------------------------------------


def _read_deployed(target_dir: Path, name: str) -> str:
    return (target_dir / name).read_text(encoding="utf-8")


class TestDeployPlaybooksJiraAware:
    def test_non_jira_deploy_scrubs_jira_only_block_and_keeps_alt(
        self, client, tmp_path
    ):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "NJDEP",
                "name": "Non-Jira Deploy",
                "repo_path": str(tmp_path),
                "jira_base_url": None,
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200, r.text
        target_dir = Path(r.json()["target_dir"])

        worker = _read_deployed(target_dir, "worker_playbook.md")
        # Jira-only content stripped — sentinel phrases from the source must
        # not appear in the deployed copy.
        assert "dwb2jira ticket transition POR-KEY" not in worker
        assert "Jira -> DWB status mapping" not in worker
        # Non-Jira alternative IS present.
        assert "Pick up -> work -> hand off (no Jira)" in worker
        assert "PATCH /api/tickets/{ticket_id}" in worker
        # Banner up top.
        assert worker.startswith(
            "> THIS PROJECT IS NOT LINKED TO JIRA."
        ) or "THIS PROJECT IS NOT LINKED TO JIRA" in worker.splitlines()[0]

    def test_jira_deploy_keeps_jira_block_and_drops_alt(
        self, client, tmp_path
    ):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "JDEP",
                "name": "Jira Deploy",
                "repo_path": str(tmp_path),
                "jira_base_url": "https://example.atlassian.net",
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200, r.text
        target_dir = Path(r.json()["target_dir"])

        worker = _read_deployed(target_dir, "worker_playbook.md")
        # Jira-only content present.
        assert "dwb2jira ticket transition POR-KEY" in worker
        # Non-Jira alternative stripped.
        assert "Pick up -> work -> hand off (no Jira)" not in worker
        # Banner NOT prepended.
        assert "THIS PROJECT IS NOT LINKED TO JIRA" not in worker

    def test_non_jira_deploy_creates_handoff_with_banner(
        self, client, tmp_path
    ):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "NJH",
                "name": "Non-Jira Handoff",
                "repo_path": str(tmp_path),
                "jira_base_url": None,
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200, r.text

        handoff = (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")
        assert "THIS PROJECT IS NOT LINKED TO JIRA" in handoff
        # HANDOFF.md is at the repo root, NOT under .claude/, so it's not
        # surfaced in the `deployed` list (whose entries are expected to
        # resolve under target_dir). File-presence check is the contract.

    def test_non_jira_deploy_does_not_overwrite_existing_handoff(
        self, client, tmp_path
    ):
        """User-authored HANDOFF.md content must NEVER be mutated by deploy
        — the banner-scaffold only fires when the file is absent."""
        existing_handoff = "# Existing handoff\n\nUser content here.\n"
        (tmp_path / "HANDOFF.md").write_text(existing_handoff)

        project = client.post(
            "/api/projects",
            json={
                "prefix": "NJHKP",
                "name": "Keep Handoff",
                "repo_path": str(tmp_path),
                "jira_base_url": None,
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200

        after = (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")
        assert after == existing_handoff

    def test_non_jira_deploy_prepends_banner_to_new_project_rules_files(
        self, client, tmp_path
    ):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "NJPR",
                "name": "Non-Jira Rules",
                "repo_path": str(tmp_path),
                "jira_base_url": None,
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200, r.text
        target_dir = Path(r.json()["target_dir"])

        for name in (
            "project_rules_worker.md",
            "project_rules_pm.md",
            "project_rules_team_lead.md",
        ):
            text = _read_deployed(target_dir, name)
            assert "THIS PROJECT IS NOT LINKED TO JIRA" in text, (
                f"banner missing from {name}"
            )

    def test_jira_deploy_does_not_prepend_banner_to_project_rules(
        self, client, tmp_path
    ):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "JPR",
                "name": "Jira Rules",
                "repo_path": str(tmp_path),
                "jira_base_url": "https://example.atlassian.net",
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 200, r.text
        target_dir = Path(r.json()["target_dir"])

        text = _read_deployed(target_dir, "project_rules_worker.md")
        assert "THIS PROJECT IS NOT LINKED TO JIRA" not in text

# Path:          tests/test_token_budget.py
# File:          test_token_budget.py
# Created:       2026-06-04
# Purpose:       Tests for GET /api/projects/:id/token-budget — root docs, agent defs, memory files
# Caller:        pytest
# Callees:       GET /api/projects/:id/token-budget
# Data In:       Temp repo dir with .claude/ + memory layout, factory-created project + agents
# Data Out:      Assertions on category/agent_name fields and inclusion of new docs/memory files
# Last Modified: 2026-06-19

"""Tests for the /api/projects/:id/token-budget endpoint.

Covers the round-2 extension that adds:
  - ARCHITECTURE.md / README.md / INITIAL.md to the root-docs scan
  - per-agent memory file scan under .dwb/memory/{prefix}/{name}/ (DWB-401)
  - `category` field on every entry
  - `agent_name` field (string for memory entries, null otherwise)
"""

from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _setup_repo(tmp_path: Path, prefix: str, agent_names: list[str]) -> Path:
    """Build a minimal repo layout that exercises every scan path."""
    repo = tmp_path / "repo"
    # Root-level docs
    _write(repo / "CLAUDE.md", "# Claude context\n" + "word " * 50)
    _write(repo / "ARCHITECTURE.md", "# Architecture\n" + "word " * 200)
    _write(repo / "README.md", "# Readme\n" + "word " * 100)
    _write(repo / "INITIAL.md", "# Initial\n" + "word " * 80)
    # Agent definition
    _write(repo / ".claude" / "agents" / "backend-worker.md", "# backend\n" + "word " * 60)
    # Playbook + project rules
    _write(repo / ".claude" / "worker_playbook.md", "# playbook\n" + "word " * 80)
    _write(repo / ".claude" / "project_rules_worker.md", "# rules\n" + "word " * 20)
    # Memory dirs for each agent. DWB-401: .dwb/memory/<prefix>/<name>/ with the
    # 2-file model (identity.md + the single free-form memory.md).
    for name in agent_names:
        mem = repo / ".dwb" / "memory" / prefix / name
        _write(mem / "identity.md", f"# identity {name}\n" + "word " * 40)
        _write(mem / "memory.md", f"# memory {name}\n" + "word " * 30)
    return repo


class TestTokenBudgetExtended:
    def test_endpoint_returns_200(self, client, make_project):
        # Brand-new project with repo_path set still needs a repo to scan
        proj = make_project(repo_path=str(Path(__file__).parent))
        r = client.get(f"/api/projects/{proj['id']}/token-budget")
        assert r.status_code == 200

    def test_root_docs_include_new_files(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "TST", agent_names=[])
        proj = make_project(prefix="TBX1", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()

        names = {f["name"] for f in data["files"]}
        assert "CLAUDE.md" in names
        assert "ARCHITECTURE.md" in names
        assert "README.md" in names
        assert "INITIAL.md" in names

    def test_every_entry_has_category(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "TST", agent_names=[])
        proj = make_project(prefix="TBX2", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()

        assert data["files"], "expected at least one file in scan"
        for entry in data["files"]:
            assert "category" in entry, f"missing category: {entry['name']}"
            assert isinstance(entry["category"], str)
            assert entry["category"]

    def test_new_doc_categories_are_set(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "TST", agent_names=[])
        proj = make_project(prefix="TBX3", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        by_name = {f["name"]: f for f in data["files"]}

        assert by_name["ARCHITECTURE.md"]["category"] == "architecture"
        assert by_name["README.md"]["category"] == "readme"
        assert by_name["INITIAL.md"]["category"] == "initial"

    def test_non_memory_entries_have_null_agent_name(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "TST", agent_names=[])
        proj = make_project(prefix="TBX4", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()

        for entry in data["files"]:
            assert entry["agent_name"] is None, (
                f"expected null agent_name on non-memory entry: {entry['name']}"
            )

    def test_memory_files_counted_for_active_agents(
        self, client, make_project, make_agent, tmp_path
    ):
        prefix = "TBX5"
        repo = _setup_repo(tmp_path, prefix, agent_names=["Barry", "Mona"])
        proj = make_project(prefix=prefix, repo_path=str(repo))
        make_agent(project_id=proj["id"], name="Barry", role="backend-worker")
        make_agent(project_id=proj["id"], name="Mona", role="pm")

        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        names = {f["name"] for f in data["files"]}

        # DWB-401: each agent contributes 2 memory files (identity + memory.md).
        for agent in ("Barry", "Mona"):
            assert f"memory/{agent}/identity.md" in names
            assert f"memory/{agent}/memory.md" in names
            assert f"memory/{agent}/scratchpad.md" not in names
            assert f"memory/{agent}/lessons.md" not in names
            assert f"memory/{agent}/recent_sessions.md" not in names

    def test_memory_entries_carry_agent_name_and_category(
        self, client, make_project, make_agent, tmp_path
    ):
        prefix = "TBX6"
        repo = _setup_repo(tmp_path, prefix, agent_names=["Barry"])
        proj = make_project(prefix=prefix, repo_path=str(repo))
        make_agent(project_id=proj["id"], name="Barry", role="backend-worker")

        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        memory_entries = [f for f in data["files"] if f["name"].startswith("memory/")]
        assert memory_entries, "expected memory entries for active agent Barry"

        category_by_file = {
            "memory/Barry/identity.md": "memory_identity",
            "memory/Barry/memory.md": "memory_main",
        }
        by_name = {e["name"]: e for e in memory_entries}
        for name, expected_category in category_by_file.items():
            assert name in by_name, f"missing {name}"
            assert by_name[name]["agent_name"] == "Barry"
            assert by_name[name]["category"] == expected_category

    def test_inactive_agents_excluded(
        self, client, make_project, make_agent, tmp_path
    ):
        prefix = "TBX7"
        repo = _setup_repo(tmp_path, prefix, agent_names=["Ghost"])
        proj = make_project(prefix=prefix, repo_path=str(repo))
        ghost = make_agent(project_id=proj["id"], name="Ghost", role="backend-worker")
        # Deactivate
        r = client.patch(f"/api/agents/{ghost['id']}", json={"is_active": False})
        assert r.status_code == 200

        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        names = {f["name"] for f in data["files"]}
        assert not any(n.startswith("memory/Ghost/") for n in names), (
            "memory files for inactive agent must not be counted"
        )

    def test_agents_on_other_projects_excluded(
        self, client, make_project, make_agent, tmp_path
    ):
        prefix_a = "TBX8A"
        prefix_b = "TBX8B"
        # Repo A has memory dirs for both Alice and Mallory
        repo_a = _setup_repo(tmp_path / "a", prefix_a, agent_names=["Alice", "Mallory"])
        proj_a = make_project(prefix=prefix_a, repo_path=str(repo_a))
        proj_b = make_project(prefix=prefix_b)

        # Alice is on project A, Mallory is on project B
        make_agent(project_id=proj_a["id"], name="Alice", role="backend-worker")
        make_agent(project_id=proj_b["id"], name="Mallory", role="backend-worker")

        data = client.get(f"/api/projects/{proj_a['id']}/token-budget").json()
        names = {f["name"] for f in data["files"]}
        # Alice's memory shows; Mallory's does not (she's on a different project)
        assert any(n.startswith("memory/Alice/") for n in names)
        assert not any(n.startswith("memory/Mallory/") for n in names)


class TestCeilingRebalance:
    """Post-DWB-331 ceilings (2026-06-05): playbook 2500→4000,
    project_rules 1000→3000, claude_md 1500→2000, architecture 6000→7500,
    readme 2500→3500, initial 1500→2000. agent_def stays at 1500. memory and
    handoff caps unchanged.

    Asserts caps surface on the budget endpoint. If a future ticket tunes
    them again, the source of truth (_TOKEN_CEILINGS in routers/projects.py)
    must update along with these tests.
    """

    def test_agent_def_ceiling_is_1500(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "DR1", agent_names=[])
        proj = make_project(prefix="DR1", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        agent_def = next(
            f for f in data["files"] if f["category"] == "agent_def"
        )
        assert agent_def["ceiling"] == 1500

    def test_project_rules_ceiling_is_4000(self, client, make_project, tmp_path):
        # DWB-399: bumped 3000 -> 4000 (worker rules are ~3042, need headroom).
        repo = _setup_repo(tmp_path, "DR2", agent_names=[])
        proj = make_project(prefix="DR2", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        rules = next(
            f for f in data["files"] if f["category"] == "project_rules"
        )
        assert rules["ceiling"] == 4000

    def test_architecture_ceiling_is_7500(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "DR3", agent_names=[])
        proj = make_project(prefix="DR3", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        arch = next(
            f for f in data["files"] if f["category"] == "architecture"
        )
        assert arch["ceiling"] == 7500

    def test_readme_ceiling_is_3500(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "DR4", agent_names=[])
        proj = make_project(prefix="DR4", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        readme = next(
            f for f in data["files"] if f["category"] == "readme"
        )
        assert readme["ceiling"] == 3500

    def test_playbook_and_claude_md_and_initial_bumped(
        self, client, make_project, tmp_path
    ):
        repo = _setup_repo(tmp_path, "DR5", agent_names=[])
        proj = make_project(prefix="DR5", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        by_category = {f["category"]: f["ceiling"] for f in data["files"]}
        assert by_category["playbook"] == 4000
        assert by_category["claude_md"] == 2000
        assert by_category["initial"] == 2000


class TestGateEnforcedHelper:
    """DWB-397/399: is_gate_enforced — shipped DWB doctrine is advisory;
    project_rules are budgeted (TL-editable)."""

    def test_playbooks_and_defs_exempt(self):
        from app.config.token_budget import is_gate_enforced

        assert is_gate_enforced(".claude/team_lead_playbook.md") is False
        assert is_gate_enforced(".claude/worker_playbook.md") is False
        assert is_gate_enforced(".claude/agents/backend-worker.md") is False

    def test_project_rules_enforced(self):
        # DWB-399: project_rules are NOT shipped doctrine; they gate.
        from app.config.token_budget import is_gate_enforced

        assert is_gate_enforced(".claude/project_rules_worker.md") is True
        assert is_gate_enforced(".claude/project_rules_team_lead.md") is True
        assert is_gate_enforced(".claude/project_rules_pm.md") is True

    def test_root_docs_enforced(self):
        from app.config.token_budget import is_gate_enforced

        for name in ("CLAUDE.md", "HANDOFF.md", "ARCHITECTURE.md",
                     "README.md", "INITIAL.md"):
            assert is_gate_enforced(name) is True, name

    def test_memory_file_names_classify_as_agent_def_by_name(self):
        # Memory files match no classify_file prefix, so they fall through to
        # 'agent_def' and is_gate_enforced returns False on the NAME alone.
        # DWB-401: memory is now never gated regardless (agent_consolidation's
        # _gate_counts returns False for any agent_name entry).
        from app.config.token_budget import is_gate_enforced

        assert is_gate_enforced("memory/Barry/memory.md") is False


class TestExemptStatus:
    """DWB-398/399: gate-exempt categories (playbook, agent_def) report status
    'exempt' on the budget endpoint instead of over/warning/ok. They just exist;
    size isn't judged. Root docs + project_rules + memory are judged
    (over/warning/ok). project_rules left the exempt set in DWB-399.
    """

    def test_exempt_categories_report_exempt(self, client, make_project, tmp_path):
        repo = _setup_repo(tmp_path, "EX1", agent_names=[])
        proj = make_project(prefix="EX1", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()

        from app.config.token_budget import GATE_EXEMPT_CATEGORIES

        exempt_entries = [
            f for f in data["files"] if f["category"] in GATE_EXEMPT_CATEGORIES
        ]
        assert exempt_entries, "expected at least one playbook/agent_def"
        for entry in exempt_entries:
            assert entry["status"] == "exempt", (
                f"{entry['name']} ({entry['category']}) should be exempt, "
                f"got {entry['status']}"
            )

    def test_project_rules_judged_not_exempt(self, client, make_project, tmp_path):
        # DWB-399: project_rules are budgeted now — under-ceiling fixture reads 'ok'.
        repo = _setup_repo(tmp_path, "EX5", agent_names=[])
        proj = make_project(prefix="EX5", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        rules = next(f for f in data["files"] if f["category"] == "project_rules")
        assert rules["status"] in ("over", "warning", "ok")
        assert rules["status"] != "exempt"

    def test_over_ceiling_playbook_still_exempt_not_over(
        self, client, make_project, tmp_path
    ):
        # A playbook far past its 4000 ceiling must still read 'exempt', proving
        # the exemption short-circuits the ratio judgment.
        repo = tmp_path / "repo"
        _write(repo / ".claude" / "worker_playbook.md", "# huge\n" + "word " * 6000)
        proj = make_project(prefix="EX2", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        pb = next(f for f in data["files"] if f["category"] == "playbook")
        assert pb["tokens"] > pb["ceiling"], "test fixture should exceed ceiling"
        assert pb["status"] == "exempt"

    def test_exempt_keeps_tokens_and_ceiling(self, client, make_project, tmp_path):
        # Only status changes; tokens + ceiling stay in the payload.
        repo = _setup_repo(tmp_path, "EX3", agent_names=[])
        proj = make_project(prefix="EX3", repo_path=str(repo))
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()
        pb = next(f for f in data["files"] if f["category"] == "playbook")
        assert isinstance(pb["tokens"], int) and pb["tokens"] > 0
        assert pb["ceiling"] == 4000

    def test_root_docs_and_memory_not_exempt(
        self, client, make_project, make_agent, tmp_path
    ):
        prefix = "EX4"
        repo = _setup_repo(tmp_path, prefix, agent_names=["Barry"])
        proj = make_project(prefix=prefix, repo_path=str(repo))
        make_agent(project_id=proj["id"], name="Barry", role="backend-worker")
        data = client.get(f"/api/projects/{proj['id']}/token-budget").json()

        non_exempt = [
            f
            for f in data["files"]
            if f["name"] in ("CLAUDE.md", "ARCHITECTURE.md")
            or f["name"].startswith("memory/")
        ]
        assert non_exempt
        for entry in non_exempt:
            assert entry["status"] != "exempt", (
                f"{entry['name']} should be judged, not exempt"
            )
            assert entry["status"] in ("over", "warning", "ok")

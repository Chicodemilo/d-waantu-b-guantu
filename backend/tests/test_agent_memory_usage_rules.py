# Path: tests/test_agent_memory_usage_rules.py
# File: test_agent_memory_usage_rules.py
# Created: 2026-06-10
# Purpose: Tests for DWB-352 inline memory_usage_rules surfaced on identify + spawn-prepare
# Caller: pytest
# Callees: POST /api/agents/identify, POST /api/agents/spawn-prepare, app.config.memory_rules
# Data In: tmp_path filesystem, factory project + agent
# Data Out: Assertions on response field presence, length cap, content invariants, single source of truth
# Last Modified: 2026-10-09 (DWB-667: the pinned cap literal moves 700 -> 1050,
#                then 1050 -> 1350 for the two findings the authors sent back,
#                then 1350 -> 1600 for the junk-keyword qualifier)

"""DWB-352 coverage.

The DWB API ships a condensed copy of the memory-file usage rules on every
identify + spawn-prepare response so workers see the rules inline whether
or not they open the full playbook.

Pinned invariants:

  1. Both endpoints include a ``memory_usage_rules`` field in the response.
  2. The field is <= MEMORY_USAGE_RULES_MAX_CHARS (hard cap; the
     module-level assert protects against silent overflow on edits). The
     number was 600 until DWB-661 moved it to 700; these tests read the
     constant rather than a literal so there is one place to change.
  3. Both endpoints serve the same string (single source of truth: the
     ``MEMORY_USAGE_RULES`` constant in app.config.memory_rules).
  4. Key tokens are present so a future edit that drops an important rule
     fails the test rather than slipping into production: the four file
     names, the ISO 8601 rule, the append-only contract, the
     session-complete easy-path endpoint, and the "NEVER edit" identity.md
     rule.
"""


def _make_project(client, tmp_path, prefix):
    return client.post("/api/projects", json={
        "prefix": prefix, "name": f"Project {prefix}",
        "repo_path": str(tmp_path),
    }).json()


def _make_agent(client, project_id, name, role="backend-worker"):
    return client.post("/api/agents", json={
        "project_id": project_id, "name": name,
        "role": role, "api_key": f"mur-{name}",
    }).json()


# ---------------------------------------------------------------------------
# 1. Field present on both endpoints
# ---------------------------------------------------------------------------


class TestMemoryUsageRulesSurfaced:
    def test_identify_response_includes_memory_usage_rules(
        self, client, tmp_path,
    ):
        _make_project(client, tmp_path, "MUR1")
        _make_agent(client, client.get("/api/projects").json()[-1]["id"], "Pixel")
        r = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Pixel", "project_prefix": "MUR1",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "memory_usage_rules" in body
        assert isinstance(body["memory_usage_rules"], str)
        assert body["memory_usage_rules"].strip() != ""

    def test_spawn_prepare_response_includes_memory_usage_rules(
        self, client, tmp_path,
    ):
        proj = _make_project(client, tmp_path, "MUR2")
        _make_agent(client, proj["id"], "Vega")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Vega", "project_prefix": "MUR2",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "memory_usage_rules" in body
        assert isinstance(body["memory_usage_rules"], str)
        assert body["memory_usage_rules"].strip() != ""


# ---------------------------------------------------------------------------
# 2. The char cap (MEMORY_USAGE_RULES_MAX_CHARS)
# ---------------------------------------------------------------------------


class TestMemoryUsageRulesLengthCap:
    def test_identify_payload_under_cap(self, client, tmp_path):
        proj = _make_project(client, tmp_path, "MUR3")
        _make_agent(client, proj["id"], "Cap")
        r = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Cap", "project_prefix": "MUR3",
        })
        from app.config.memory_rules import MEMORY_USAGE_RULES_MAX_CHARS
        assert len(r.json()["memory_usage_rules"]) <= MEMORY_USAGE_RULES_MAX_CHARS

    def test_spawn_prepare_payload_under_cap(self, client, tmp_path):
        proj = _make_project(client, tmp_path, "MUR4")
        _make_agent(client, proj["id"], "Cap")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Cap", "project_prefix": "MUR4",
        })
        from app.config.memory_rules import MEMORY_USAGE_RULES_MAX_CHARS
        assert len(r.json()["memory_usage_rules"]) <= MEMORY_USAGE_RULES_MAX_CHARS

    def test_constant_module_enforces_cap_at_import(self):
        """The module-level assert in app.config.memory_rules is the
        load-bearing check. If a future edit pushes a constant past the cap,
        the import fails and every test that touches the API blows up -
        exactly the right failure mode.

        The literal is pinned on purpose: moving the cap should be a
        deliberate edit in two places, not a silent drift in one. DWB-661
        moved it 600 -> 700 after trimming the human_memory block to its
        floor; DWB-667 moved it 700 -> 1050 the same way, to carry
        `situation` and the worked contrast between a reachable keyword and a
        filing label. The contrast is the part that needed the room: "keywords
        are the words that will be in the air" is a sentence the authors of all
        288 unreachable rows believed they were following, and only the pair -
        'git checkout' beside 'self-exempt' - changes what the next one writes.
        It then moved 1050 -> 1350 inside the SAME ticket, which is the kind of
        second bump this pinned literal exists to make visible. The first move
        carried the rule; four agents then re-keyworded 207 rows against it and
        sent back what the rule did not contain - that INFLECTION, not labels,
        is the hard half, and that the procedure is to write the situation
        first and read the keywords out of it. Both were found by running rows
        rather than by reading the rule.

        THEN 1350 -> 1600, a THIRD move in the same ticket, and the reason is
        this literal doing its job: the second move shipped "several short
        keywords beat one precise phrase" into the block some agents read
        INSTEAD of the playbook, and measuring the pass that followed showed
        what that advice produces unqualified - keywords like 'before i' and
        'show me', two ordinary English words that clear the two-token floor by
        themselves and fire on any first-person prose. The qualifier is part of
        the advice rather than an addition to it, so it had to ship in the same
        place. Three moves in one ticket is a lot; each was forced by a
        measurement rather than by drafting, and the trim was done first every
        time. See the cap block in app/config/memory_rules.py, which also
        records that the block is now 1597 against the stock variant's 593 and
        that its SHAPE, not its size, is the open question."""
        from app.config.memory_rules import (
            MEMORY_USAGE_RULES,
            MEMORY_USAGE_RULES_MAX_CHARS,
        )
        assert MEMORY_USAGE_RULES_MAX_CHARS == 1600
        assert len(MEMORY_USAGE_RULES) <= MEMORY_USAGE_RULES_MAX_CHARS


# ---------------------------------------------------------------------------
# 3. Single source of truth: both endpoints serve the same string
# ---------------------------------------------------------------------------


class TestMemoryUsageRulesSingleSource:
    def test_identify_and_spawn_prepare_serve_identical_content(
        self, client, tmp_path,
    ):
        proj = _make_project(client, tmp_path, "MUR5")
        _make_agent(client, proj["id"], "Twin")

        r_id = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Twin", "project_prefix": "MUR5",
        })
        r_sp = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Twin", "project_prefix": "MUR5",
        })
        assert r_id.status_code == 200
        assert r_sp.status_code == 200
        assert r_id.json()["memory_usage_rules"] == r_sp.json()["memory_usage_rules"]

    def test_responses_match_the_module_constant(self, client, tmp_path):
        """Pin that the endpoint output IS the constant, not a copy that
        drifts. If someone duplicates the string inside a service, this
        test catches it."""
        from app.config.memory_rules import MEMORY_USAGE_RULES

        proj = _make_project(client, tmp_path, "MUR6")
        _make_agent(client, proj["id"], "Sync")
        r = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Sync", "project_prefix": "MUR6",
        })
        assert r.json()["memory_usage_rules"] == MEMORY_USAGE_RULES


# ---------------------------------------------------------------------------
# 4. Key tokens present (drift detection for future edits)
# ---------------------------------------------------------------------------


class TestMemoryUsageRulesContent:
    """The constant can be reworded; what cannot drop without explicit
    intent is the set of rules it covers. These assertions pin the
    important tokens so a future edit that trims too aggressively fails."""

    def test_lists_memory_files(self, client, tmp_path):
        # DWB-401: 2-file model. The rules must name identity.md + memory.md and
        # must NOT reference the retired scratchpad/lessons/recent_sessions.
        proj = _make_project(client, tmp_path, "MURC1")
        _make_agent(client, proj["id"], "Files")
        rules = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Files", "project_prefix": "MURC1",
        }).json()["memory_usage_rules"]
        for fname in ("identity.md", "memory.md"):
            assert fname in rules, f"missing file mention: {fname}"
        for retired in ("scratchpad.md", "lessons.md", "recent_sessions.md"):
            assert retired not in rules, f"retired file still mentioned: {retired}"

    def test_mentions_iso_8601_timestamp_rule(self, client, tmp_path):
        proj = _make_project(client, tmp_path, "MURC2")
        _make_agent(client, proj["id"], "Iso")
        rules = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Iso", "project_prefix": "MURC2",
        }).json()["memory_usage_rules"]
        # Case-insensitive; the exact phrasing may evolve but the standard
        # name must stay in the rules.
        assert "ISO 8601" in rules

    def test_mentions_append_only_contract(self, client, tmp_path):
        proj = _make_project(client, tmp_path, "MURC3")
        _make_agent(client, proj["id"], "App")
        rules = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "App", "project_prefix": "MURC3",
        }).json()["memory_usage_rules"]
        # "append-only" wording is the load-bearing concept; allow either
        # casing variant in case the constant gets re-titled.
        assert "append-only" in rules.lower() or "never overwrit" in rules.lower()

    def test_mentions_session_complete_easy_path(self, client, tmp_path):
        proj = _make_project(client, tmp_path, "MURC4")
        _make_agent(client, proj["id"], "Sess")
        rules = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "Sess", "project_prefix": "MURC4",
        }).json()["memory_usage_rules"]
        assert "session-complete" in rules

    def test_identity_md_marked_never_edit(self, client, tmp_path):
        proj = _make_project(client, tmp_path, "MURC5")
        _make_agent(client, proj["id"], "NoEdit")
        rules = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "NoEdit",
            "project_prefix": "MURC5",
        }).json()["memory_usage_rules"]
        # The NEVER-edit rule on identity.md is one of the few hard rules;
        # require an explicit "NEVER" + identity reference in the same
        # rules blob.
        assert "NEVER" in rules
        assert "identity.md" in rules

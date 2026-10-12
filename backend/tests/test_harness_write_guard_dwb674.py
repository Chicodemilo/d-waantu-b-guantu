# Path: tests/test_harness_write_guard_dwb674.py
# File: test_harness_write_guard_dwb674.py
# Created: 2026-10-12 (DWB-674)
# Purpose: Acceptance tests for scripts/hooks/block_harness_memory_writes.py -
#          arming, the Bash path, the rule table, and the regressions that
#          prove the guard did not wedge the session.
# Caller: pytest
# Callees: scripts/hooks/block_harness_memory_writes.py (as a subprocess)
# Data In: crafted PreToolUse payloads on the script's stdin
# Data Out: assertions on exit code, stdout, permissionDecision, reason text
# Last Modified: 2026-10-12 (DWB-674)

"""DWB-674: the guard is armed only when DWB is in use for the repo, it covers
Bash as well as the file tools, and it walks a rule table.

RUN AS A SUBPROCESS, NOT IMPORTED. The contract under test is the hook
contract - exit code, stdout, and the JSON block - and importing the module
would test the functions while leaving the three things Claude Code actually
reads untested. It also keeps the real `~/.claude` out of reach: every run gets
CLAUDE_CONFIG_DIR and CLAUDE_PROJECT_DIR pointed at tmp_path.

THE ARMED AND UNARMED CASES RUN ON THE SAME PAYLOADS, IN THIS FILE, ON PURPOSE.
An absence assertion that passes because nothing was looked at is the standing
hazard for a guard, so every "passes through untouched" assertion has a sibling
in the same sweep showing the identical payload refused when armed. Neither
half is evidence alone.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "hooks"
    / "block_harness_memory_writes.py"
)

# A settings.json carrying DWB's own hook wiring. The marker the script looks
# for is the script name inside a hook command, so this is the real shape.
ARMED_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": 'python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/block_harness_memory_writes.py"',
                        "timeout": 5,
                    }
                ],
            }
        ]
    }
}

# A settings.json with hooks, but none of them DWB's.
UNARMED_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Write",
                "hooks": [{"type": "command", "command": "echo hi", "timeout": 5}],
            }
        ]
    }
}


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------


def _make_repo(root: Path, settings: dict | None) -> Path:
    repo = root / "repo"
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (repo / ".claude" / "settings.json").write_text(json.dumps(settings))
    return repo


def _make_config_dir(root: Path) -> Path:
    config = root / "fake_claude_home"
    (config / "projects" / "some-project" / "memory").mkdir(parents=True)
    return config


def _run(payload, repo: Path, config: Path):
    """Feed the script a payload. Returns (returncode, stdout)."""
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(config)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=raw,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    return proc.returncode, proc.stdout


def _decision(stdout: str) -> dict:
    """The hookSpecificOutput block, asserting the envelope on the way."""
    parsed = json.loads(stdout)
    block = parsed["hookSpecificOutput"]
    assert block["hookEventName"] == "PreToolUse"
    return block


def _payload_for(tool: str, target: str) -> dict:
    """A crafted payload per tool, each in that tool's real input shape."""
    if tool == "Write":
        tool_input = {"file_path": target, "content": "durable lesson\n"}
    elif tool == "Edit":
        tool_input = {
            "file_path": target,
            "old_string": "a",
            "new_string": "b",
        }
    elif tool == "MultiEdit":
        tool_input = {
            "file_path": target,
            "edits": [{"old_string": "a", "new_string": "b"}],
        }
    elif tool == "NotebookEdit":
        tool_input = {"notebook_path": target, "new_source": "x"}
    elif tool == "Bash":
        # The heredoc that walked through the old matcher for a full day.
        tool_input = {"command": f"cat > {target} <<'EOF'\ndurable lesson\nEOF"}
    else:  # pragma: no cover - guarded by the parametrize lists
        raise AssertionError(f"no payload shape for {tool}")
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": "/nowhere",
    }


ALL_WRITE_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"]

# The four tools that AUTHOR a file. The root_doc rule is scoped to these and
# deliberately excludes Bash: a Bash command naming a filename proves nothing
# about whether it writes there, and a read-only `grep` over a *.md path put a
# confirmation dialog in front of the human until the scope was fixed.
FILE_WRITE_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit"]


def _load_guard():
    """Import the hook module. Safe: it does nothing outside __main__."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("guard_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root_docs_named_in_classify_file() -> set[str]:
    """The root-doc filenames token_budget names by explicit equality.

    AST, NOT A GREP. The question is which string literals `classify_file`
    COMPARES against, which is a question about code; a text scan over the
    module would also hit the block comment near GATE_EXEMPT_CATEGORIES that
    lists HANDOFF/ARCHITECTURE/README/INITIAL in prose - four of the five, in
    a sentence, which is exactly the shape that produces a confident wrong
    answer. The `in` and `endswith` branches are not equality and are not root
    docs, so they drop out for free.
    """
    import ast
    import inspect

    from app.config import token_budget

    tree = ast.parse(inspect.getsource(token_budget))
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "classify_file"
    )

    found = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        if not all(isinstance(op, ast.Eq) for op in node.ops):
            continue
        for operand in node.comparators:
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                if operand.value.endswith(".md"):
                    found.add(operand.value.lower())
    return found


def test_the_allowlist_matches_token_budget():
    """The forced duplication, made detectable.

    The hook is stdlib-only and runs in consumer repos with no backend, so it
    CANNOT import token_budget and the copy is unavoidable. Two copies of one
    truth drift; this is the thing that tells someone, instead of care.
    """
    module = _load_guard()
    canonical = _root_docs_named_in_classify_file()

    # Anti-vacuous: an empty scan makes the comparison below free, and a
    # silently-empty AST walk is how this check would read as green forever.
    assert canonical, (
        "found no root-doc equality branch in classify_file - either it stopped "
        "naming filenames or this AST walk has rotted"
    )
    assert {n.lower() for n in module.ROOT_DOC_ALLOWED} == canonical, (
        "the hook's ROOT_DOC_ALLOWED and token_budget.classify_file have "
        f"drifted: hook={sorted(module.ROOT_DOC_ALLOWED)} "
        f"token_budget={sorted(canonical)}"
    )


def test_the_reason_names_every_allowed_doc():
    """The refusal text is the rule's whole user-facing surface.

    An agent is stopped and reads this and nothing else. A reason that names
    fewer docs than the allowlist permits hides places that agent may write,
    and the text falling out of step with the list is silent otherwise.
    """
    module = _load_guard()

    missing = [
        name for name in sorted(module.ROOT_DOC_ALLOWED)
        if name not in module.ROOT_DOC_REASON
    ]
    assert not missing, (
        f"ROOT_DOC_ALLOWED permits {missing} but ROOT_DOC_REASON never names "
        "them, so an agent stopped by this rule is not told it may write there"
    )
    # The count word is DERIVED from the constant, not written down here. A
    # literal "Five" in this test is the same defect as the literal in the
    # text: it goes stale the day the allowlist moves, and then both agree
    # with each other and with nothing else.
    words = {3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven"}
    size = len(module.ROOT_DOC_ALLOWED)
    assert size in words, f"extend the count-word map for {size} docs"
    assert f"{words[size]} root docs" in module.ROOT_DOC_REASON, (
        f"the reason must say '{words[size]} root docs'; the allowlist holds "
        f"{size}"
    )
    for n, word in words.items():
        if n != size:
            assert f"{word} root docs" not in module.ROOT_DOC_REASON, (
                f"the reason still says '{word} root docs' while the allowlist "
                f"holds {size}"
            )


def test_the_sweep_covers_every_tool_the_script_claims():
    """Structural guard: the parametrize list IS the script's tool set.

    Every other test here is one runtime case. A tool added to the script
    later without a payload shape in `_payload_for` would leave the sweep
    quietly one tool short, and a sweep that is short in exactly the place a
    new hole opens is the whole failure mode this ticket exists to close.
    """
    module = _load_guard()

    assert set(module.WRITE_TOOLS) == set(ALL_WRITE_TOOLS), (
        "the script's WRITE_TOOLS and this file's sweep have drifted: "
        f"script={sorted(module.WRITE_TOOLS)} sweep={sorted(ALL_WRITE_TOOLS)}"
    )
    # And every rule in the table carries a reason that points somewhere.
    for rule in module.RULES:
        assert rule.mode in {"deny", "ask"}, rule.name
        assert "/api/" in rule.reason or ".md" in rule.reason, (
            f"rule {rule.name} refuses without naming a replacement route"
        )


def test_every_rule_declares_a_tool_scope_within_the_matcher():
    """A rule's scope is a fact it must state, not a default it inherits.

    root_doc applying to Bash is what interrupted a read-only grep. The
    general defence is that no rule gets a scope by accident: each one
    declares its tools, and a scope naming a tool outside WRITE_TOOLS would
    be silently unreachable.
    """
    module = _load_guard()

    assert module.RULES, "no rules; this test asserts nothing"
    for rule in module.RULES:
        assert rule.tools, f"rule {rule.name} declares no tool scope"
        unknown = set(rule.tools) - set(module.WRITE_TOOLS)
        assert not unknown, (
            f"rule {rule.name} is scoped to {sorted(unknown)}, which the "
            "matcher never delivers, so that scope is dead"
        )


def test_the_two_rules_have_the_scopes_their_subjects_require():
    """Named explicitly, because the difference is the whole fix.

    harness_memory keys on a SPECIFIC sealed path that must appear in a
    command for the command to write there, so Bash is in scope and must stay
    there - it was the heredoc hole. root_doc keys on a BARE FILENAME, which
    any command may mention for any reason, so it is limited to the tools
    that author files.
    """
    module = _load_guard()
    by_name = {r.name: r for r in module.RULES}

    assert set(by_name["harness_memory"].tools) == set(module.WRITE_TOOLS), (
        "harness_memory must cover every matched tool including Bash; "
        "narrowing it reopens the heredoc hole"
    )
    assert set(by_name["root_doc"].tools) == set(module.FILE_WRITE_TOOLS)
    assert "Bash" not in by_name["root_doc"].tools


# --------------------------------------------------------------------------
# Criterion 1 + 2: refused when armed, untouched when unarmed, same payloads.
# --------------------------------------------------------------------------


class TestHarnessMemoryAcrossEveryTool:
    @pytest.mark.parametrize("tool", ALL_WRITE_TOOLS)
    def test_armed_refuses_harness_memory_write(self, tmp_path, tool):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        sealed = str(config / "projects" / "some-project" / "memory" / "MEMORY.md")

        rc, out = _run(_payload_for(tool, sealed), repo, config)

        assert rc == 0, f"{tool}: hook must always exit 0"
        assert out.strip(), f"{tool}: expected a decision, got silence"
        block = _decision(out)
        assert block["permissionDecision"] == "deny", f"{tool}: {block}"

    @pytest.mark.parametrize("tool", ALL_WRITE_TOOLS)
    def test_unarmed_lets_the_identical_payload_through(self, tmp_path, tool):
        """The sibling of the test above. Same bytes on stdin, no settings."""
        repo = _make_repo(tmp_path, None)
        config = _make_config_dir(tmp_path)
        sealed = str(config / "projects" / "some-project" / "memory" / "MEMORY.md")

        rc, out = _run(_payload_for(tool, sealed), repo, config)

        assert rc == 0
        assert out == "", f"{tool}: unarmed guard spoke: {out!r}"

    @pytest.mark.parametrize("tool", ALL_WRITE_TOOLS)
    def test_settings_without_dwb_wiring_is_unarmed(self, tmp_path, tool):
        """A settings.json that exists but is somebody else's."""
        repo = _make_repo(tmp_path, UNARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        sealed = str(config / "projects" / "some-project" / "memory" / "MEMORY.md")

        rc, out = _run(_payload_for(tool, sealed), repo, config)

        assert rc == 0
        assert out == "", f"{tool}: armed by a non-DWB settings.json: {out!r}"

    def test_config_dir_outside_memory_is_not_sealed(self, tmp_path):
        """Hard rule 2 is about memory, not about the whole config dir."""
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        target = str(config / "settings.json")

        rc, out = _run(_payload_for("Write", target), repo, config)

        assert rc == 0
        assert out == "", f"denied a non-memory harness file: {out!r}"


# --------------------------------------------------------------------------
# Criterion 3: the refusal names the replacement route.
# --------------------------------------------------------------------------


class TestRefusalNamesTheReplacementRoute:
    def test_harness_memory_reason_names_the_api(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        sealed = str(config / "projects" / "p" / "memory" / "MEMORY.md")

        _, out = _run(_payload_for("Write", sealed), repo, config)
        reason = _decision(out)["permissionDecisionReason"]

        assert "/api/agents/{agent_id}/memories" in reason
        assert "/api/journal" in reason

    def test_root_doc_reason_names_where_to_write_instead(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        target = str(repo / "NOTES.md")

        _, out = _run(_payload_for("Write", target), repo, config)
        reason = _decision(out)["permissionDecisionReason"]

        assert "HANDOFF.md" in reason
        assert "ARCHITECTURE.md" in reason
        assert "/api/agents/{agent_id}/memories" in reason


# --------------------------------------------------------------------------
# The second rule: new root-level docs, mode ask.
# --------------------------------------------------------------------------


class TestRootDocRule:
    @pytest.mark.parametrize("tool", FILE_WRITE_TOOLS)
    def test_new_root_doc_is_asked_about_on_every_authoring_tool(
        self, tmp_path, tool
    ):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        target = str(repo / "SCRATCH_NOTES.md")

        rc, out = _run(_payload_for(tool, target), repo, config)

        assert rc == 0
        assert out.strip(), f"{tool}: new root doc passed silently"
        assert _decision(out)["permissionDecision"] == "ask"

    def test_bash_naming_a_new_root_doc_is_silent(self, tmp_path):
        """The reported outage, as its own case.

        A Bash command naming a root-level *.md proves nothing about whether
        it writes there, so the rule does not apply. This is the literal
        command that put a confirmation dialog in front of the human: a
        read-only grep whose argument happens to be a markdown filename.
        """
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        'grep -n "coding-standards.md" docs/worker_playbook.md'
                        " | cut -c1-320"
                    )
                },
            },
            repo,
            config,
        )

        assert rc == 0
        assert out == "", (
            "a read-only grep naming a *.md path was interrupted; the "
            f"root_doc rule must not apply to Bash. got: {out!r}"
        )

    def test_bash_heredoc_to_a_new_root_doc_is_also_silent(self, tmp_path):
        """The cost of the scope, stated rather than discovered.

        Authoring a root doc THROUGH Bash is not caught, and cannot be
        without deciding from a command string whether it writes - the shell
        parsing that was ruled out. Written down so the gap is a known
        decision and not a surprise; harness_memory still covers Bash because
        its target is a specific sealed path, not a bare filename.
        """
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        target = repo / "SCRATCH_NOTES.md"

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": f"cat > {target} <<'EOF'\nx\nEOF"},
            },
            repo,
            config,
        )

        assert rc == 0
        assert out == "", (
            "documented gap: root_doc does not apply to Bash. If this now "
            "fires, the scope changed and the docstring is stale."
        )

    def test_owned_root_doc_passes(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)

        for name in (
            "HANDOFF.md",
            "ARCHITECTURE.md",
            "README.md",
            "CLAUDE.md",
            "INITIAL.md",
        ):
            rc, out = _run(_payload_for("Write", str(repo / name)), repo, config)
            assert rc == 0
            assert out == "", f"{name} is owned and must pass: {out!r}"

    def test_existing_root_doc_is_edited_freely(self, tmp_path):
        """The rule is creation. An existing root doc is nobody's business."""
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        existing = repo / "CHANGELOG.md"
        existing.write_text("# Changelog\n")

        rc, out = _run(_payload_for("Edit", str(existing)), repo, config)

        assert rc == 0
        assert out == "", f"blocked an edit to an existing root doc: {out!r}"

    def test_doc_below_the_root_passes(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        (repo / "docs").mkdir()

        rc, out = _run(_payload_for("Write", str(repo / "docs" / "NEW.md")), repo, config)

        assert rc == 0
        assert out == "", f"docs/ is a legitimate home: {out!r}"

    def test_deny_beats_ask_when_one_command_names_both(self, tmp_path):
        """Rule order is severity order, not discovery order.

        Since root_doc stopped applying to Bash this no longer discriminates
        ordering on its own - only harness_memory is in scope here - but it
        still pins the outcome that matters: a command touching a sealed path
        is denied no matter what else it names.
        """
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        sealed = config / "projects" / "p" / "memory" / "MEMORY.md"
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            # The root doc is named FIRST, so first-match-by-candidate would
            # return ask here.
            "tool_input": {"command": f"cp {repo / 'NOTES.md'} {sealed}"},
        }

        rc, out = _run(payload, repo, config)

        assert rc == 0
        assert _decision(out)["permissionDecision"] == "deny"


# --------------------------------------------------------------------------
# Criterion 4: the regression that proves the session is not wedged.
# --------------------------------------------------------------------------


ORDINARY_COMMANDS = [
    "git status --short",
    "ls -la /tmp",
    "python3 -m pytest tests/ -q",
    "curl -s http://localhost:8000/api/status",
    "grep -rn 'def main' backend/app",
    "cd backend && source .venv/bin/activate && alembic current",
    "echo hello world",
    "docker compose up -d",
    'git commit -m "fix(hook): arm the guard"',
    "npm run dev",
    # EVERY COMMAND ABOVE THIS LINE CARRIES NO .md TOKEN, WHICH IS WHY THIS
    # SWEEP PASSED WHILE READ-ONLY MARKDOWN COMMANDS WERE BEING INTERRUPTED.
    # The sample avoided the failing case, so the check reported coverage it
    # did not have. These are the ones that would have caught it: ordinary
    # read-only commands whose arguments are markdown paths, including
    # root-level ones that do not exist.
    'grep -n "coding-standards.md" docs/worker_playbook.md | cut -c1-320',
    "cat NOTES.md",
    "wc -l PLAN.md DESIGN.md",
    "ls -la *.md",
    "sed -n '1,40p' PROPOSAL.md",
    "head -20 CHANGELOG.md",
    "diff OLD_NOTES.md NEW_NOTES.md",
    "git log --oneline -- ROADMAP.md",
    "grep -rn TODO docs/ --include=*.md",
    "python3 -c \"print(open('SPEC.md').read())\"",
]


class TestOrdinaryBashIsUntouched:
    @pytest.mark.parametrize("command", ORDINARY_COMMANDS)
    def test_armed_guard_stays_silent_on_ordinary_commands(self, tmp_path, command):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            repo,
            config,
        )

        assert rc == 0
        assert out == "", f"wedged an ordinary command {command!r}: {out!r}"

    def test_command_mentioning_an_existing_root_doc_passes(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        (repo / "README.md").write_text("# readme\n")

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "grep -n install README.md"},
            },
            repo,
            config,
        )

        assert rc == 0
        assert out == "", f"blocked a read of README.md: {out!r}"

    def test_non_write_tool_is_not_judged(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)
        sealed = str(config / "projects" / "p" / "memory" / "MEMORY.md")

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": sealed},
            },
            repo,
            config,
        )

        assert rc == 0
        assert out == "", f"judged a Read: {out!r}"


# --------------------------------------------------------------------------
# Criterion 5: garbage in, exit 0 and no decision.
# --------------------------------------------------------------------------


class TestMalformedPayloads:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   \n",
            "not json at all",
            "{",
            "[]",
            '"a bare string"',
            "null",
            "123",
            '{"tool_name": "Write"}',
            '{"tool_name": "Write", "tool_input": null}',
            '{"tool_name": "Write", "tool_input": {"file_path": null}}',
            '{"tool_name": "Write", "tool_input": {"file_path": ""}}',
            '{"tool_name": null, "tool_input": {}}',
            '{"tool_name": "Bash", "tool_input": {"command": null}}',
            '{"tool_name": "Bash", "tool_input": {"command": ""}}',
            '{"tool_input": {"file_path": "/tmp/x"}}',
        ],
    )
    def test_exits_zero_with_no_decision(self, tmp_path, raw):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)

        rc, out = _run(raw, repo, config)

        assert rc == 0, f"payload {raw!r} produced rc={rc}"
        assert out == "", f"payload {raw!r} produced a decision: {out!r}"

    def test_malformed_settings_json_still_arms_on_the_marker(self, tmp_path):
        """A broken settings.json still answers 'is DWB wired here'."""
        repo = tmp_path / "repo"
        (repo / ".claude").mkdir(parents=True)
        (repo / ".claude" / "settings.json").write_text(
            '{"hooks": {"PreToolUse": [ '
            '{"command": "python3 scripts/hooks/block_harness_memory_writes.py"'
        )
        config = _make_config_dir(tmp_path)
        sealed = str(config / "projects" / "p" / "memory" / "MEMORY.md")

        rc, out = _run(_payload_for("Write", sealed), repo, config)

        assert rc == 0
        assert _decision(out)["permissionDecision"] == "deny"


# --------------------------------------------------------------------------
# The known uncovered edge, asserted so it is a documented hole and not a
# surprise the next person reads as a bug.
# --------------------------------------------------------------------------


class TestKnownUncoveredEdges:
    def test_literal_directory_in_an_assignment_is_still_caught(self, tmp_path):
        """A variable still holding a LITERAL sealed path is caught anyway.

        The assignment puts the sealed directory in the command verbatim, and
        verbatim is the whole test. Only the `$D` token is skipped.
        """
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f'D="{config}/projects/p/memory"; '
                        'echo lesson > "$D/MEMORY.md"'
                    )
                },
            },
            repo,
            config,
        )

        assert rc == 0
        assert _decision(out)["permissionDecision"] == "deny"

    def test_fully_indirect_path_is_the_real_hole(self, tmp_path):
        repo = _make_repo(tmp_path, ARMED_SETTINGS)
        config = _make_config_dir(tmp_path)

        rc, out = _run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": 'echo lesson > "$CLAUDE_CONFIG_DIR/projects/p/memory/M.md"'
                },
            },
            repo,
            config,
        )

        assert rc == 0
        assert out == "", (
            "this is the documented uncovered edge; if it now denies, the "
            "docstring is out of date, which is the thing to fix"
        )

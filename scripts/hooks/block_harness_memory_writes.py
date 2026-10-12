#!/usr/bin/env python3
# Path: scripts/hooks/block_harness_memory_writes.py
# File: block_harness_memory_writes.py
# Created: 2026-09-29 (DWB-589)
# Purpose: PreToolUse hook - walk a table of guarded write rules and refuse the
#          ones that belong somewhere else, naming the replacement route.
#          Rule 1: Claude Code's OWN file-based memory (spec section 7 hard
#          rule 2, deny). Rule 2: new root-level docs (ask).
# Caller: Claude Code PreToolUse hook (wired in .claude/settings.json by the TL)
# Callees: stdlib only - no DWB imports, no network, no database
# Data In: a PreToolUse hook payload as JSON on stdin
# Data Out: a permissionDecision JSON block on stdout, or nothing; always exit 0
# Last Modified: 2026-10-12 (DWB-674)

"""Refuse writes that belong on a different route, and say which route.

Spec section 7 hard rule 2, verbatim: "The harness's own file-based memory is
not used at all. It holds ONE thing: a pointer saying durable memory lives in
DWB, with the API shape. Two homes drift, and the one that drifts is always the
one nobody is reading."

WHAT THIS IS AND IS NOT. DWB can seal its OWN API, and DWB-589 does. It cannot
seal Claude Code's file memory, which belongs to the harness, so this hook is
the only available lever and it is a WEAKER one: anything that does not route
through PreToolUse goes around it. Do not describe the rule as airtight.

IT IS ARMED, NOT UNCONDITIONAL (DWB-674). DWB-589 shipped this unconditional
and said so deliberately. The replacement rule is the human's: do not deny on
suspicion, deny when DWB is being used. "In use" is decided LOCALLY from the
repo's own `.claude/settings.json` (see `_dwb_in_use`) - no API call, no DB, no
socket, because a hook that needs uvicorn up would fail closed every time the
server restarts, and failing closed here means wedging every write.

IT GUARDS BASH TOO (DWB-674). Bash is how agents actually write; a heredoc went
straight through the old `Write|Edit|MultiEdit|NotebookEdit` matcher for a full
day on another project. A Bash payload carries no `file_path`, so the target is
found by MATCHING A SEALED PATH IN THE COMMAND STRING: candidate path tokens are
lifted out of the command and handed to the SAME path predicate the file tools
use. There is no shell parser here and nothing infers intent from a command -
the only question asked is whether a sealed path appears in it. Two consequences
worth stating rather than discovering: a command that merely READS a sealed path
is also refused (telling a read from a write would be exactly the intent
inference that was rejected, and the refusal text names where to go instead),
and a path assembled through a VARIABLE is not covered at all (see
`_command_targets`).

THE PATH IS DERIVED, NEVER HARDCODED. `CLAUDE_CONFIG_DIR` first, then `~`
expanded at runtime. DWB-574 shipped a hardcoded home directory that leaked a
real username into this repo, and this repo is cloned onto other machines.

IT ALWAYS EXITS 0. Project rule for hook scripts, and here it matters more than
usual: a PreToolUse hook that crashes blocks the tool call it was inspecting,
so a parse error on an unexpected payload would stop every Write in the session.
Failing to guard one write is far cheaper than wedging the session.

SILENCE MEANS NO OPINION. Nothing is ever printed for an allowed call. Printing
an allow decision would override a later hook or the user's own permission
settings, which is not this script's business.
"""

import json
import os
import re
import sys
from pathlib import Path

# Tools that carry their target in `tool_input` under a path key.
FILE_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

# Tools that carry a command string instead of a path. Bash is in the table
# before it is in the matcher: the matcher line in .claude/settings.json is a
# separate change (subagent writes under .claude/ open a permission dialog), so
# until a TL adds Bash there this branch is correct but never reached.
COMMAND_TOOLS = frozenset({"Bash"})

WRITE_TOOLS = FILE_WRITE_TOOLS | COMMAND_TOOLS

# Keys a write tool may carry its target under. NotebookEdit uses
# `notebook_path`; the rest use `file_path`.
PATH_KEYS = ("file_path", "notebook_path", "path")

# The directory name that marks harness memory inside the config dir.
MEMORY_SEGMENT = "memory"

# Substrings that identify DWB's own hook wiring inside a settings.json hook
# command. Either one means this repo deliberately installed DWB's hooks.
DWB_SETTINGS_MARKERS = ("block_harness_memory_writes.py", "/api/hooks/")

# Root-level docs that are owned and may be written freely. Everything else
# at the repo root is only ASKED about, and only when it does not exist yet.
#
# THIS SET IS NOT A JUDGEMENT CALL, IT IS A COPY. It is exactly the set of root
# docs `backend/app/config/token_budget.py::classify_file` names by explicit
# equality, which is what the consolidation gate budgets and what the team_lead
# playbook section 5a spells out. One definition, two consumers.
#
# THE COPY IS FORCED AND WILL THEREFORE DRIFT. This script is stdlib-only and
# runs inside consumer repos that have no DWB backend, so it cannot import
# token_budget. Care is not the answer to a forced duplication; a test is.
# tests/test_harness_write_guard_dwb674.py AST-walks classify_file and asserts
# the two sets are equal, so whoever adds a sixth root doc to either one is
# told about the other instead of discovering it a sprint later.
#
# THE TEST FOR MEMBERSHIP IS "IS AN AGENT INSTRUCTED TO AUTHOR THIS BY HAND",
# NOT "DOES DWB CREATE THIS FILE". The two questions have different answers and
# conflating them is what put this list wrong the first time.
#
# INITIAL.md is here because docs/team_lead_playbook.md's First-Run Checklist
# says, for an empty repo: "write INITIAL.md, ARCHITECTURE.md, HANDOFF.md".
# That is an agent Write through a tool call, so it reaches this hook, and a
# guard that interrupts the procedure the playbook prescribes is how guards get
# ignored.
#
# CODING_STANDARDS.md is deliberately NOT here, and it is the near miss worth
# recording because it LOOKS like INITIAL.md. Deploy does create it at the repo
# root, in its own step separate from _ROOT_DOC_STUBS, via
# `cs_path.write_text(...)` in app/services/playbook_deploy.py. That is backend
# file IO: it never passes through PreToolUse, so no agent is ever stopped on
# it. Nothing in docs/, .claude/ or CLAUDE.md instructs any agent to author it.
# It also classifies to `agent_def` in token_budget, exactly like NOTES.md -
# the consolidation gate does not count it as a root doc either.
#
# POINTER, because there IS a second list and the next person should know:
# app/services/playbook_deploy.py has its own root-doc set (_ROOT_DOC_STUBS,
# plus the separate CODING_STANDARDS step). It is NOT this set and is not
# supposed to be - it answers "what does deploy generate", this answers "what
# may an agent author". They overlap without being equal, so do not "fix" one
# to match the other. The set this one must track is token_budget's, and the
# test enforces exactly that.
ROOT_DOC_ALLOWED = frozenset(
    {
        "README.md",
        "HANDOFF.md",
        "ARCHITECTURE.md",
        "CLAUDE.md",
        "INITIAL.md",
    }
)

HARNESS_MEMORY_REASON = (
    "Durable memory does not live in Claude Code's file memory on this "
    "project. It lives in DWB.\n\n"
    "Write it through the API instead:\n"
    "  POST /api/agents/{agent_id}/memories        (a raw memory row)\n"
    "  POST /api/agents/{agent_id}/memory/append   (stock-mode projects)\n"
    "  POST /api/journal                           (a journal entry)\n\n"
    "Two memory homes drift, and the one that drifts is always the one nobody "
    "is reading, so this file is not a fallback, a cache or a second opinion. "
    "If something genuinely must live in an auto-loaded file, it is a POINTER "
    "to the DWB API and nothing more."
)

# Every filename in ROOT_DOC_ALLOWED must appear in this text. It is the whole
# user-facing surface of the rule - what an agent reads at the moment it is
# stopped - so a reason that undercounts its own allowlist hides places that
# agent is allowed to write. Asserted, not remembered: see
# test_the_reason_names_every_allowed_doc.
ROOT_DOC_REASON = (
    "New root-level docs are not a home for anything on this project. Five "
    "root docs are owned here, and this is not one of them.\n\n"
    "Write it where it will be read instead:\n"
    "  HANDOFF.md                            (project continuity, what is in flight)\n"
    "  ARCHITECTURE.md                       (system design, operational gotchas and traps)\n"
    "  INITIAL.md                            (requirements, phases, constraints, success criteria)\n"
    "  README.md                             (what this repo is and how to run it)\n"
    "  CLAUDE.md                             (standing instructions for agents in this repo)\n"
    "  docs/                                 (anything genuinely new and long-lived)\n"
    "  POST /api/agents/{agent_id}/memories  (a durable lesson)\n"
    "  POST /api/journal                     (a session episode)\n\n"
    "A root-level *.md nobody is pointed at is a second home for something "
    "that already has one, and it is the copy that goes stale. If this really "
    "is a new permanent document, say so and create it deliberately."
)


# --------------------------------------------------------------------------
# Context: everything a rule needs that is not the candidate path itself.
# --------------------------------------------------------------------------


def _harness_config_dir() -> Path:
    """Where Claude Code keeps its own state. Derived at runtime."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured)
    return Path(os.path.expanduser("~")) / ".claude"


def _real(path: Path) -> Path:
    """Normalise without requiring the path to exist.

    realpath rather than Path.resolve(strict=True): the target of a Write
    usually does NOT exist yet, and on macOS the temp directory is a symlink
    (/var -> /private/var), so comparing unresolved paths would miss a match
    that is really there.
    """
    return Path(os.path.realpath(str(path)))


def _repo_root(payload: dict) -> Path:
    """The repo this hook invocation is about.

    CLAUDE_PROJECT_DIR is set by Claude Code for hook commands and is the
    project the session is attached to, so it is preferred over the payload's
    cwd, which moves with the agent.
    """
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured:
        return _real(Path(configured))
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return _real(Path(cwd))
    return _real(Path(os.getcwd()))


def _dwb_in_use(repo_root: Path) -> bool:
    """Is DWB in use for THIS repo? Decided locally, from the repo itself.

    THE SIGNAL IS THE HOOKS BLOCK IN `<repo>/.claude/settings.json`, NOT THE
    PRESENCE OF `.dwb/`. Both were on the table. `.dwb/` loses for one concrete
    reason: it is gitignored and untracked, so a fresh clone does not have it
    and would not have it until something happened to write there - the guard
    would be silently unarmed exactly when a new agent, on a new checkout, is
    most likely to reach for harness memory. `.claude/settings.json` ships in
    the repo, and it is the thing that LOADS this script, so asking it answers
    the real question: did this repo deliberately wire DWB's hooks, or is this
    script running against an unrelated project because some user-level
    settings file loads it everywhere.

    Unreadable, missing or malformed settings all answer False - unarmed. An
    unarmed guard misses a write; an armed guard in the wrong repo denies one
    that was nobody's business, which is the failure this ticket exists to fix.
    """
    settings = repo_root / ".claude" / "settings.json"
    try:
        text = settings.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False

    try:
        parsed = json.loads(text)
        hooks = parsed.get("hooks") if isinstance(parsed, dict) else None
    except Exception:
        # Malformed JSON: fall back to the raw text. The question is only
        # whether DWB's wiring is in this file, and a broken settings.json
        # still answers it.
        return any(marker in text for marker in DWB_SETTINGS_MARKERS)

    if not isinstance(hooks, dict):
        return False
    return any(marker in json.dumps(hooks) for marker in DWB_SETTINGS_MARKERS)


class _Context:
    """Per-invocation facts. Built once, read by every rule."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.repo_root = _repo_root(payload)
        self.config_dir = _real(_harness_config_dir())
        self.armed = _dwb_in_use(self.repo_root)


# --------------------------------------------------------------------------
# Rules. Each one is a PURE PATH PREDICATE plus the reason and the mode.
# --------------------------------------------------------------------------


class _Rule:
    """One guarded class of write.

    `matches` takes an absolute, normalised candidate target and the context,
    and answers whether that path is sealed. Keeping it path-only is what lets
    one rule serve a Write (target arrives in tool_input) and a Bash command
    (target is found in the command string) without either knowing about the
    other.

    `reason` NAMES THE REPLACEMENT ROUTE. That is the contract for every rule
    in this table, not a nicety: a refusal that only says no leaves the caller
    to invent a second wrong home.

    `mode` is a Claude Code permissionDecision - "deny" or "ask".

    `tools` IS THE RULE'S SCOPE AND EVERY RULE MUST STATE IT. A path predicate
    answers "is this path sealed"; it cannot answer "is this command writing
    there", because nothing in a command string says so. For a rule whose
    whole subject is AUTHORING, that gap is fatal: Bash hands the tokenizer a
    bare `notes.md` from a `grep` exactly as it would from a heredoc, and the
    rule has no way to tell them apart. The fix is a fact about the RULE - the
    tools it applies to - not an inference about the command, which is the
    shell parsing Miles ruled out. Scoping lives here rather than inside a
    predicate so the next rule added has to declare it.
    """

    def __init__(self, name, mode, reason, matches, tools):
        self.name = name
        self.mode = mode
        self.reason = reason
        self.matches = matches
        self.tools = frozenset(tools)


def _is_harness_memory(target: Path, ctx: _Context) -> bool:
    """Inside the harness config dir, under a `memory` segment.

    Unchanged from DWB-589 apart from taking an already-normalised target.
    Scoped to memory on purpose: denying the whole config dir would also block
    settings.json and every other harness file, which is a much bigger claim
    than hard rule 2 makes.
    """
    config_dir = ctx.config_dir
    if target != config_dir and config_dir not in target.parents:
        return False
    try:
        relative = target.relative_to(config_dir)
    except ValueError:  # pragma: no cover - guarded by the check above
        return False
    return MEMORY_SEGMENT in relative.parts


def _is_new_root_doc(target: Path, ctx: _Context) -> bool:
    """A root-level *.md that does not exist yet and is not an owned one.

    CREATION ONLY. An existing root doc is edited all day by design, so the
    existence check is what keeps this rule off every HANDOFF.md update rather
    than a list of names that would have to be maintained. The named allowlist
    only covers re-creating one of the owned docs after a delete.

    The team_lead playbook has claimed since DWB-589 that a separate
    `.claude/hooks/guard-root-docs.py` ships via deploy-playbooks and enforces
    this. No such file has ever existed anywhere in the repo - the claim was
    prose with nothing behind it. This rule is that enforcement, here, where
    the PreToolUse plumbing already is.
    """
    if target.suffix.lower() != ".md":
        return False
    if target.parent != ctx.repo_root:
        return False
    if target.name in ROOT_DOC_ALLOWED:
        return False
    try:
        if target.exists():
            return False
    except OSError:
        return False
    return True


# Ordered by severity: the first rule with a matching candidate wins, so a deny
# is never shadowed by an ask found on an earlier path in the same command.
RULES = (
    # ALL FIVE TOOLS, INCLUDING BASH. Different in kind from root_doc: the
    # SEALED PATH ITSELF has to appear in the command for the command to write
    # there, and that path is specific (a harness config dir plus a `memory`
    # segment), not a bare filename that any command might mention in passing.
    # Bash is also the hole this rule was extended to close - a heredoc walked
    # through the old matcher for a full day. Do not narrow this.
    _Rule(
        "harness_memory",
        "deny",
        HARNESS_MEMORY_REASON,
        _is_harness_memory,
        WRITE_TOOLS,
    ),
    # FILE-WRITE TOOLS ONLY, NOT BASH. This rule exists to catch an agent
    # AUTHORING a new root doc, and those four tools do that unambiguously
    # while a Bash command naming a filename proves nothing about whether it
    # writes. Scoped after a read-only `grep -n "coding-standards.md"
    # docs/worker_playbook.md` put a confirmation dialog in front of the human:
    # the tokenizer lifted a bare `*.md` token, _is_new_root_doc correctly saw
    # a root-level markdown file that does not exist, and asked. The predicate
    # was right; its scope was wrong.
    _Rule(
        "root_doc",
        "ask",
        ROOT_DOC_REASON,
        _is_new_root_doc,
        FILE_WRITE_TOOLS,
    ),
)


# --------------------------------------------------------------------------
# Finding candidate targets.
# --------------------------------------------------------------------------

# A token is a run of characters that could spell a path, cut at whitespace,
# quotes and the shell metacharacters that can never appear inside an unquoted
# path. This is a tokenizer, not a shell parser: it does not know what any of
# these commands DO and never tries to work out whether one writes.
_TOKEN_RE = re.compile(r"[^\s'\"`;|&<>()=,]+")

# Characters that mean the token is not a literal path we can check.
# `$` and `{` are VARIABLE INDIRECTION and are a KNOWN UNCOVERED EDGE: a
# command that builds the sealed path into a variable first (`d=~/.claude;
# echo x > "$d/projects/p/memory/MEMORY.md"`) is not caught, by decision. The
# alternative is evaluating shell, which is the thing this script must not do.
# `*?[]` are globs - the literal token is not a path that could be compared.
_UNCHECKABLE = set("$*?[]{}")

# A command can mention a lot of tokens. Bound the work; a command that writes
# a sealed path names it long before this.
_MAX_TOKENS = 256


def _tool_input(payload: dict) -> dict:
    tool_input = payload.get("tool_input")
    return tool_input if isinstance(tool_input, dict) else {}


def _file_tool_target(payload: dict) -> str | None:
    """The first non-empty path key, exactly as DWB-589 read it."""
    tool_input = _tool_input(payload)
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _command_targets(payload: dict) -> list[str]:
    """Candidate paths named literally in a Bash command.

    THE WHOLE RULE IS: the path has to appear in the command for the command to
    write there. So lift every token that could be a path and let the same path
    predicates decide. Nothing here reads the command's meaning.
    """
    command = _tool_input(payload).get("command")
    if not isinstance(command, str) or not command:
        return []

    out = []
    for token in _TOKEN_RE.findall(command)[:_MAX_TOKENS]:
        if token.startswith("-"):
            continue  # a flag, not a path
        if _UNCHECKABLE & set(token):
            continue
        out.append(token)
    return out


def _normalise(raw: str, ctx: _Context) -> Path | None:
    """Absolute, realpath'd. Relative tokens resolve against the repo root.

    Relative resolution is against the repo root rather than a cwd tracked
    through the command, because this script does not execute `cd`. A command
    that cds elsewhere first and then writes a relative path is another
    uncovered edge of the same family as variable indirection.
    """
    try:
        expanded = os.path.expanduser(raw)
        path = Path(expanded)
        if not path.is_absolute():
            path = ctx.repo_root / path
        return _real(path)
    except Exception:
        return None


def _candidate_targets(payload: dict, ctx: _Context) -> list[Path]:
    tool = payload.get("tool_name")
    if tool in COMMAND_TOOLS:
        raws = _command_targets(payload)
    else:
        single = _file_tool_target(payload)
        raws = [single] if single else []

    targets = []
    for raw in raws:
        target = _normalise(raw, ctx)
        if target is not None:
            targets.append(target)
    return targets


# --------------------------------------------------------------------------
# Decision.
# --------------------------------------------------------------------------


def decide(payload: dict) -> _Rule | None:
    """The matching rule, or None for no opinion."""
    tool = payload.get("tool_name")
    if tool not in WRITE_TOOLS:
        return None

    ctx = _Context(payload)
    if not ctx.armed:
        # DWB is not in use for this repo. Not our business.
        return None

    targets = _candidate_targets(payload, ctx)
    if not targets:
        return None

    for rule in RULES:
        # The rule's declared scope, checked before its predicate ever runs.
        # A rule that does not apply to this tool has no opinion about it.
        if tool not in rule.tools:
            continue
        for target in targets:
            try:
                if rule.matches(target, ctx):
                    return rule
            except Exception:
                continue
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    try:
        payload = json.loads(raw)
    except Exception:
        # Not JSON, or empty. Nothing to judge; let the call through.
        return 0

    if not isinstance(payload, dict):
        return 0

    try:
        rule = decide(payload)
    except Exception:
        # Any surprise in the payload shape or the filesystem. Allow, rather
        # than wedge the session on a guess.
        return 0

    if rule is None:
        # Silence is "no opinion". Printing an allow decision would override a
        # later hook or a user's own permission settings, which is not this
        # script's business.
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": rule.mode,
                "permissionDecisionReason": rule.reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # The outermost net. A hook that raises blocks the tool call it was
        # inspecting, so there is no failure mode here worth a non-zero exit.
        sys.exit(0)

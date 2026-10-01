#!/usr/bin/env python3
# Path: scripts/hooks/block_harness_memory_writes.py
# File: block_harness_memory_writes.py
# Created: 2026-09-29 (DWB-589)
# Purpose: PreToolUse hook - deny writes into Claude Code's OWN file-based
#          memory directory and point the caller at the DWB API instead.
#          Spec section 7 hard rule 2.
# Caller: Claude Code PreToolUse hook (wired in .claude/settings.json by the TL)
# Callees: stdlib only - no DWB imports, no network, no database
# Data In: a PreToolUse hook payload as JSON on stdin
# Data Out: a permissionDecision JSON block on stdout, or nothing; always exit 0
# Last Modified: 2026-09-29 (DWB-589)

"""Deny writes to the harness's own memory store.

Spec section 7 hard rule 2, verbatim: "The harness's own file-based memory is
not used at all. It holds ONE thing: a pointer saying durable memory lives in
DWB, with the API shape. Two homes drift, and the one that drifts is always the
one nobody is reading."

WHAT THIS IS AND IS NOT. DWB can seal its OWN API, and DWB-589 does. It cannot
seal Claude Code's file memory, which belongs to the harness, so this hook is
the only available lever and it is a WEAKER one: anything that does not route
through PreToolUse goes around it. Do not describe the rule as airtight.

IT IS UNCONDITIONAL, WHICH IS BROADER THAN HARD RULE 1. Rule 1 is scoped to
projects with `human_memory` on. This hook has no project context: PreToolUse
gives it a tool name and a path, not a repo, and it has no database connection
by design (a hook that needs the API to be up would fail closed every time the
server restarts). So it denies harness-memory writes for ANY project whose
settings load it. That is deliberate and worth stating plainly rather than
discovering: hard rule 2 is itself written unconditionally, and the alternative
would be a hook that guesses which project it is in.

THE PATH IS DERIVED, NEVER HARDCODED. `CLAUDE_CONFIG_DIR` first, then `~`
expanded at runtime. DWB-574 shipped a hardcoded home directory that leaked a
real username into this repo, and this repo is cloned onto other machines.

IT ALWAYS EXITS 0. Project rule for hook scripts, and here it matters more than
usual: a PreToolUse hook that crashes blocks the tool call it was inspecting,
so a parse error on an unexpected payload would stop every Write in the session.
Failing to guard one write is far cheaper than wedging the session.
"""

import json
import os
import sys
from pathlib import Path

# The tools that can put bytes on disk. A tool added to the matcher in
# settings.json without being added here would pass through silently, which is
# why the test parametrizes over exactly this set.
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

# Keys a write tool may carry its target under. NotebookEdit uses
# `notebook_path`; the rest use `file_path`.
PATH_KEYS = ("file_path", "notebook_path", "path")

# The directory name that marks harness memory inside the config dir.
MEMORY_SEGMENT = "memory"

DENY_REASON = (
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


def _target_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_harness_memory_write(payload: dict) -> bool:
    if payload.get("tool_name") not in WRITE_TOOLS:
        return False

    raw_target = _target_path(payload)
    if raw_target is None:
        return False

    target = _real(Path(os.path.expanduser(raw_target)))
    config_dir = _real(_harness_config_dir())

    if target != config_dir and config_dir not in target.parents:
        return False

    # Inside the config dir, but only the memory directories are sealed.
    # Scoped this way on purpose: denying the whole config dir would also
    # block settings.json and every other harness file, which is a much
    # bigger claim than hard rule 2 makes.
    try:
        relative = target.relative_to(config_dir)
    except ValueError:  # pragma: no cover - guarded by the check above
        return False
    return MEMORY_SEGMENT in relative.parts


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
        blocked = _is_harness_memory_write(payload)
    except Exception:
        # Any surprise in the payload shape or the filesystem. Allow, rather
        # than wedge the session on a guess.
        return 0

    if not blocked:
        # Silence is "no opinion". Printing an allow decision would override a
        # later hook or a user's own permission settings, which is not this
        # script's business.
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": DENY_REASON,
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

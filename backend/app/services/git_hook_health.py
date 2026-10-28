# Path: app/services/git_hook_health.py
# File: git_hook_health.py
# Created: 2026-10-28
# Purpose: Tell UNARMED apart from QUIET (DWB-695) - is this project's post-commit hook actually installed
# Caller: app/routers/projects.py (GET /api/projects/{id}/hook-status)
# Callees: app/services/code_pointers (effective_hooks_dir, git_config_value, _repo_ok), app/services/commit_record (coverage_start)
# Data In: db: Session, Project
# Data Out: dict - armed (True/False/None), state, silence_means, commit_rows
# Last Modified: 2026-10-28

"""DWB-695: the defect is not that a clone needs one local action. It is that
"nobody committed" and "nothing was ever installed" are the SAME OBSERVATION
from inside DWB.

A hook that was never installed produces exactly the silence of a hook that is
installed and has nothing to report. That is how this repository went twelve
days with an orphaned uvicorn worker and no commit ever reaching the database,
with every read returning 200 throughout.

THIS MODULE ANSWERS THE QUESTION DIRECTLY RATHER THAN INFERRING IT FROM
SILENCE. Installation is a filesystem fact at `project.repo_path`, so it can be
read, and once it is read, zero commit rows stops being ambiguous.

THE VERDICT IS THREE-VALUED, matching `gate-status`'s convention (see CLAUDE.md
on `all_passing`): True armed, False unarmed, and None meaning COULD NOT
ANSWER - no repo_path, or a path this machine cannot read. None is falsy, so a
caller that writes `if armed` lands on the safe reading. A caller that wants to
act on "unarmed" must test `is False`, which is the point: "we could not look"
must never be reported as "it is off".

WHY `core.hooksPath` GETS ITS OWN FLAG. It REPLACES the hooks directory rather
than adding to it, so setting it to a directory with no post-commit switches
off `.git/hooks` as well. The result is a repository that looks configured, has
eleven untouched sample hooks sitting beside it, and runs nothing. That is the
worst state here because it is the one most likely to be mistaken for progress,
so it is named rather than folded into "no hook".
"""

import logging
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.commit import Commit
from app.models.project import Project
from app.services import code_pointers

logger = logging.getLogger(__name__)

# What makes a post-commit hook OURS. Deliberately the endpoint it posts to and
# not the shipped file's name or a symlink target: an operator may legitimately
# copy the script instead of linking it, or fold the POST into an existing
# hook of their own. What decides the question is whether DWB gets told, and
# this string is the only part of the script that carries that.
DWB_HOOK_MARKER = "/api/hooks/post-commit"

STATE_ARMED = "armed"
STATE_NO_HOOK = "no_hook"
STATE_NOT_EXECUTABLE = "hook_not_executable"
STATE_FOREIGN_HOOK = "foreign_hook"
STATE_NO_REPO_PATH = "unknown_no_repo_path"
STATE_REPO_UNREADABLE = "unknown_repo_unreadable"


def hook_status(db: Session, project: Project) -> dict:
    """Is this project's post-commit hook installed, and what does its silence
    mean?

    Never raises: a caller is a status endpoint and an unreadable path is an
    answer ("could not look"), not an error.
    """
    result: dict = {
        "project_id": project.id,
        "repo_path": project.repo_path,
        "armed": None,
        "state": None,
        "hooks_dir": None,
        "hooks_path_override": None,
        "hooks_path_overrides_default": False,
        "hook_file": None,
        "commit_rows": 0,
        "last_commit_at": None,
        "silence_means": None,
    }

    try:
        rows = db.scalar(
            select(func.count(Commit.id)).where(Commit.project_id == project.id)
        )
        result["commit_rows"] = int(rows or 0)
        last = db.scalar(
            select(Commit.committed_at)
            .where(Commit.project_id == project.id)
            .order_by(Commit.committed_at.desc())
            .limit(1)
        )
        result["last_commit_at"] = last

        if not project.repo_path:
            result["state"] = STATE_NO_REPO_PATH
            return _with_reading(result)

        if not code_pointers._repo_ok(project.repo_path):
            result["state"] = STATE_REPO_UNREADABLE
            return _with_reading(result)

        override = code_pointers.git_config_value(project.repo_path, "core.hooksPath")
        result["hooks_path_override"] = override
        # A set override is load-bearing on its own: `.git/hooks` is OFF from
        # this moment whether or not the new directory contains anything.
        result["hooks_path_overrides_default"] = override is not None

        hooks_dir = code_pointers.effective_hooks_dir(project.repo_path)
        result["hooks_dir"] = hooks_dir
        if not hooks_dir:
            result["state"] = STATE_REPO_UNREADABLE
            return _with_reading(result)

        hook = Path(hooks_dir) / "post-commit"
        result["hook_file"] = str(hook)

        if not hook.exists():
            result["armed"] = False
            result["state"] = STATE_NO_HOOK
            return _with_reading(result)

        # Git SILENTLY SKIPS a non-executable hook. It prints a hint to the
        # committer's terminal, which never reaches DWB, so from here this is
        # indistinguishable from no hook at all unless it is named.
        if not os.access(hook, os.X_OK):
            result["armed"] = False
            result["state"] = STATE_NOT_EXECUTABLE
            return _with_reading(result)

        try:
            body = hook.read_text(errors="replace")
        except OSError:
            body = ""
        if DWB_HOOK_MARKER not in body:
            # A hook runs, but not one that tells DWB anything.
            result["armed"] = False
            result["state"] = STATE_FOREIGN_HOOK
            return _with_reading(result)

        result["armed"] = True
        result["state"] = STATE_ARMED
        return _with_reading(result)
    except Exception:
        logger.exception("hook_status failed for project_id=%s", project.id)
        result["armed"] = None
        result["state"] = STATE_REPO_UNREADABLE
        return _with_reading(result)


def _with_reading(result: dict) -> dict:
    """Attach the sentence that resolves the ambiguity.

    THIS FIELD IS THE WHOLE POINT OF THE MODULE. Everything above is evidence;
    this is the reading, written out so a caller does not have to re-derive it
    and get it subtly wrong. "Zero commit rows" means four different things
    depending on the state beside it, and only one of them is about the work.
    """
    armed = result["armed"]
    rows = result["commit_rows"]
    state = result["state"]

    if armed is None:
        result["silence_means"] = (
            "CANNOT SAY. DWB could not look at this repository "
            f"({state}), so no conclusion about commits is available - "
            "absence of commit rows is not evidence of anything here."
        )
    elif armed is False:
        detail = {
            STATE_NO_HOOK: "there is no post-commit hook in the directory git uses",
            STATE_NOT_EXECUTABLE: (
                "a post-commit hook exists but is not executable, so git skips "
                "it without telling DWB"
            ),
            STATE_FOREIGN_HOOK: (
                "a post-commit hook exists and runs, but it does not report to "
                "DWB"
            ),
        }.get(state, state)
        override_note = ""
        if result["hooks_path_overrides_default"]:
            override_note = (
                f" core.hooksPath is set to {result['hooks_path_override']!r}, "
                "which also DISABLES .git/hooks - any sample or hook sitting "
                "there is ignored."
            )
        result["silence_means"] = (
            f"UNARMED: {detail}.{override_note} "
            f"{rows} commit row(s) stored. Zero here would be explained by the "
            "hook, not by the work: do not read it as 'nothing was committed'."
        )
    elif rows == 0:
        result["silence_means"] = (
            "ARMED AND QUIET: the hook is installed and reports to DWB, and no "
            "commit has been recorded yet. Zero here IS about the work."
        )
    else:
        result["silence_means"] = (
            f"ARMED AND REPORTING: {rows} commit row(s) stored, most recent "
            f"{result['last_commit_at']}."
        )
    return result

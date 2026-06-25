# Path: app/services/session_work_record.py
# File: session_work_record.py
# Created: 2026-06-25
# Purpose: DWBG-013 — assemble a compact, AGENT-ONLY "work record" for a DWB session
#          window [opened_at, COALESCE(closed_at, now)]. PRIMARY evidence is git
#          commits + bounded unified diffs over the window (yields code symbols +
#          file:line); plus tool_actions file targets, tickets closed in window, and
#          a bounded agent/tool-only transcript slice for "why". Consumed by the
#          DWBG-014 summarizer. NEVER includes user-typed prompt text (DWB-351/DWBG-003).
# Caller: app/services/session_narrative.py (DWBG-014 summarizer)
# Callees: app.models.dwb_session, app.models.project, app.models.ticket,
#          app.models.tool_action, app.models.hook_session, app.models.agent,
#          subprocess (git, read-only against the project repo)
# Data In: SQLAlchemy Session + a DwbSession instance (+ optional now for the window end)
# Data Out: dict — the structured work record (see WORK RECORD CONTRACT below)
# Last Modified: 2026-06-25

"""DWBG-013 — session work-record evidence gatherer.

``build_work_record(db, session)`` assembles a structured, bounded, AGENT-ONLY
record of what happened during a DWB session window. The summarizer (DWBG-014)
feeds this to the Claude API to produce the human-readable wrap-up narrative.

PRIVACY (HARD RULE, DWB-351 / DWBG-003): nothing user-typed is gathered. Git
commits + diffs are authored by agents; tool_actions, tickets, and the transcript
slice are filtered to agent/tool turns only. The transcript reader explicitly
SKIPS any ``role: "user"`` / ``type: "user"`` entries.

PRIMARY evidence = git. The unified diff over [opened_at, win_end] is what yields
concrete code symbols (``fetchCFCRRawData()``) and file:line references
(``DataManipulation.php:21``) that ground the narrative in real specifics. Diff
size is bounded (per-file and total line caps) so the LLM prompt stays small;
truncation is recorded so the summarizer can note it honestly.

WORK RECORD CONTRACT (output dict; the summarizer degrades gracefully on any
missing field):

    {
      "session_id": int,
      "project": {"name": str, "prefix": str | None, "repo_path": str | None},
      "window": {"start": iso8601, "end": iso8601, "live": bool},
      "totals": {"total_tokens": int, "total_time_seconds": int},

      # PRIMARY: git over the window. repo_available is False when there is no
      # repo_path or git is unavailable/errors (the gatherer never raises).
      "git": {
        "repo_available": bool,
        "commits": [{"sha": str, "author": str, "date": iso8601, "subject": str}],
        "diff": str,                 # bounded unified diff (may be "")
        "diff_truncated": bool,
        "files_changed": [str],      # paths touched across the window
        "note": str | None,         # e.g. "diff truncated to N lines" / why unavailable
      },

      # tool_actions linked to this dwb_session — file-edit targets (DWB-417+).
      "tool_actions": [{"tool_name": str, "event_type": str, "target": str | None}],

      # tickets completed in the window (key + title) — names for the narrative.
      "tickets_completed": [{"ticket_key": str, "title": str}],

      # BOUNDED transcript slice — agent/tool turns only, never user prompts.
      "transcript_excerpt": str,     # may be "" when no transcript / nothing safe
      "transcript_truncated": bool,
    }
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.dwb_session import DwbSession
from app.models.hook_session import HookSession
from app.models.project import Project
from app.models.ticket import Ticket
from app.models.tool_action import ToolAction

logger = logging.getLogger(__name__)

# Size bounds — keep the LLM prompt small and the run cheap. The diff is the
# expensive part, so cap both per-file and total lines; the transcript slice is
# capped by character count after user-prompt filtering.
_MAX_DIFF_LINES = 1200
_MAX_DIFF_LINES_PER_FILE = 200
_MAX_COMMITS = 60
_MAX_TOOL_ACTIONS = 80
_MAX_TRANSCRIPT_CHARS = 12000
_GIT_TIMEOUT_SECONDS = 20

# Date format git understands for --since/--until window bounds. The window
# datetimes are naive UTC (DwbSession columns are naive UTC), so we append a
# +0000 offset to make git interpret the bounds in UTC rather than the host's
# local timezone — otherwise a window built in UTC silently misses commits whose
# author date git read as local time.
_GIT_DATE_FMT = "%Y-%m-%dT%H:%M:%S+0000"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _window_end(session: DwbSession, now: datetime | None) -> tuple[datetime, bool]:
    """Return (end, live). Closed sessions freeze at closed_at; open sessions
    end at now (caller-supplied for tests, else server clock)."""
    if session.closed_at is not None:
        return session.closed_at, False
    return (now or _utcnow()), True


def _run_git(repo_path: str, args: list[str]) -> tuple[bool, str]:
    """Run a read-only git command in repo_path. Returns (ok, stdout). Never
    raises — any failure (no repo, git missing, timeout, non-zero exit) returns
    (False, ""). The work record is best-effort evidence, not a hard dependency."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    if result.returncode != 0:
        return False, ""
    return True, result.stdout


def _gather_git(
    repo_path: str | None, win_start: datetime, win_end: datetime
) -> dict:
    """Collect commits + a bounded unified diff over the window. PRIMARY evidence.

    Uses --since/--until on the wall-clock window. The diff is bounded two ways:
    a per-file line cap (so one huge generated file can't dominate) and a total
    line cap; truncation is recorded in `note` + `diff_truncated`."""
    out: dict = {
        "repo_available": False,
        "commits": [],
        "diff": "",
        "diff_truncated": False,
        "files_changed": [],
        "note": None,
    }
    if not repo_path:
        out["note"] = "no repo_path configured for project"
        return out
    if not Path(repo_path).is_dir():
        out["note"] = f"repo_path does not exist: {repo_path}"
        return out

    since = win_start.strftime(_GIT_DATE_FMT)
    until = win_end.strftime(_GIT_DATE_FMT)

    # Confirm it's a git repo at all (cheap probe).
    ok, _ = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    if not ok:
        out["note"] = "not a git repository (or git unavailable)"
        return out
    out["repo_available"] = True

    # Commits in window. %x1f (unit separator) keeps subjects with spaces safe.
    ok, log_out = _run_git(
        repo_path,
        [
            "log",
            f"--since={since}",
            f"--until={until}",
            "--no-merges",
            f"--max-count={_MAX_COMMITS}",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%an%x1f%ad%x1f%s",
        ],
    )
    commits: list[dict] = []
    if ok and log_out.strip():
        for line in log_out.strip().splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                sha, author, date, subject = parts
                commits.append(
                    {"sha": sha[:12], "author": author, "date": date, "subject": subject}
                )
    out["commits"] = commits

    # Files changed across the window (deduped, ordered).
    ok, names_out = _run_git(
        repo_path,
        ["log", f"--since={since}", f"--until={until}", "--no-merges",
         "--name-only", "--pretty=format:"],
    )
    files: list[str] = []
    if ok:
        seen: set[str] = set()
        for line in names_out.splitlines():
            f = line.strip()
            if f and f not in seen:
                seen.add(f)
                files.append(f)
    out["files_changed"] = files

    # The diff itself — combined patch for the commits in the window. We diff the
    # window's commit range rather than the working tree so it reflects what was
    # actually committed during the session. -U2 keeps context tight.
    diff_text, truncated, note = _gather_diff(repo_path, since, until)
    out["diff"] = diff_text
    out["diff_truncated"] = truncated
    if note:
        out["note"] = note
    return out


def _gather_diff(
    repo_path: str, since: str, until: str
) -> tuple[str, bool, str | None]:
    """Build a bounded unified diff for commits in the window.

    Walks each file's hunk and applies a per-file line cap, then a global cap.
    Returns (diff_text, truncated, note)."""
    # Resolve the commit range: oldest..newest in the window. We use the boundary
    # commits so `git diff A^..B` captures everything committed in the span.
    ok, shas_out = _run_git(
        repo_path,
        ["log", f"--since={since}", f"--until={until}", "--no-merges",
         "--pretty=format:%H"],
    )
    shas = [s for s in shas_out.splitlines() if s.strip()] if ok else []
    if not shas:
        return "", False, None

    newest, oldest = shas[0], shas[-1]
    # `oldest^..newest` includes the oldest commit's changes too. If oldest has
    # no parent (root commit), fall back to a diff against the empty tree.
    ok, diff_out = _run_git(
        repo_path,
        ["diff", "-U2", "--no-color", f"{oldest}^..{newest}"],
    )
    if not ok:
        # Root-commit fallback: diff the full range against the empty tree.
        empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        ok, diff_out = _run_git(
            repo_path, ["diff", "-U2", "--no-color", empty_tree, newest]
        )
        if not ok:
            return "", False, "git diff failed for window range"

    return _bound_diff(diff_out)


def _bound_diff(diff_out: str) -> tuple[str, bool, str | None]:
    """Apply per-file and total line caps to a raw unified diff. Returns
    (bounded_text, truncated, note)."""
    if not diff_out:
        return "", False, None

    lines = diff_out.splitlines()
    kept: list[str] = []
    truncated = False
    per_file_count = 0
    total_count = 0

    for line in lines:
        if line.startswith("diff --git "):
            per_file_count = 0  # reset the per-file budget at each file header
        if total_count >= _MAX_DIFF_LINES:
            truncated = True
            break
        if line.startswith("diff --git ") or per_file_count < _MAX_DIFF_LINES_PER_FILE:
            kept.append(line)
            per_file_count += 1
            total_count += 1
        else:
            # This file's budget is spent; mark and skip until the next file.
            truncated = True

    note = None
    if truncated:
        note = (
            f"diff truncated to ~{_MAX_DIFF_LINES} lines "
            f"({_MAX_DIFF_LINES_PER_FILE}/file) to bound prompt size"
        )
    return "\n".join(kept), truncated, note


def _gather_tool_actions(db: Session, session: DwbSession) -> list[dict]:
    """tool_actions (DWB-417+) linked to this dwb_session — file-edit targets and
    the like. Agent-produced by construction (captured from the PostToolUse hook)."""
    rows = db.execute(
        select(ToolAction)
        .where(ToolAction.dwb_session_id == session.id)
        .order_by(ToolAction.created_at.asc())
        .limit(_MAX_TOOL_ACTIONS)
    ).scalars().all()
    return [
        {"tool_name": r.tool_name, "event_type": r.event_type, "target": r.target}
        for r in rows
    ]


def _gather_tickets_completed(
    db: Session, session: DwbSession, win_start: datetime, win_end: datetime
) -> list[dict]:
    """Tickets completed in the window (key + title) — gives the narrative real
    names to reference. Filters on completed_at (the timestamp), not status, so a
    later reopen doesn't rewrite what this session shipped."""
    rows = db.execute(
        select(Ticket.ticket_key, Ticket.title)
        .where(Ticket.project_id == session.project_id)
        .where(Ticket.completed_at.isnot(None))
        .where(Ticket.completed_at >= win_start)
        .where(Ticket.completed_at <= win_end)
        .order_by(Ticket.completed_at.asc())
    ).all()
    return [{"ticket_key": k, "title": t} for k, t in rows if k]


# Keys whose presence marks a transcript entry as user-authored. Belt-and-
# suspenders: we drop the entry if ANY of these signal a user turn.
_USER_ROLE_VALUES = {"user", "human"}


def _gather_transcript_excerpt(
    db: Session, session: DwbSession
) -> tuple[str, bool]:
    """Read a BOUNDED slice of a linked hook_session transcript for 'why' context.

    AGENT/TOOL TURNS ONLY (DWB-351 / DWBG-003): every entry whose role/type marks
    it as user-authored is SKIPPED. The transcript is a JSONL file; we parse line
    by line and keep only assistant/tool text up to a char cap. Best-effort — any
    read/parse error yields ("", False) rather than raising.

    Returns (excerpt, truncated)."""
    transcript_path = db.execute(
        select(HookSession.transcript_path)
        .where(HookSession.dwb_session_id == session.id)
        .where(HookSession.transcript_path.isnot(None))
        .order_by(HookSession.start_time.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not transcript_path:
        return "", False
    path = Path(transcript_path)
    if not path.is_file():
        return "", False

    pieces: list[str] = []
    total = 0
    truncated = False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(entry, dict):
                    continue
                text = _safe_agent_text(entry)
                if not text:
                    continue
                if total + len(text) > _MAX_TRANSCRIPT_CHARS:
                    pieces.append(text[: _MAX_TRANSCRIPT_CHARS - total])
                    truncated = True
                    break
                pieces.append(text)
                total += len(text)
    except OSError:
        return "", False

    return "\n".join(pieces), truncated


def _safe_agent_text(entry: dict) -> str | None:
    """Return agent/tool text from one transcript entry, or None if the entry is
    user-authored or carries no usable text. HARD privacy filter: any user/human
    role drops the entry entirely (DWB-351 / DWBG-003)."""
    # Common transcript shapes carry the speaker in `role` and/or `type`.
    role = str(entry.get("role") or entry.get("type") or "").lower()
    if role in _USER_ROLE_VALUES:
        return None
    # Some shapes nest the actual message under `message`.
    msg = entry.get("message")
    if isinstance(msg, dict):
        nested_role = str(msg.get("role") or "").lower()
        if nested_role in _USER_ROLE_VALUES:
            return None
        content = msg.get("content")
    else:
        content = entry.get("content") or entry.get("text")

    return _flatten_content(content)


def _flatten_content(content) -> str | None:
    """Flatten a transcript `content` value (str | list of blocks) to plain text.
    Skips non-text blocks (tool_use/tool_result inputs can be large/noisy)."""
    if content is None:
        return None
    if isinstance(content, str):
        s = content.strip()
        return s or None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Anthropic-style content blocks: {"type": "text", "text": "..."}.
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        joined = " ".join(p.strip() for p in parts if p and p.strip())
        return joined or None
    return None


def build_work_record(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> dict:
    """Assemble the structured work record for a DWB session window (DWBG-013).

    Pure data assembly + read-only git; never raises (the summarizer is
    best-effort and must never block a close). See the WORK RECORD CONTRACT in
    the module docstring for the output shape."""
    win_end, live = _window_end(session, now)
    win_start = session.opened_at

    project = db.get(Project, session.project_id)
    repo_path = project.repo_path if project else None

    git = _gather_git(repo_path, win_start, win_end)
    transcript_excerpt, transcript_truncated = _gather_transcript_excerpt(db, session)

    return {
        "session_id": session.id,
        "project": {
            "name": project.name if project else "",
            "prefix": project.prefix if project else None,
            "repo_path": repo_path,
        },
        "window": {
            "start": win_start.isoformat(),
            "end": win_end.isoformat(),
            "live": live,
        },
        "totals": {
            "total_tokens": int(session.total_tokens or 0),
            "total_time_seconds": int(session.total_time_seconds or 0),
        },
        "git": git,
        "tool_actions": _gather_tool_actions(db, session),
        "tickets_completed": _gather_tickets_completed(
            db, session, win_start, win_end
        ),
        "transcript_excerpt": transcript_excerpt,
        "transcript_truncated": transcript_truncated,
    }


def has_evidence(work_record: dict) -> bool:
    """True when the record carries enough signal to be worth a narrative run.
    A record with no commits, no tool actions, no completed tickets, and no
    transcript is not worth an LLM call (and would yield a hollow narrative)."""
    git = work_record.get("git") or {}
    return bool(
        git.get("commits")
        or git.get("diff")
        or work_record.get("tool_actions")
        or work_record.get("tickets_completed")
        or work_record.get("transcript_excerpt")
    )

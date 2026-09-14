# Path: app/services/recap.py
# File: recap.py
# Created: 2026-09-14
# Purpose: Auto-generated sprint recap draft (DWB-512). Sweeps a time window over closed/worked tickets, DWB session headlines, git/PR activity, and tl-channel traffic, then renders a markdown draft in the Sprint Warehouse post format (TL-channel #245). Draft is assembled ONLY from live queried data - it invents no claims.
# Caller: app/routers/projects.py (GET /{id}/recap-draft)
# Callees: app/models (Ticket, DwbSession, Sprint, TlMessage), git via subprocess
# Data In: db Session, Project, window_days
# Data Out: dict {window meta, counts, draft markdown string}
# Last Modified: 2026-09-14

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dwb_session import DwbSession
from app.models.sprint import Sprint, SprintStatus
from app.models.ticket import Ticket, TicketStatus
from app.models.tl_message import TlMessage

# A DWB-style internal ticket key: 2-10 uppercase/digit prefix, hyphen, digits
# (DWB-512, CI-638, IND-40). These are internal and must NEVER appear in the
# human-facing recap per TL-channel #245. Jira keys and PR numbers are allowed,
# but the tl-channel + DWB tables this recap reads from carry only internal
# keys, so a blanket scrub of this pattern is safe here.
_INTERNAL_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")

# A pull-request number as it appears in a merge-commit subject
# ("Merge pull request #3 from ...").
_PR_RE = re.compile(r"#(\d+)")

# Statuses that count as "still open" for the THIS SPRINT GOALS section.
_OPEN_STATUSES = (
    TicketStatus.todo,
    TicketStatus.in_progress,
    TicketStatus.in_review,
)


def _scrub(text: str | None) -> str:
    """Strip internal ticket keys and collapse whitespace for human output."""
    if not text:
        return ""
    # No em/en dashes in the human-facing recap (#245): normalize to a hyphen.
    cleaned = text.replace("—", "-").replace("–", "-")
    cleaned = _INTERNAL_KEY_RE.sub("", cleaned)
    # Collapse the whitespace/punctuation left where a key was removed.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.:;])", r"\1", cleaned)
    return cleaned.strip(" -:;,")


def _git_lines(repo_path: str, args: list[str]) -> list[str]:
    """Run a git command in repo_path and return non-empty stdout lines.

    Any failure (not a git repo, git missing, timeout) returns [] so the recap
    degrades to "no git activity" rather than erroring the endpoint.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _sweep_git(repo_path: str | None, window_start: datetime) -> dict:
    """Return {commit_count, pr_numbers} for commits since window_start."""
    result = {"commit_count": 0, "pr_numbers": []}
    if not repo_path:
        return result
    path = Path(repo_path)
    if not path.exists():
        return result
    since = window_start.strftime("%Y-%m-%d %H:%M:%S")
    commits = _git_lines(repo_path, ["log", f"--since={since}", "--oneline", "--no-merges"])
    result["commit_count"] = len(commits)
    merges = _git_lines(
        repo_path, ["log", f"--since={since}", "--oneline", "--merges"]
    )
    seen: list[str] = []
    for line in merges:
        for num in _PR_RE.findall(line):
            if num not in seen:
                seen.append(num)
    result["pr_numbers"] = seen
    return result


def build_recap_draft(
    db: Session,
    project,
    window_days: int = 14,
    now: datetime | None = None,
) -> dict:
    """Assemble a sprint-recap draft for one project over a trailing window.

    Everything in the returned draft comes from live queried data: closed/worked
    tickets, DWB session headlines, git/PR activity where a repo_path exists, and
    this project's tl-channel traffic in the window. No claim is invented; empty
    sweeps render as empty sections rather than filler. Format follows the Sprint
    Warehouse post rules (TL-channel #245): project headline + terse bullets
    biggest-first, THIS SPRINT GOALS with carries labeled "(carried)", plain
    markdown, hyphens not em dashes, no icons, and no internal ticket keys.
    """
    now = now or datetime.utcnow()
    window_start = now - timedelta(days=window_days)

    tickets = (
        db.execute(select(Ticket).where(Ticket.project_id == project.id))
        .scalars()
        .all()
    )

    def _touched_at(t: Ticket) -> datetime:
        return t.completed_at or t.updated_at

    closed = [
        t
        for t in tickets
        if t.status == TicketStatus.done and _touched_at(t) >= window_start
    ]
    # Biggest first: use attributed tokens as a size proxy, newest as tiebreak.
    closed.sort(key=lambda t: (t.tokens_used or 0, _touched_at(t)), reverse=True)

    worked = [
        t
        for t in tickets
        if t.status in (TicketStatus.in_progress, TicketStatus.in_review)
        and t.updated_at >= window_start
    ]

    open_tickets = [t for t in tickets if t.status in _OPEN_STATUSES]
    # A goal carried over is one that existed before the window opened and is
    # still not done. Newest-created first so fresh goals lead.
    open_tickets.sort(key=lambda t: t.created_at, reverse=True)

    sessions = (
        db.execute(
            select(DwbSession)
            .where(DwbSession.project_id == project.id)
            .where(DwbSession.opened_at >= window_start)
            .where(DwbSession.headline.isnot(None))
            .order_by(DwbSession.opened_at.desc())
        )
        .scalars()
        .all()
    )

    active_sprint = (
        db.execute(
            select(Sprint)
            .where(Sprint.project_id == project.id)
            .where(Sprint.status == SprintStatus.active)
        )
        .scalars()
        .first()
    )

    tl_messages = (
        db.execute(
            select(TlMessage)
            .where(TlMessage.from_project_id == project.id)
            .where(TlMessage.created_at >= window_start)
            .order_by(TlMessage.created_at.desc())
        )
        .scalars()
        .all()
    )

    git = _sweep_git(project.repo_path, window_start)
    pr_numbers = git["pr_numbers"]

    # --- Compose the markdown draft ---
    headline_bits = []
    if closed:
        headline_bits.append(f"{len(closed)} closed")
    if pr_numbers:
        headline_bits.append(f"{len(pr_numbers)} PRs merged")
    if worked:
        headline_bits.append(f"{len(worked)} in flight")
    headline = ", ".join(headline_bits) if headline_bits else "quiet window"

    lines: list[str] = []
    lines.append(f"**{project.name} - {headline}**")
    for t in closed:
        title = _scrub(t.title)
        if title:
            lines.append(f"- {title}")
    if pr_numbers:
        joined = ", ".join(f"#{n}" for n in pr_numbers)
        lines.append(f"- Merged PRs: {joined}")
    elif git["commit_count"]:
        lines.append(f"- {git['commit_count']} commits landed in the window")
    for s in sessions[:5]:
        h = _scrub(s.headline)
        if h:
            lines.append(f"- Session: {h}")
    if len(lines) == 1:
        lines.append("- No closed tickets, PRs, or sessions in the window")

    lines.append("")
    lines.append("**THIS SPRINT GOALS**")
    theme = _scrub(active_sprint.goal) if active_sprint and active_sprint.goal else ""
    if active_sprint:
        theme_label = theme or active_sprint.name
        lines.append(f"**{project.name} - {theme_label}**")
    else:
        lines.append(f"**{project.name}**")
    if open_tickets:
        for t in open_tickets:
            title = _scrub(t.title)
            if not title:
                continue
            carried = " (carried)" if t.created_at < window_start else ""
            lines.append(f"- {title}{carried}")
    else:
        lines.append("- No open tickets")

    lines.append("")
    lines.append("**WORKFLOW**")
    if tl_messages:
        for m in tl_messages[:5]:
            first_line = _scrub(m.body.splitlines()[0] if m.body else "")
            if first_line:
                lines.append(f"- {first_line}")
    else:
        lines.append("- No team-lead channel traffic in the window")

    lines.append("")
    lines.append("**PERSONAL**")
    lines.append("- (carry from previous post)")

    draft = "\n".join(lines)

    return {
        "project_id": project.id,
        "project_name": project.name,
        "window_days": window_days,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "generated_at": now.isoformat(),
        "format_source": "tl-channel #245 (Sprint Warehouse post); "
        "no #250 specimen on channel at build time",
        "counts": {
            "tickets_closed": len(closed),
            "tickets_worked": len(worked),
            "tickets_open": len(open_tickets),
            "prs_merged": len(pr_numbers),
            "commits": git["commit_count"],
            "sessions": len(sessions),
            "tl_messages": len(tl_messages),
        },
        "draft": draft,
    }

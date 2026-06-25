# Path: scripts/seed_showcase_session.py
# File: seed_showcase_session.py
# Created: 2026-06-25
# Purpose: Seed ONE contrived, fully-loaded DWB session that showcases every
#          Session Recall feature at once (DWBG-025): a hand-crafted narrative with
#          real repo-relative file:line refs + real commit shas (clickable via
#          DWBG-022) and code chips, weighted keywords (search/DWBG-011), linked
#          hook_sessions (by_role), and tracking_log events (by_ticket + overhead).
#          For demos — NOT real work data. Idempotent on a sentinel headline.
# Caller: manual — PYTHONPATH=. .venv/bin/python scripts/seed_showcase_session.py
# Callees: app.database.SessionLocal, app.models.{dwb_session,hook_session,tracking_log,entity_keyword,ticket}
# Data In: none (hardcoded showcase content; real refs verified against the repo)
# Data Out: one dwb_session (+ hooks, tracking_log, entity_keywords) on project 2
# Last Modified: 2026-06-25

"""Seed a single showcase DWB session that exercises the whole recall layer."""

from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.dwb_session import (
    DwbCloseMethod, DwbCloseReason, DwbOpenMethod, DwbSession,
)
from app.models.entity_keyword import EntityKeyword
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.ticket import Ticket
from app.models.tracking_log import TrackingLog

PROJECT_ID = 2
SENTINEL = "Showcase: full Session Recall Layer demo"

# Anchor to "now" so the showcase is always the most-recent session — it tops the
# Recall feed and the per-project list instead of sorting under real sessions.
# (Naive UTC to match the DB DATETIME columns / the app's utcnow convention.)
OPENED = datetime.utcnow().replace(microsecond=0)
CLOSED = OPENED + timedelta(minutes=30)

# (agent_id, role-ish session_type, tokens). Real project-2 roster: Archie(6)=TL,
# Devin(7)=backend, Freddie(8)=frontend — drives by_role + agents_active.
HOOKS = [(6, HookSessionType.main, 32000), (7, HookSessionType.teammate, 88000),
         (8, HookSessionType.teammate, 44000)]

# by_ticket: real DWBG ticket keys (looked up to ids) -> (agent_id, tokens).
TICKET_WORK = {"DWBG-014": (7, 40000), "DWBG-010": (7, 28000), "DWBG-022": (8, 22000)}

# entity_keywords -> search ranking + chips (DWBG-011 / DWBG-493).
KEYWORDS = [("narrative", 9), ("recall", 8), ("ollama", 7), ("provider", 7),
            ("search", 6), ("fulltext", 5), ("summarizer", 5), ("wrap-up", 4),
            ("clickable", 3), ("keywords", 3)]

# Hand-crafted narrative. BARE paths/shas (no backticks) -> clickable links via
# DWBG-022; backticked symbols -> non-clickable code chips. Paths + shas are real.
NARRATIVE = {
    "lead": "Showcase: the full Session Recall Layer, end to end — local wrap-ups, cross-project search, and clickable evidence.",
    "sections": [
        {"title": "What this session demonstrates", "bullets": [
            "On close, a narrative is synthesized and persisted to the column added in backend/app/models/dwb_session.py:141, then rendered by the SessionSummary component.",
            "The summarizer is pluggable behind `NarrativeProvider` (see backend/app/services/summarizer_providers/ollama.py), with Ollama as the local default via `get_provider()` — your diffs never leave the machine.",
            "Clickable evidence shipped in commit d6dc65f, backed by the project `repo_url` exposed in commit 9dff148: the file refs below open in GitHub and a sha opens its diff.",
        ]},
        {"title": "Search and recall", "bullets": [
            "Cross-project search ranks this session via FULLTEXT plus the entity_keywords substrate — try querying ollama, recall, or provider on the Recall page at frontend/src/pages/SessionRecallPage.jsx.",
            "The `force_session_writeup` project gate controls auto-generation on close (default on).",
        ]},
        {"title": "Caveat", "bullets": [
            "This is a CONTRIVED showcase session seeded for demos — the token counts, timings, and ticket attributions are illustrative, not a real work record. The file paths and commit shas, however, are real and clickable.",
        ]},
    ],
}


def main() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(DwbSession).where(DwbSession.project_id == PROJECT_ID,
                                               DwbSession.headline == SENTINEL)):
            print("Showcase session already exists; aborting (idempotent). Delete it to re-seed.")
            return

        total = sum(t for _, _, t in HOOKS)
        s = DwbSession(
            project_id=PROJECT_ID, opened_at=OPENED, closed_at=CLOSED,
            open_method=DwbOpenMethod.regex, open_phrase="open a dwb session",
            close_method=DwbCloseMethod.ai_confident, close_reason=DwbCloseReason.explicit,
            headline=SENTINEL, summary={"lead": SENTINEL, "sections": [
                {"title": "Tickets", "bullets": ["3 worked: DWBG-014, DWBG-010, DWBG-022"]},
                {"title": "Cost", "bullets": [f"{total:,} tokens across {len(HOOKS)} agents"]}]},
            narrative=NARRATIVE, narrative_author="summarizer", narrative_generated_at=CLOSED,
            total_tokens=total, total_time_seconds=int((CLOSED - OPENED).total_seconds()),
            created_at=OPENED, updated_at=CLOSED,
        )
        db.add(s); db.flush()

        # resolve real ticket ids by key
        tid_by_key = {k: db.scalar(select(Ticket.id).where(Ticket.project_id == PROJECT_ID,
                                                            Ticket.ticket_key == k))
                      for k in TICKET_WORK}
        # one ticket per agent so worker hooks aren't counted as ad_hoc
        agent_ticket = {7: tid_by_key.get("DWBG-014"), 8: tid_by_key.get("DWBG-022")}

        for aid, stype, tokens in HOOKS:
            db.add(HookSession(session_id=f"showcase-{s.id}-a{aid}", project_id=PROJECT_ID,
                               agent_id=aid, dwb_session_id=s.id, ticket_id=agent_ticket.get(aid),
                               start_time=OPENED, end_time=CLOSED, total_tokens=tokens,
                               status=HookSessionStatus.completed, session_type=stype,
                               hook_event="SessionEnd", created_at=CLOSED))

        # by_ticket: token_report + a start/stop pair per ticket (inside the window)
        t = OPENED + timedelta(minutes=10)
        for key, (aid, tokens) in TICKET_WORK.items():
            tid = tid_by_key.get(key)
            if not tid:
                continue
            for ev, tok in (("start", 0), ("token_report", tokens), ("stop", 0)):
                db.add(TrackingLog(project_id=PROJECT_ID, agent_id=aid, ticket_id=tid,
                                   event_type=ev, tokens=tok, timestamp=t, source="showcase"))
        # TL overhead (Archie)
        db.add(TrackingLog(project_id=PROJECT_ID, agent_id=6, ticket_id=None,
                           event_type="overhead_token_report", tokens=12000,
                           timestamp=CLOSED, source="showcase"))

        for kw, w in KEYWORDS:
            db.add(EntityKeyword(entity_type="dwb_session", entity_id=s.id,
                                 keyword=kw, weight=w, source="showcase"))

        db.commit()
        print(f"Seeded showcase session id={s.id}: {total:,} tokens, "
              f"{len(KEYWORDS)} keywords, {len(HOOKS)} agents, {len(TICKET_WORK)} tickets.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

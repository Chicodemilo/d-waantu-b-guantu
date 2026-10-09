#!/usr/bin/env python3
# Path: scripts/human_memory_exerciser.py
# File: human_memory_exerciser.py
# Created: 2026-09-30 (DWB-614)
# Purpose: End-to-end exerciser for human_memory mode. Builds a throwaway
#          project+agent, seeds every tier at several session-ages (including
#          a WORKING row at the floor), manufactures the session clock by
#          inserting closed dwb_sessions/hook_sessions directly, fires the
#          SessionStart hook as the consolidation trigger, and asserts each of
#          the five movements individually. Prints the literal spawn and
#          SessionStart context an agent receives. Deletes the throwaway
#          project/agent whether it passes or fails.
# Caller: manual CLI (`python scripts/human_memory_exerciser.py`)
# Callees: app.database.SessionLocal + app.models.* (session-clock and tiered
#          memory seed rows only - no write API exists for either, see module
#          docstring); the running API at --api-base (default
#          http://localhost:8000/api) for every read/write being verified
# Data In: none (all state is created by this script)
# Data Out: stdout report (per-movement PASS/FAIL table, literal received
#           context, band-assembly check); no lasting DB rows on success
# Last Modified: 2026-09-30 (DWB-614: functional-not-unit rework - movement
#                and band checks now read exclusively through GET
#                /api/agents/{id}/memory/scored and GET /api/journal, journal
#                seeding goes through real POST/GET reinforcement, per Miles's
#                correction that this must be a functional test all the way
#                through, not a unit test importing the service layer)

"""DWB-614: the exerciser Miles asked for.

"You probably need one more ticket, a way to test the system. So you can see
where your problems are and correct." (Miles Chick, approving the human_memory
gap lane, 2026-09-30)

BUILT FIRST, ON PURPOSE. Nothing in the five-movement lane (DWB-603, 604, 606,
607, 608) or the session-start job (DWB-609) exists yet when this is written.
That means this script is EXPECTED to print FAIL on nearly every row today.
That red baseline is the deliverable, not a defect - a harness written after
the features would be shaped by what got built; written first, it is shaped
by what Miles specified. Each subsequent ticket in the lane should turn one
row of the movement table green, and the received-context prints in step 5
should stop showing the empty STOCK_MEMORY_SEALED_POINTER once DWB-610 lands.

HARD RULE, per the ticket: operates against a THROWAWAY project and agent that
this script creates and deletes. NEVER project 1. A live-memory outage in S83
already cost real time for touching the real project's memory_mode; this
exerciser exists partly to stop that ever needing to happen again to verify
anything about the memory system.

WHY DIRECT DB INSERTS FOR THE SESSION CLOCK. DWB-585's decay clock counts
CLOSED dwb_sessions joined through hook_sessions for one agent, by id, not by
wall time (docs/human_memory_spec.md section 3: "the clock is sessions, not
days"). Waiting on real sessions to accumulate is not an option for a script
that has to run in one command, so this manufactures a chain of already-closed
(dwb_session, hook_session) pairs directly via the ORM - exactly what Archie's
brief calls the fiddly part that makes the rest measurable.

FUNCTIONAL, NOT UNIT (Miles's correction, 2026-09-30, after an earlier draft
of this file read state through direct ORM queries). "Not unit test a
functional test all the way thru." A unit test proves the code matches the
models; only a test that drives the actual running system over the channels
an agent really uses proves the system works - and a version that imports the
same service functions the feature is built from is not a second instrument,
it is the first one wearing a different hat. Concretely: this script talks to
`--api-base` (default the live localhost:8000 API, backed by the real dev
database, not `lat_test` - `lat_test` is built by `create_all` from the models
and live is built by migrations, and the two disagree on server defaults) for
EVERY read or write that is part of what is being verified:
  - create/delete the throwaway project and agent            -> HTTP
  - the memory_mode adopt/cutover switch                     -> HTTP
  - the consolidation trigger itself                         -> HTTP POST
    /api/hooks/session-start, the exact hook DWB-609 is meant to hang off
  - what an agent receives at spawn and at session start      -> HTTP, printed
    verbatim from the response body, not summarized
  - whether a movement fired (does the memory/journal state an agent can
    actually READ show it)                                    -> HTTP GET
    /api/agents/{id}/memory/scored and HTTP GET /api/journal, the same two
    read surfaces an agent uses, never a direct table query
  - journal reinforcement for the promotion precondition       -> HTTP GET
    /api/journal?term=... called three times, the REAL retrieval-increments-
    the-count mechanism (spec section 5), not a column set directly

WHAT STILL GOES DIRECT-TO-DB, AND WHY THAT DOES NOT VIOLATE THE ABOVE. Two
things: the session-clock chain (dwb_sessions/hook_sessions rows) and the
tiered AgentMemory seed rows (CORE/SCAR/WORKING with a specific tier,
fired_count, context_key and session-gap). Neither has a write API today by
design - not an oversight this script routes around. There is no endpoint
that creates a memory pre-tiered: the only POST that writes agent_memories
directly is raw-only (app/services/raw_memory.py forces tier=raw
unconditionally), and the one pipeline that CAN write scar/working/core rows
(the adopt/decide flow) can only tier candidates it enumerated from a real
memory.md file and cannot accept a caller-supplied fired_count or context_key
at all - both are exactly the fields two of the five movement preconditions
need. Backdating real session history through the hook API is similarly a
non-starter: HookEventInput carries no timestamp field, so 92 real hook calls
would all land at "now" regardless. None of this is the code under test -
it is the fixture a real E2E test still needs when the system cannot yet
produce that state on its own - and every assertion this script makes reads
that fixture back exclusively through the same endpoints an agent uses.

MOVEMENTS C AND D EACH NEED A DIFFERENT "IS THIS CONTEXT ALIVE" SIGNAL, AND
BOTH ARE NOW GENUINE, NOT PROXIED. DWB-604's context-liveness SCAN
(app/services/memory_scan.py) landed after this script was first written,
when both preconditions were still fabricated strings that could never
resolve to anything - which meant movement (c) in particular could never go
green even against perfect code, since its precondition never reached the
outcome it claimed to test (caught by Archie, 2026-09-30). Fixed by making
each precondition real rather than descriptive: `create_throwaway` mints a
real epic/sprint/ticket and closes it, and movement (c)'s scar
(`scar_ctx_dead`) carries that ticket's own key in its context_key, so
`scan_context`'s ticket-resolution branch genuinely returns `finished`.
Movement (d)'s scar (`scar_ctx_alive`) keeps a context_key that matches
nothing real on purpose - `cannot_die` IS the "resolves to nothing" case, so
a non-matching string is the correct fixture there, not a limitation.

Usage:
    cd backend && .venv/bin/python scripts/human_memory_exerciser.py
    .venv/bin/python scripts/human_memory_exerciser.py --keep   # skip cleanup, for debugging
    .venv/bin/python scripts/human_memory_exerciser.py --api-base http://localhost:8000/api
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.agent_memory import AgentMemory, MemoryTier  # noqa: E402
from app.models.dwb_session import (  # noqa: E402
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType  # noqa: E402
from app.models.journal_entry import JournalEntry  # noqa: E402
from app.models.tl_message import TlMessageRead  # noqa: E402

DEFAULT_API_BASE = "http://localhost:8000/api"

# Session chain length. 91 covers every bucket edge in the section-3 table
# (0, 1-5, 6-14, 15-30, 31-90, 90+) with room to spare; index 0 is the oldest.
CHAIN_LEN = 91

# A unique marker per seeded row, so every assertion below greps for a string
# that cannot collide with anything else in a shared dev database, rather than
# guessing at row identity by tier + rough content.
RUN_TAG = uuid.uuid4().hex[:8]


def marker(label: str) -> str:
    return f"EXERCISER-{label}-{RUN_TAG}"


@dataclass
class Movement:
    """One row of the five-movement table."""

    key: str
    description: str
    passed: bool | None = None  # None until checked
    detail: str = ""


@dataclass
class Rig:
    """Everything this run created, so cleanup can find it all."""

    api_base: str
    session: object = None
    project_id: int | None = None
    project_prefix: str = ""
    agent_id: int | None = None
    agent_name: str = ""
    repo_path: str | None = None
    ticket_key: str = ""
    dwb_session_id: int | None = None
    chain_session_ids: list[int] = field(default_factory=list)
    movements: list[Movement] = field(default_factory=list)
    # WHICH PHASES ACTUALLY RAN (DWB-663). Not decoration: `print_table`
    # refuses unless every expected phase is in here. See PHASES below for
    # why a count of results cannot answer this question.
    phases_run: set = field(default_factory=set)
    band_assembly_ok: bool | None = None


def _api(rig: Rig, method: str, path: str, **kw) -> requests.Response:
    resp = requests.request(method, f"{rig.api_base}{path}", timeout=15, **kw)
    return resp


def _require(resp: requests.Response, context: str) -> dict:
    if resp.status_code >= 400:
        raise RuntimeError(
            f"{context} failed: {resp.status_code} {resp.text[:500]}"
        )
    return resp.json() if resp.content else {}


# ---------------------------------------------------------------------------
# 1. Throwaway project + agent
# ---------------------------------------------------------------------------


def create_throwaway(rig: Rig) -> None:
    rig.repo_path = tempfile.mkdtemp(prefix="dwb-memory-exerciser-")
    prefix = f"MEX{uuid.uuid4().hex[:4].upper()}"
    body = {
        "prefix": prefix,
        "name": f"Memory Exerciser Throwaway {RUN_TAG}",
        "description": "DWB-614 throwaway. Created and deleted by "
        "human_memory_exerciser.py. If you see this outside a running "
        "exerciser, the cleanup step failed - delete it by hand.",
        "repo_path": rig.repo_path,
    }
    data = _require(_api(rig, "POST", "/projects", json=body), "create throwaway project")
    rig.project_id = data["id"]
    rig.project_prefix = prefix
    print(f"[setup] throwaway project {prefix} (id={rig.project_id}) at {rig.repo_path}")

    # role=team-lead so this same agent is the one tl_memory_for_project()
    # resolves at SessionStart - that is the one path today's code actually
    # injects memory into, and it is the path step 5 needs to print.
    rig.agent_name = f"Exerciser_{RUN_TAG}"
    agent_body = {
        "project_id": rig.project_id,
        "name": rig.agent_name,
        "role": "team-lead",
        "api_key": f"exerciser-{RUN_TAG}",
    }
    data = _require(_api(rig, "POST", "/agents", json=agent_body), "create throwaway agent")
    rig.agent_id = data["id"]
    print(f"[setup] throwaway agent {rig.agent_name} (id={rig.agent_id})")

    # A DWB SESSION MUST BE OPEN BEFORE THE ADOPTION (DWB-663). Without one
    # the PATCH below is refused outright:
    #   400 "Adoption refused: <PREFIX> has no open DWB session."
    # That guard (DWB-637) is correct and is not the thing to work around.
    # Every memory an adoption writes stamps its clock origin from the session
    # open at the time; with none open they all store NULL, and a memory with
    # no origin cannot be scored, so it is excluded from retrieval and never
    # reaches an agent. The store fills up and reads as empty.
    #
    # This rig predates that guard and was never updated, so it died here, at
    # setup, long before any of the checks it exists to run. It had been doing
    # that quietly for an unknown length of time.
    data = _require(
        _api(rig, "POST", "/sessions/open", json={
            "project_id": rig.project_id,
            "open_method": "slash",
            "open_phrase": f"exerciser run {RUN_TAG}",
        }),
        "open DWB session on the throwaway",
    )
    rig.dwb_session_id = data["id"]
    print(f"[setup] DWB session {rig.dwb_session_id} opened on the throwaway")

    # stock -> adopting, confirmed. A brand-new project with no memory.md
    # content on disk enumerates ZERO candidates, and app/services/project.py
    # (_enumerate_for_run) walks BEGIN then immediately CUTOVER inside this
    # one PATCH when that happens - there is nothing to adopt, so it lands
    # directly on human_memory. Confirmed by reading that function before
    # writing this script; if that auto-cutover behaviour ever changes this
    # step will surface it immediately as a mode mismatch below.
    resp = _api(
        rig,
        "PATCH",
        f"/projects/{rig.project_id}",
        json={"memory_mode": "adopting", "memory_mode_confirmed": True},
    )
    data = _require(resp, "switch memory_mode to adopting")
    mode = data.get("memory_mode")
    if mode != "human_memory":
        raise RuntimeError(
            f"expected auto-cutover to human_memory (empty project, nothing "
            f"to adopt); got memory_mode={mode!r}. The adopt-pipeline "
            f"contract this script relies on may have changed."
        )
    print(f"[setup] memory_mode = {mode}")

    # A real, closed ticket - the resolvable "context finished" case movement
    # (c) needs. Until this existed, scar_ctx_dead's context_key was a
    # descriptive-but-unresolvable string, which app/services/memory_scan.py's
    # scan_context resolves to `cannot_die`, not `finished` - meaning movement
    # (c) could never go green even against perfect DWB-607/609 code (Archie's
    # catch, 2026-09-30). A ticket needs an active sprint to exist on, which
    # needs an epic; created here purely as that scaffolding, deleted along
    # with everything else when the project goes (delete_project cascades
    # tickets/sprints/epics by project_id).
    epic = _require(
        _api(rig, "POST", "/epics", json={
            "project_id": rig.project_id, "name": "exerciser scaffolding",
        }),
        "create throwaway epic",
    )
    sprint = _require(
        _api(rig, "POST", "/sprints", json={
            "project_id": rig.project_id, "epic_id": epic["id"],
            "goal": "exerciser scaffolding", "sprint_number": 1, "status": "active",
        }),
        "create throwaway sprint",
    )
    ticket = _require(
        _api(rig, "POST", "/tickets", json={
            "project_id": rig.project_id, "sprint_id": sprint["id"],
            "ticket_key": f"{rig.project_prefix}-1",
            "title": f"exerciser context-finished proxy {RUN_TAG}",
        }),
        "create throwaway ticket",
    )
    rig.ticket_key = ticket["ticket_key"]
    _require(
        _api(rig, "PATCH", f"/tickets/{ticket['id']}", json={"status": "done"}),
        "close throwaway ticket",
    )
    print(f"[setup] context-finished proxy ticket {rig.ticket_key} closed")
    rig.phases_run.add("setup")


# ---------------------------------------------------------------------------
# 2/3. Manufacture the session clock, then seed every bucket against it
# ---------------------------------------------------------------------------


def build_session_chain(rig: Rig) -> None:
    """CHAIN_LEN+1 already-closed (dwb_session, hook_session) pairs for the
    throwaway agent, oldest first. `chain[i].id` used as a memory row's
    created_session_id/last_reinforced_session_id gives that row a
    sessions_since_reinforced of exactly (CHAIN_LEN - i), because
    memory_score.sessions_since_reinforced counts closed dwb_sessions with
    id > origin, joined through hook_sessions for this agent (memory_score.py
    lines ~143-189) - it does not read wall-clock time at all.

    Inserted pre-closed (closed_at set at construction) so the single-open-
    session-per-project generated column never marks one open; no interaction
    with the real project's own session state.
    """
    db = rig.session
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(CHAIN_LEN + 1):
        opened = base + timedelta(minutes=i * 10)
        closed = opened + timedelta(minutes=5)
        dwb = DwbSession(
            project_id=rig.project_id,
            opened_at=opened,
            closed_at=closed,
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        db.add(dwb)
        db.flush()
        hook = HookSession(
            session_id=f"exerciser-chain-{RUN_TAG}-{i}",
            agent_id=rig.agent_id,
            project_id=rig.project_id,
            dwb_session_id=dwb.id,
            start_time=opened,
            end_time=closed,
            status=HookSessionStatus.completed,
            session_type=HookSessionType.teammate,
            agent_name=rig.agent_name,
        )
        db.add(hook)
        rig.chain_session_ids.append(dwb.id)
    db.commit()
    print(f"[setup] manufactured {CHAIN_LEN + 1} closed sessions for the clock")
    rig.phases_run.add("session_chain")


def origin_for_gap(rig: Rig, gap: int) -> int:
    """The dwb_session id to use as created/last_reinforced_session_id so that
    sessions_since_reinforced comes out to exactly `gap`."""
    index = CHAIN_LEN - gap
    if index < 0:
        raise ValueError(f"gap {gap} exceeds chain length {CHAIN_LEN}")
    return rig.chain_session_ids[index]


def _mk_memory(rig: Rig, *, tier: MemoryTier, gap: int, body: str, **kw) -> AgentMemory:
    origin = origin_for_gap(rig, gap)
    row = AgentMemory(
        agent_id=rig.agent_id,
        tier=tier,
        body=body,
        created_session_id=origin,
        last_reinforced_session_id=origin,
        **kw,
    )
    rig.session.add(row)
    return row


def seed_buckets(rig: Rig) -> dict:
    """Every bucket, at several ages, plus one row per movement precondition.

    Returns the seeded rows keyed by role, so assertions can find them by
    identity rather than re-deriving markers.
    """
    db = rig.session
    seeded: dict[str, AgentMemory | JournalEntry] = {}

    # CORE - age is irrelevant by rule (never touched by decay); seeded at a
    # long gap specifically to prove that.
    seeded["core"] = _mk_memory(
        rig, tier=MemoryTier.core, gap=CHAIN_LEN,
        body=f"{marker('CORE')}: a standing rule, ten forever.",
    )

    # SCAR at several ages, resting at 6 past the 31-90 bucket.
    for gap in (0, 3, 10, 20, CHAIN_LEN):
        seeded[f"scar_gap{gap}"] = _mk_memory(
            rig, tier=MemoryTier.scar, gap=gap,
            body=f"{marker('SCAR')}-gap{gap}: an ordinary scar at rest.",
        )

    # Movement b precondition: a scar fired 3x, despite being held - the
    # spec's own evidence for "learned too narrow, broaden to CORE". Seeded
    # directly rather than via the (unbuilt) DWB-603 writer, so this row
    # exercises the DOWNSTREAM promotion independent of the upstream counter.
    seeded["scar_recur"] = _mk_memory(
        rig, tier=MemoryTier.scar, gap=50, fired_count=3,
        body=f"{marker('SCAR-RECUR')}: fired three times while held.",
    )

    # Movement c precondition: a scar, resting at 6, with a context_key that
    # reads as finished. DWB-611 collapsed scar_context_bound into scar - all
    # scars are context-bound now, distinguished only by whether context_key
    # is populated, not by tier. IMPORTANT POST-611 CORRECTION (Stan, same
    # day): a scar with NO context_key now means `still_active` (unknown,
    # take no action), not `cannot_die` - a missing key used to be safe to
    # read as "deliberately general" only because a plain `scar` could never
    # carry one by construction; that guarantee is gone now that there is one
    # tier. So every row below sets an EXPLICIT context_key, never leaves it
    # None, to stay on the branch that still means what its name says.
    # DWB-604's context-liveness SCAN (app/services/memory_scan.py) resolves
    # context_key by looking for a real ticket key embedded in it, then a
    # matching epic name, before falling back to "named but unresolvable".
    # A descriptive-but-fake string here would resolve to `cannot_die`, not
    # `finished` - Archie caught that this movement could never go green
    # against even perfect DWB-607/609 code while the precondition was fake.
    # So this uses the REAL closed ticket `create_throwaway` makes for exactly
    # this purpose (see that function) - `_resolve_ticket`'s regex picks the
    # ticket key out of the string, and `status == done` resolves to
    # `finished`.
    seeded["scar_ctx_dead"] = _mk_memory(
        rig, tier=MemoryTier.scar, gap=CHAIN_LEN,
        context_key=f"{rig.ticket_key} / the thing this scar was about",
        body=f"{marker('SCAR-CTXDEAD')}: bound to a context that is now finished.",
    )

    # Movement d precondition: a scar, resting at 6, with an EXPLICIT
    # context_key that names nothing closeable - exactly the "named but
    # unresolvable" branch Stan's post-611 fix keeps mapped to `cannot_die`.
    # Deliberately NOT a missing/None context_key: per the correction above,
    # that now means `still_active` and would not exercise this movement at
    # all. Deliberately ALSO not a real ticket/epic reference, unlike movement
    # c above - "cannot_die" is specifically the case where nothing resolves,
    # so a fabricated, non-matching string is the correct fixture here, not a
    # limitation to fix.
    #
    # COUPLING TO NAME ELSEWHERE IN THIS FILE, WRITTEN DOWN RATHER THAN LEFT
    # IMPLICIT: this row's `cannot_die` result depends on the throwaway
    # epic's name ("exerciser scaffolding", set in create_throwaway) NOT
    # being a substring of the string below - memory_scan._resolve_epic
    # matches by name-containment. Rename that epic to something containing
    # "standing" or "close" and this row silently starts returning
    # `still_active` or `finished` instead of `cannot_die`, with no error
    # anywhere to say why movement (d) started failing.
    seeded["scar_ctx_alive"] = _mk_memory(
        rig, tier=MemoryTier.scar, gap=CHAIN_LEN,
        context_key="standing:this-can-never-close",
        body=f"{marker('SCAR-CTXALIVE')}: bound to a context with no death condition.",
    )

    # WORKING at several ages, including one already at the floor (movement a
    # precondition).
    for gap in (0, 3, 10, 20):
        seeded[f"working_gap{gap}"] = _mk_memory(
            rig, tier=MemoryTier.working, gap=gap,
            body=f"{marker('WORKING')}-gap{gap}: a box fact, fading on schedule.",
        )
    seeded["working_floor"] = _mk_memory(
        rig, tier=MemoryTier.working, gap=CHAIN_LEN,
        body=f"{marker('WORKING-FLOOR')}: a box fact nobody has touched in 91 sessions.",
    )

    # Band-check precondition, added after Archie caught the first version's
    # false FAIL: every other seeded body here is one short sentence, so a
    # correct one-line compression of it is a no-op and is BYTE-IDENTICAL to
    # a broken compressor that dumps the full body - "compressed, body
    # present verbatim" cannot tell the two apart when compression would not
    # have changed anything anyway. This row is deliberately multi-line with
    # a first line well past the compression cap, so the two cases produce
    # DIFFERENT, checkable output. Seeded in the compressed band (gap=20,
    # score=7), not tied to any of the five movements.
    long_first_line = (
        f"{marker('SCAR-LONG')}: this first line is deliberately written "
        "well past the one-line compression cap, long enough on its own "
        "that a correct compressor and a broken one cannot produce the "
        "same output by accident, which a short body cannot rule out."
    )
    seeded["scar_long"] = _mk_memory(
        rig, tier=MemoryTier.scar, gap=20,
        body=(
            f"{long_first_line}\n"
            "This second line must never appear in a correctly compressed "
            "rendering.\n"
            "Neither should this third line."
        ),
        # DWB-658/659. The two author-supplied fields are REQUIRED at the write
        # gate (DWB-657), and this rig writes rows directly, so without seeding
        # them here the rig would keep passing while never once exercising the
        # contract it exists to prove. A check pointed at a contract it does not
        # touch is not evidence for that contract.
        #
        # The condensed line deliberately shares NO marker with the body's first
        # line, so `check_band_assembly` can tell the stored-line path from the
        # old truncation. If they overlapped, both implementations would produce
        # output containing the same marker and the check could not discriminate.
        condensed=f"{marker('SCAR-LONG-CONDENSED')}: the author's own line",
        keywords=["compression", "band", "author-line"],
    )

    # Deliberately left with condensed=NULL and keywords=NULL: every one of the
    # 832 rows that existed when these columns landed is in that state, and
    # DWB-655 has not backfilled them, so the fallback path is the one real
    # agents read today. A rig that seeded every row would stop covering it.
    seeded["scar_long_null"] = _mk_memory(
        rig, tier=MemoryTier.scar, gap=20,
        body=(
            f"{marker('SCAR-LONG-NULL')}: this row has no author-supplied "
            "condensed line, which is what every pre-DWB-657 row looks like.\n"
            "This second line must never appear either."
        ),
    )

    db.commit()
    for v in seeded.values():
        db.refresh(v)

    seed_journal_entries(rig, seeded)

    print(f"[setup] seeded {len(seeded)} rows across CORE/SCAR/WORKING/JOURNAL")
    rig.phases_run.add("seed")
    return seeded


def seed_journal_entries(rig: Rig, seeded: dict) -> None:
    """JOURNAL entries over real HTTP: POST /api/journal to create, then GET
    /api/journal?term=... zero, one or three times to reach the target
    retrieval_count through the ACTUAL reinforcement mechanism (spec section
    5: "retrieval is the reinforcement signal", the single write site in
    app/services/journal.py) rather than by setting the column directly. The
    movement e precondition (3+ retrievals) is reached this way on purpose -
    it is the real path an agent's own journal search would trigger.

    `term` does a LIKE match on body (app/services/journal.py search_entries),
    and each marker is unique for this run, so a search never reinforces a
    different row than the one intended.
    """
    for target_count, role in (
        (0, "journal_low"), (1, "journal_mid"), (3, "journal_promote"),
    ):
        text = marker(role.upper())
        body = f"{text}: retrieved {target_count} time(s)."
        data = _require(
            _api(rig, "POST", "/journal", json={
                "agent_id": rig.agent_id, "body": body, "tags": ["exerciser"],
            }),
            f"create journal entry ({role})",
        )
        seeded[role] = {"id": data["id"], "marker": text}
        for _ in range(target_count):
            _require(
                _api(rig, "GET", "/journal", params={
                    "agent_id": rig.agent_id, "term": text,
                }),
                f"reinforce journal entry ({role})",
            )


# ---------------------------------------------------------------------------
# 4. Run consolidation (fire SessionStart), assert the five movements
# ---------------------------------------------------------------------------


def fire_consolidation_trigger(rig: Rig) -> dict:
    """POST /api/hooks/session-start for the throwaway agent - the hook
    DWB-609 is meant to hang the movement job off, per Miles's framing that
    the job fires "at the start of each session". agent_name is passed
    directly in the hook payload, which handle_session_start's fallback path
    resolves without needing a `.claude/agents/active/<session_id>` marker
    file (app/services/hook_tracking.py handle_session_start, the `agent_name`
    fallback branch) - this script is not a live Claude Code session and has
    no marker to write, nor should it: writing under .claude/ is the thing
    that crashes a subagent's permission dialog.
    """
    session_id = f"exerciser-trigger-{RUN_TAG}"
    resp = _api(
        rig, "POST", "/hooks/session-start",
        json={
            "session_id": session_id,
            "cwd": rig.repo_path,
            "hook_event_name": "SessionStart",
            "agent_name": rig.agent_name,
        },
    )
    out = _require(resp, "fire SessionStart consolidation trigger")
    rig.phases_run.add("consolidation_trigger")
    return out


def fetch_scored(rig: Rig) -> list[dict]:
    """GET /api/agents/{id}/memory/scored - the same read surface an agent
    (or a future spawn/session-start assembly) uses.

    CALLED EXACTLY ONCE PER RUN, by `main`, and the result is threaded through
    to both `check_movements` and `check_band_assembly` rather than each
    calling it independently. Not an optimisation: Stan's DWB-603 made
    reading this endpoint a MUTATION for scar-family rows (it increments
    `fired_count` on every scar it returns, per Freddie's note on DWB-614)
    while the counter semantics are still pending Miles's ruling. Reading it
    twice would tick `scar_recur`'s fired_count past the 3 it was seeded at
    before `check_band_assembly` ever looks at it, which is not a bug in
    either check individually but would be a real, silent side effect of
    THIS SCRIPT on the exact counters the rest of the lane promotes on.

    NOT FULLY ELIMINATED BY THIS SINGLE FETCH, AND SAID PLAINLY RATHER THAN
    IMPLIED. `memory_score.scored_memory()` is the one write site (DWB-603),
    and `memory_context.assemble_session_context()` calls it internally too -
    so `print_received_context`'s spawn-prepare call and its two SessionStart
    hook calls (the consolidation trigger and the context-print call) each
    ALSO increment fired_count on every scar-family row for this agent, on
    top of the one read here. Four passes total per run, not one. Left as-is
    rather than restructured around it: today nothing reacts to fired_count
    at read time (promotion needs an explicit call to
    `memory_promote.maybe_promote_scar`, which nothing yet wires to a read),
    so the inflated counters are inert for every check this script currently
    makes. That stops being true the day something DOES read fired_count off
    the back of one of these calls and act on it - and the semantics this
    note describes are explicitly provisional pending Miles's ruling, so
    building a workaround for them now risks hard-coding a shape that is
    about to change. Revisit this note once that ruling lands.
    """
    data = _require(
        _api(rig, "GET", f"/agents/{rig.agent_id}/memory/scored"),
        "GET scored memory",
    )
    rig.phases_run.add("scored_fetch")
    return data.get("entries", []) if data.get("computed") else []


def _journal_has(rig: Rig, text: str) -> bool:
    """Does a journal entry NOW exist whose body contains `text`, via the real
    search endpoint - the same one an agent's own retrieval would hit. Every
    marker is unique for this run, so a hit can only be the row in question,
    whether it was seeded there or written by an eviction that just fired."""
    data = _require(
        _api(rig, "GET", "/journal", params={"agent_id": rig.agent_id, "term": text}),
        f"journal search for {text!r}",
    )
    return data.get("total_matched", 0) > 0


def check_movements(rig: Rig, seeded: dict, entries: list[dict]) -> None:
    """All five checks read ONLY through GET /api/agents/{id}/memory/scored
    (passed in, already fetched once by `main` - see `fetch_scored`) and GET
    /api/journal - the two surfaces an agent actually reads memory through.
    No table is queried directly here (see the FUNCTIONAL, NOT UNIT module
    note for why that boundary matters)."""
    by_id = {e["id"]: e for e in entries}

    def still_present(role: str) -> dict | None:
        return by_id.get(seeded[role].id)

    def core_row_referencing(text: str) -> dict | None:
        return next(
            (e for e in entries if e["tier"] == "core" and text in e["body"]), None
        )

    m = []

    # a. WORKING at the floor moves into the journal.
    text = marker("WORKING-FLOOR")
    gone = still_present("working_floor") is None
    journaled = _journal_has(rig, text)
    m.append(Movement(
        "a", "WORKING at the floor moves into the journal",
        passed=gone and journaled,
        detail=f"evicted_from_agent_memories={gone}, journal_entry_present={journaled}",
    ))

    # b. SCAR fired 3x broadens to CORE.
    text = marker("SCAR-RECUR")
    row = still_present("scar_recur")
    new_core = core_row_referencing(text)
    promoted = (row is not None and row["tier"] == "core") or new_core is not None
    m.append(Movement(
        "b", "SCAR fired 3x broadens to CORE",
        passed=promoted,
        detail=f"original_row_tier={row['tier'] if row else None!r}, "
               f"new_core_row_found={new_core is not None}",
    ))

    # c. SCAR at 6 whose context is finished moves into the journal.
    text = marker("SCAR-CTXDEAD")
    gone = still_present("scar_ctx_dead") is None
    journaled = _journal_has(rig, text)
    m.append(Movement(
        "c", "SCAR at 6 whose context is finished moves into the journal",
        passed=gone and journaled,
        detail=f"evicted_from_agent_memories={gone}, journal_entry_present={journaled}",
    ))

    # d. SCAR whose context can never die becomes CORE.
    text = marker("SCAR-CTXALIVE")
    row = still_present("scar_ctx_alive")
    new_core = core_row_referencing(text)
    promoted = (row is not None and row["tier"] == "core") or new_core is not None
    m.append(Movement(
        "d", "SCAR whose context can never die becomes CORE",
        passed=promoted,
        detail=f"original_row_tier={row['tier'] if row else None!r}, "
               f"new_core_row_found={new_core is not None}",
    ))

    # e. JOURNAL entry pulled 3+ times becomes CORE. There is no
    # source_journal_id on ScoredMemoryEntry (by design - DWB-585's schema
    # does not expose it), so the HTTP-visible proxy is the same one used for
    # b/d: a CORE row whose body carries the promoted entry's marker. This is
    # arguably the more honest check anyway - it asks whether the promoted
    # lesson actually reached the agent's readable memory, not merely whether
    # a foreign key was set.
    #
    # MARKER MUST MATCH seed_journal_entries' OWN STRING EXACTLY: that
    # function builds its marker from the role string "journal_promote"
    # (underscore, from the (count, role) tuple below), not the hyphenated
    # "JOURNAL-PROMOTE" every other movement's marker uses. A one-character
    # mismatch here silently reported this movement as permanently FAIL - a
    # bug in the exerciser's own fixture matching, not in DWB-608/609. Caught
    # by querying the live row directly rather than trusting the printed
    # FAIL.
    text = marker("journal_promote".upper())
    new_core = core_row_referencing(text)
    m.append(Movement(
        "e", "JOURNAL entry pulled 3+ times becomes CORE",
        passed=new_core is not None,
        detail=f"promoted_agent_memory_id={new_core['id'] if new_core else None}",
    ))

    rig.movements = m
    rig.phases_run.add("movements")


# ---------------------------------------------------------------------------
# 5/6. What an agent actually receives, verbatim; band assembly check
# ---------------------------------------------------------------------------


def print_received_context(rig: Rig) -> tuple[str, str]:
    print("\n" + "=" * 78)
    print("STEP 5: literal text an agent receives at SPAWN")
    print("=" * 78)
    spawn_resp = _api(
        rig, "POST", "/agents/spawn-prepare",
        json={"role": "team-lead", "name": rig.agent_name, "project_prefix": rig.project_prefix},
    )
    spawn_data = _require(spawn_resp, "spawn-prepare")
    memory_full = spawn_data.get("memory_full", "")
    print("--- memory_full field, verbatim ---")
    print(memory_full if memory_full else "(EMPTY STRING)")
    print("--- end memory_full ---\n")

    print("=" * 78)
    print("STEP 5: literal text an agent receives at SESSION START")
    print("=" * 78)
    session_id = f"exerciser-context-print-{RUN_TAG}"
    resp = _api(
        rig, "POST", "/hooks/session-start",
        json={
            "session_id": session_id,
            "cwd": rig.repo_path,
            "hook_event_name": "SessionStart",
            "agent_name": rig.agent_name,
        },
    )
    data = _require(resp, "session-start (context print)")
    additional_context = (
        data.get("hookSpecificOutput", {}).get("additionalContext", "")
    )
    print("--- hookSpecificOutput.additionalContext, verbatim ---")
    print(additional_context if additional_context else "(EMPTY - nothing injected)")
    print("--- end additionalContext ---\n")

    rig.phases_run.add("received_context")
    return memory_full, additional_context


def _expected_compressed_line(entry: dict, cap: int = 400) -> str:
    """Independent expectation for what a band 5-7 entry's one line should
    read, REWRITTEN FOR DWB-658.

    WHAT CHANGED AND WHY THIS FILE HAD TO CHANGE WITH THE FEATURE. This used to
    reimplement the old `memory_context._one_line`: first non-blank line of the
    body, capped at 160. That was correct until DWB-658, which made the 5-7
    band render the AUTHOR'S stored `condensed` instead. Left alone, this
    function would have expected the body's first line, found the author's line
    instead, and reported NOT_ASSEMBLED for every compressed row - the
    project's own end-to-end instrument calling a working feature broken, with
    no way for a reader to tell which of the two to believe.

    That is worth naming as a class: AN INDEPENDENT REIMPLEMENTATION IS THE
    RIGHT DESIGN AND IT IS ALSO A SECOND COPY OF THE CONTRACT. It cannot drift
    silently the way a shared helper does, but it does go stale, and it goes
    stale by reporting FAILURE, which is the safe direction and still costs
    somebody an afternoon. When the contract moves, this moves.

    STILL DELIBERATELY NOT AN IMPORT of `memory_context._condensed_line`.
    Importing the function under test puts the same component on both sides of
    the comparison, so a bug in it cancels out and the check passes for the
    wrong reason. Hand-written from the contract instead:
      - an author's `condensed` renders as itself, bounded for display;
      - a NULL `condensed` falls back to the body's first line, bounded, and
        carries a marker saying it is not the author's line.
    """
    condensed = (entry.get("condensed") or "").strip()
    if condensed:
        return condensed[: cap - 1].rstrip() + "\u2026" if len(condensed) > cap else condensed

    for line in (entry.get("body") or "").splitlines():
        stripped = line.strip().lstrip("-*+").strip()
        if stripped:
            bounded = (
                stripped[: cap - 1].rstrip() + "\u2026"
                if len(stripped) > cap
                else stripped
            )
            return f"{bounded} [auto-excerpt, not the author's line]"
    return ""


def _band_expectation_label(expect_full_text: bool, expect_keywords_only: bool) -> str:
    if expect_full_text:
        return "expected verbatim"
    if expect_keywords_only:
        return "expected id + keywords, no content"
    return "expected the author's one line"


def check_band_assembly(rig: Rig, memory_full: str, entries: list[dict]) -> None:
    """Section 3's band table (docs/human_memory_spec.md): 8-10 carried in
    full, 5-7 compressed to one line, below that not carried at all. DWB-610
    (assemble scored memory into new session context) produces `memory_full`
    from these bands.

    `entries` is the SAME list `check_movements` used, fetched once by `main`
    via `fetch_scored` - see that function's docstring for why this does not
    call the endpoint again itself (reading it is a mutation for scar-family
    rows as of DWB-603).

    THE GUARD ARCHIE CAUGHT, AND WHY THE FIX IS A SIGNAL THAT DIFFERS, NOT A
    TIGHTER CHECK. The first version of this asked "is the full body present
    verbatim in a compressed-band row" and called that FAIL. For every row
    seeded as one short sentence, a CORRECT one-line compression is a no-op -
    the compressed output IS the full body, byte for byte - so that question
    answers identically whether DWB-610's compressor is broken or working.
    That is the same shape as every guard this project has shipped wrong: the
    dangerous case and the safe case give the same answer. The fix is not to
    tighten the check (it cannot be tightened into telling them apart, the
    information is not there), it is `seed_buckets`'s `scar_long` row - a body
    long and multi-line enough that a real compression and a no-op compression
    are DIFFERENT strings. Only rows where that is true can produce a decisive
    PASS or FAIL for the compressed side; every other compressed-band row is
    reported SHORT_BODY_AMBIGUOUS rather than guessed at.
    """
    print("=" * 78)
    print("STEP 6: bands 8-10 as full text, lower bands compressed")
    print("=" * 78)
    rig.phases_run.add("band_assembly")
    if not entries:
        print("FAIL: scored memory reports computed=False, or nothing scored")
        rig.band_assembly_ok = False
        return

    rows = []
    for e in entries:
        if not e["scored"]:
            continue
        band = e["band"]
        full = e["body"]  # DWB-610: ScoredMemoryEntry carries body directly
        full_present = bool(full) and full in memory_full
        expect_full_text = band == "full_text"
        # DWB-659 SPLIT THE NON-FULL-TEXT CASE IN TWO AND THIS CHECK HAD TO
        # SPLIT WITH IT. Everything that was not `full_text` used to be
        # "expected one-line compression", which was true when the 2-4 and 1
        # bands were a bare aggregate count and no row appeared individually.
        # They now render per-row as `#<id>  kw, kw` and carry NO condensed
        # line, so the old expectation looked for a line that is correctly
        # absent and reported NOT_ASSEMBLED - the instrument calling a working
        # feature broken, which is exactly what DWB-663 was filed about,
        # reappearing one band along. Caught by running the rig; the first fix
        # to this file was made without being able to.
        expect_keywords_only = band in ("demotion_candidate", "last_consolidation")

        if expect_full_text:
            outcome = "PASS" if full_present else "NOT_ASSEMBLED"
        elif expect_keywords_only:
            # These bands are abbreviated BECAUSE they are low value. The
            # check is therefore the mirror of the one above: the row must be
            # REFERENCED and its content must NOT be carried.
            id_present = f"#{e['id']}" in memory_full
            condensed = (e.get("condensed") or "").strip()
            leaked = full_present or (bool(condensed) and condensed in memory_full)
            if leaked:
                outcome = "FAIL"  # content carried in a band that must not
            elif id_present:
                outcome = "PASS"
            else:
                outcome = "NOT_ASSEMBLED"
        else:
            expected_line = _expected_compressed_line(e)
            # Decisive when the expected rendering is a DIFFERENT string
            # from the full body - otherwise a correct render and a no-op
            # render are byte-identical and the row cannot tell them
            # apart. True for scar_long (an author's line that shares no
            # text with the body) and scar_long_null (a long first line
            # plus the excerpt marker).
            decisive = expected_line != full
            line_present = bool(expected_line) and expected_line in memory_full
            if not decisive:
                # A short, already-one-line body: full text and a correct
                # compression are the identical string, so neither
                # "verbatim present" nor "compressed present" can tell a
                # working compressor from a broken one on this row. Reported,
                # not guessed at - see the module-level guard note above.
                outcome = "SHORT_BODY_AMBIGUOUS"
            elif line_present:
                outcome = "PASS"
            elif full_present:
                outcome = "FAIL"  # dumped in full when it should be compressed
            else:
                outcome = "NOT_ASSEMBLED"

        rows.append((e["id"], e["tier"], e["score"], band, outcome))
        print(
            f"  {outcome:<20}  memory_id={e['id']:>6}  tier={e['tier']:<20}  "
            f"score={e['score']:>2}  band={band:<18}  "
            f"{_band_expectation_label(expect_full_text, expect_keywords_only)}"
        )
    if not rows:
        print("  (no scored entries - nothing to check)")
    n_pass = sum(1 for *_, o in rows if o == "PASS")
    n_fail = sum(1 for *_, o in rows if o == "FAIL")
    n_not_assembled = sum(1 for *_, o in rows if o == "NOT_ASSEMBLED")
    n_ambiguous = sum(1 for *_, o in rows if o == "SHORT_BODY_AMBIGUOUS")
    print(
        f"\nBand assembly: {n_pass} PASS, {n_fail} FAIL, "
        f"{n_not_assembled} NOT_ASSEMBLED (DWB-610 has landed - any of these is a real gap), "
        f"{n_ambiguous} SHORT_BODY_AMBIGUOUS (compression is a no-op on these "
        f"bodies either way, so they cannot confirm or deny it) "
        f"of {len(rows)} scored rows"
    )
    # FEED THE VERDICT (DWB-663). This function used to print its results and
    # return None, touching nothing `print_table` reads, so every compressed
    # row could report FAIL while OVERALL said PASS and the script exited 0.
    # NOT_ASSEMBLED counts as failure: it means the row never reached the
    # injected context at all, which is the thing this step exists to catch.
    # SHORT_BODY_AMBIGUOUS does NOT - it is the honest third state for inputs
    # that cannot discriminate, and counting it either way would be a guess.
    rig.band_assembly_ok = (n_fail == 0 and n_not_assembled == 0)


# ---------------------------------------------------------------------------
# 7. Cleanup - always, pass or fail
# ---------------------------------------------------------------------------


def cleanup(rig: Rig) -> None:
    """Teardown is split between two mechanisms, and that split is deliberate,
    not partial coverage - named here so a reader never has to go read
    `delete_project` to find out which is which, the way Archie did.

    TICKETS, SPRINTS AND EPICS come out via `delete_project`'s own cascade
    (it deletes them by project_id before the project row goes). Verified,
    not assumed: checked the function's source, then confirmed no orphans
    across three live runs. No manual delete for these three tables here,
    on purpose - duplicating a cascade that already works is how a later fix
    to the real one gets half-applied to a second copy nobody remembers.

    AGENT_MEMORIES, JOURNAL_ENTRIES AND TL_MESSAGE_READS are deleted BY HAND,
    below, because `delete_project` and `delete_agent` do NOT cover them -
    two filed, still-open product bugs, not a style choice:
      - DWB-616: delete_project has the mirror gap for agent_memories and
        journal_entries that it does not have for tickets/sprints/epics.
      - DWB-615: delete_agent does not clear tl_message_reads, so deleting
        any agent that ever held role=team-lead 500s.
    When either lands, its manual delete below becomes removable - this is a
    workaround with an expiry condition, not a permanent part of the design.
    """
    print("\n" + "=" * 78)
    print("CLEANUP")
    print("=" * 78)
    if rig.session is not None and rig.agent_id is not None:
        try:
            n_mem = rig.session.query(AgentMemory).filter_by(agent_id=rig.agent_id).delete()
            n_journal = rig.session.query(JournalEntry).filter_by(agent_id=rig.agent_id).delete()
            rig.session.commit()
            print(f"[cleanup] deleted {n_mem} agent_memories, {n_journal} journal_entries "
                  f"(workaround for DWB-616 - delete_project's cascade does not cover "
                  f"these two tables; see this function's docstring)")
        except Exception as e:  # noqa: BLE001
            rig.session.rollback()
            print(f"[cleanup] WARNING: failed to clear agent_memories/journal_entries: {e}")

    if rig.project_id is not None:
        # No manual ticket/sprint/epic delete here - delete_project's own
        # cascade covers all three by project_id. See this function's
        # docstring for why that split is deliberate.
        resp = _api(rig, "DELETE", f"/projects/{rig.project_id}")
        if resp.status_code == 204:
            print(f"[cleanup] deleted throwaway project id={rig.project_id} "
                  f"(tickets/sprints/epics cascade with it)")
        else:
            print(f"[cleanup] WARNING: project delete returned {resp.status_code}: {resp.text[:300]}")

    if rig.agent_id is not None:
        # Workaround for DWB-615 (see this function's docstring), reproduced
        # directly against app.services.agent.delete_agent with a full
        # traceback: delete_agent clears project_agents but not
        # tl_message_reads, so ANY agent that ever held role=team-lead (this
        # throwaway agent does, so step 5's SessionStart injection has
        # something to resolve) 500s on DELETE the moment a broadcast on the
        # cross-project TL channel enrolls it.
        if rig.session is not None:
            try:
                n = rig.session.query(TlMessageRead).filter_by(agent_id=rig.agent_id).delete()
                rig.session.commit()
                if n:
                    print(f"[cleanup] cleared {n} tl_message_reads row(s) for agent "
                          f"{rig.agent_id} (workaround for DWB-615)")
            except Exception as e:  # noqa: BLE001
                rig.session.rollback()
                print(f"[cleanup] WARNING: failed to clear tl_message_reads: {e}")
        resp = _api(rig, "DELETE", f"/agents/{rig.agent_id}")
        if resp.status_code == 204:
            print(f"[cleanup] deleted throwaway agent id={rig.agent_id}")
        else:
            print(f"[cleanup] WARNING: agent delete returned {resp.status_code}: {resp.text[:300]}")

    if rig.repo_path and Path(rig.repo_path).exists():
        shutil.rmtree(rig.repo_path, ignore_errors=True)
        print(f"[cleanup] removed temp repo_path {rig.repo_path}")

    if rig.session is not None:
        rig.session.close()


# EVERY PHASE THAT MUST HAVE RUN BEFORE A VERDICT MEANS ANYTHING (DWB-663).
#
# WHY A SET OF NAMES AND NOT A COUNT OF RESULTS. Before this, `print_table`
# iterated `rig.movements` and set `all_pass = True` before the loop. With an
# empty list the loop never executed, so it printed
#   OVERALL: PASS (0/0 movements)
# and `main` returned 0. A rig that checked NOTHING reported success - the
# dangerous case and the safe case producing the identical answer, which is
# the exact guard shape this project keeps shipping wrong. Tightening the
# count cannot separate them, because "ran and all passed" and "never ran"
# are both consistent with zero failures. The signal has to DIFFER, so it is
# a record that each phase executed, written by the phase itself.
#
# Add a phase here when you add one. A name that is never recorded fails the
# run loudly, which is the intended direction: a check that silently stops
# running is what DWB-663 was filed about.
PHASES = {
    "setup",
    "session_chain",
    "seed",
    "consolidation_trigger",
    "scored_fetch",
    "movements",
    "received_context",
    "band_assembly",
}


def print_table(rig: Rig) -> bool:
    print("\n" + "=" * 78)
    print("PER-MOVEMENT RESULT (DWB-614 acceptance)")
    print("=" * 78)
    all_pass = True
    for mv in rig.movements:
        status = "PASS" if mv.passed else "FAIL"
        if not mv.passed:
            all_pass = False
        print(f"  [{status}] ({mv.key}) {mv.description}")
        print(f"          {mv.detail}")
    print("=" * 78)

    # A verdict is only meaningful if everything that was supposed to run did.
    missing = PHASES - rig.phases_run
    if missing:
        all_pass = False
        print("INCOMPLETE RUN - these phases never executed:")
        for name in sorted(missing):
            print(f"  - {name}")
        print("A verdict over a partial run is not a verdict. Treat this as")
        print("FAIL regardless of what the movements above say.")

    if not rig.movements:
        all_pass = False
        print("NO MOVEMENTS WERE CHECKED. This used to print PASS (0/0).")

    # STEP 6 feeds the verdict. It did not before: `check_band_assembly`
    # never touched `rig.movements`, so every compressed row could report
    # FAIL while OVERALL said PASS and the script exited 0. That is the same
    # defect as the empty-movements one, one layer along, and it sat in the
    # step that proves band assembly works.
    if rig.band_assembly_ok is False:
        all_pass = False
        print("BAND ASSEMBLY FAILED - see STEP 6 above.")

    print(f"OVERALL: {'PASS' if all_pass else 'FAIL'} "
          f"({sum(1 for m in rig.movements if m.passed)}/{len(rig.movements)} movements, "
          f"{len(rig.phases_run)}/{len(PHASES)} phases)")
    return all_pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--keep", action="store_true", help="skip cleanup (debugging only)")
    args = ap.parse_args()

    rig = Rig(api_base=args.api_base)
    rig.session = SessionLocal()

    try:
        create_throwaway(rig)
        build_session_chain(rig)
        seeded = seed_buckets(rig)

        fire_consolidation_trigger(rig)
        # Fetched ONCE and threaded through both checks - see fetch_scored's
        # docstring: reading this endpoint is a mutation for scar-family rows
        # as of DWB-603, and calling it twice would tick fired_count between
        # the two checks for no reason either one needs.
        entries = fetch_scored(rig)
        check_movements(rig, seeded, entries)

        memory_full, _ = print_received_context(rig)
        check_band_assembly(rig, memory_full, entries)

        all_pass = print_table(rig)
        return 0 if all_pass else 1
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] exerciser raised: {type(e).__name__}: {e}")
        return 2
    finally:
        if not args.keep:
            cleanup(rig)
        else:
            print(f"\n[--keep set] leaving project_id={rig.project_id} "
                  f"agent_id={rig.agent_id} repo_path={rig.repo_path} in place")


if __name__ == "__main__":
    sys.exit(main())

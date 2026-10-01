# Path: tests/test_timestamp_convention_dwb634.py
# File: test_timestamp_convention_dwb634.py
# Created: 2026-10-01
# Purpose: DWB-634 - pin the second-precision storage convention across the four session-rollup timestamp pairs, so a value carrying a fraction can never store ahead of the event it records
# Caller: pytest
# Callees: app.services.timestamps, app.services.dwb_session, app.services.dwb_session_rollup, app.services.hook_tracking
# Data In: per-test db_session, factory fixtures, instants chosen to fall either side of a rounding boundary
# Data Out: Assertions on stored values, cross-path agreement, and rollup membership
# Last Modified: 2026-10-01

"""Two conventions met in one comparison, and one of them rounds.

MySQL does not truncate a value carrying a fractional second on the way into
a second-precision `DATETIME`; it ROUNDS IT HALF-UP. A value generated at
second precision has no fraction and so is not rounded. Measured on the live
server (8.0.43) before this file was written:

    python 12:00:00.400 -> stored 12:00:00      NOW()                truncates
    python 12:00:00.500 -> stored 12:00:01      NOW(3)               ROUNDS UP
    python 12:00:00.635 -> stored 12:00:01      CAST(NOW(3) AS DATETIME) ROUNDS UP

So a Python-stamped bound at :00.635 is stored at :01 - half a second in the
FUTURE - while a server-stamped row genuinely created afterwards at :00.800
stores at :00 and looks earlier. Comparing the two carries up to a full second
of error, in exactly the direction that defeats an ordering check.

WHY THE EXISTING SUITE COULD NOT SEE THIS. `test_dwb_session_rollup.py`
builds its instants through a local `_naive_now()` that already calls
`.replace(microsecond=0)`. Every fixture in it is therefore second-precision
on both sides and the asymmetry cancels. A corpus cannot exercise a case the
corpus does not contain, which is why these tests construct the fractional
instants explicitly rather than taking whatever the clock offers.

HOW THESE TESTS AVOID BEING A CLOSED LOOP. The ordering tests need to know
what the server default stores for a given real instant. They do NOT assume
it: `test_server_default_truncates_live` measures it by actually letting
`NOW()` fire and bracketing it with `NOW(3)` reads either side. The other
tests then rely on that measured premise, so the premise is pinned by a
different mechanism than the one that consumes it. If MySQL's behaviour ever
changes, that test goes red first and names the reason.

NOT A TOLERANCE WINDOW. DWB-633's non-goal applies here unchanged. Nothing
below asserts "within one second"; the whole point is that the stored values
are EQUAL to the truncated instant and ordered like the real events.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.comment import Comment
from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus
from app.models.ticket import Ticket
from app.models.tracking_log import TrackingLog
from app.services import dwb_session as dwb_session_service
from app.services import dwb_session_rollup, timestamps


# Instants either side of the half-second rounding boundary. The .5 and above
# cases are the ones that round UP and so store in the future; the low ones are
# included so a fix that simply floors everything is not the only thing these
# tests can distinguish from a fix that rounds.
FRACTIONAL = [0, 400_000, 500_000, 635_000, 749_000, 999_999]

BASE = datetime(2026, 10, 1, 12, 0, 0)


# ---------------------------------------------------------------------------
# The premise, measured rather than assumed
# ---------------------------------------------------------------------------


def test_server_default_truncates_live(db_session):
    """`NOW()` into a second-precision column never lands ahead of the event.

    This is the premise the ordering tests below consume, so it is measured
    here against the real server instead of being asserted from the model
    declaration. Bracketing with `NOW(3)` either side of the insert is what
    makes it a measurement: the stored value must not exceed an instant that
    had already passed when the row was written.
    """
    db_session.execute(
        text("create temporary table dwb634_t (id int auto_increment primary key, v datetime)")
    )
    # Precondition, asserted in the probe rather than in the reader's head:
    # a column that was not second-precision would make every result below
    # meaningless while still passing.
    cols = db_session.execute(text("show columns from dwb634_t")).all()
    kinds = {c[0]: c[1] for c in cols}
    assert kinds["v"] == "datetime", f"probe column is {kinds['v']}, not second-precision"

    for _ in range(25):
        before = db_session.execute(text("select NOW(3)")).scalar()
        db_session.execute(text("insert into dwb634_t (v) values (NOW())"))
        after = db_session.execute(text("select NOW(3)")).scalar()
        stored = db_session.execute(
            text("select v from dwb634_t order by id desc limit 1")
        ).scalar()
        assert stored <= after, (
            f"NOW() stored {stored}, which is ahead of {after}, an instant that "
            "had already passed when the row was written"
        )
        assert stored >= before.replace(microsecond=0)


def test_a_fraction_rounds_up_on_storage(db_session):
    """The defect in one line: a fraction at or above .5 stores in the future.

    Kept as its own test because every other assertion in this file is about
    the CONSEQUENCE. If this one ever goes green on its own, the server stopped
    rounding and most of this file is guarding something that no longer happens.
    """
    db_session.execute(
        text("create temporary table dwb634_r (id int auto_increment primary key, v datetime)")
    )
    rounded_up = []
    for micro in FRACTIONAL:
        moment = BASE.replace(microsecond=micro)
        db_session.execute(text("insert into dwb634_r (v) values (:v)"), {"v": moment})
        stored = db_session.execute(
            text("select v from dwb634_r order by id desc limit 1")
        ).scalar()
        if stored > moment:
            rounded_up.append((moment.isoformat(), stored.isoformat()))

    assert rounded_up, (
        "no fractional instant stored ahead of itself; the rounding this ticket "
        "exists to neutralise was not reproduced, so the rest of this file is "
        "guarding a defect that is not present"
    )


# ---------------------------------------------------------------------------
# AC2 - no stored timestamp is ever ahead of the real event it records
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("micro", FRACTIONAL)
def test_open_stamp_never_stored_ahead_of_the_real_open(db_session, make_project, micro):
    """A window bound must not name a moment that has not happened yet."""
    project = make_project()
    moment = BASE.replace(microsecond=micro)

    row, _ = dwb_session_service.open_session(
        db_session,
        project_id=project["id"],
        open_method=DwbOpenMethod.regex,
        opened_at=moment,
    )
    db_session.flush()
    stored = db_session.execute(
        text("select opened_at from dwb_sessions where id = :i"), {"i": row.id}
    ).scalar()

    assert stored <= moment.replace(tzinfo=None), (
        f"opened_at for a session opened at {moment.time()} stored as "
        f"{stored.time()}, which is in the future relative to the event"
    )


@pytest.mark.parametrize("micro", FRACTIONAL)
def test_close_stamp_never_stored_ahead_of_the_real_close(
    db_session, make_project, micro
):
    """Same property on the other bound of the same window."""
    project = make_project()
    opened = BASE - timedelta(minutes=5)
    row, _ = dwb_session_service.open_session(
        db_session,
        project_id=project["id"],
        open_method=DwbOpenMethod.regex,
        opened_at=opened,
    )
    moment = BASE.replace(microsecond=micro)
    dwb_session_service.close_session(
        db_session,
        row,
        close_method=DwbCloseMethod.slash,
        close_reason=DwbCloseReason.explicit,
        now=moment,
    )
    db_session.flush()
    stored = db_session.execute(
        text("select closed_at from dwb_sessions where id = :i"), {"i": row.id}
    ).scalar()

    assert stored <= moment.replace(tzinfo=None), (
        f"closed_at stored as {stored.time()} for a close at {moment.time()}"
    )


# ---------------------------------------------------------------------------
# AC1 - two events whose real order is known store in that order
# ---------------------------------------------------------------------------


def _server_stamp_for(moment: datetime) -> datetime:
    """What the server default stores for a real instant.

    Truncation, which `test_server_default_truncates_live` measures rather than
    assumes. Written as a helper so the premise has one name and one place to
    change if that test ever reports something different.
    """
    return moment.replace(microsecond=0)


@pytest.mark.parametrize("micro", [500_000, 635_000, 749_000, 999_999])
def test_a_later_event_does_not_store_before_an_earlier_window_bound(
    db_session, make_project, micro
):
    """The ordering inversion, driven sub-second either side of the bound.

    Event A is the session open, Python-stamped. Event B is a hook session that
    really starts AFTER it, server-stamped. Their stored values must preserve
    that order. Before the fix, A rounds up past B and the later event looks
    earlier.
    """
    project = make_project()
    a_real = BASE.replace(microsecond=micro)          # the session opens
    b_real = a_real + timedelta(milliseconds=1)        # a hook starts, just after

    session, _ = dwb_session_service.open_session(
        db_session,
        project_id=project["id"],
        open_method=DwbOpenMethod.regex,
        opened_at=a_real,
    )
    db_session.flush()

    hook = HookSession(
        session_id=f"dwb634-{micro}",
        project_id=project["id"],
        status=HookSessionStatus.active,
        start_time=_server_stamp_for(b_real),
    )
    db_session.add(hook)
    db_session.flush()

    stored_a = db_session.execute(
        text("select opened_at from dwb_sessions where id = :i"), {"i": session.id}
    ).scalar()
    stored_b = db_session.execute(
        text("select start_time from hook_sessions where id = :i"), {"i": hook.id}
    ).scalar()

    assert stored_a <= stored_b, (
        f"session opened at {a_real.time()} stored as {stored_a.time()}; a hook "
        f"session that really started later, at {b_real.time()}, stored as "
        f"{stored_b.time()}. The later event is recorded first."
    )


# ---------------------------------------------------------------------------
# The outcome at the layer that reads it: the rollup window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("micro", [500_000, 635_000, 999_999])
def test_rollup_counts_a_hook_session_that_really_started_inside_the_window(
    db_session, make_project, make_agent, micro
):
    """The consequence the dashboard shows: work inside the window is counted.

    `compute_by_role` filters on `HookSession.end_time >= win_start`. When the
    bound rounds forward past a row that genuinely falls inside the window, the
    row drops out of the rollup and its tokens vanish from the session total.
    """
    project = make_project()
    agent = make_agent(project_id=project["id"])
    a_real = BASE.replace(microsecond=micro)
    b_real = a_real + timedelta(milliseconds=1)

    session, _ = dwb_session_service.open_session(
        db_session,
        project_id=project["id"],
        open_method=DwbOpenMethod.regex,
        opened_at=a_real,
    )
    db_session.flush()

    hook = HookSession(
        session_id=f"dwb634-rollup-{micro}",
        project_id=project["id"],
        agent_id=agent["id"],
        status=HookSessionStatus.completed,
        start_time=_server_stamp_for(b_real),
        # SHORT, and that is the whole point. A thirty-second session survives
        # a bound that rounds forward by one second, so it would pass against
        # the defect and prove nothing. This one begins and ends inside the
        # same second as the bound, which is the only shape that discriminates.
        end_time=_server_stamp_for(b_real + timedelta(milliseconds=1)),
        total_tokens=4242,
    )
    db_session.add(hook)
    db_session.flush()

    rows = dwb_session_rollup.compute_by_role(
        db_session, session, now=a_real.replace(microsecond=0) + timedelta(hours=1)
    )
    tokens = sum(r["tokens"] for r in rows)

    assert tokens == 4242, (
        f"a hook session that started inside the window contributed {tokens} "
        "tokens to the rollup; the window bound rounded forward past it"
    )


# ---------------------------------------------------------------------------
# AC4 - one convention per column, across every insert path
# ---------------------------------------------------------------------------


def test_hook_session_start_time_carries_one_convention_on_both_paths(
    db_session, make_project
):
    """The column the ticket flagged: server default on some paths, Python on others.

    `server_default` is a DDL default and fires only when the column is OMITTED
    on insert. `hook_tracking` assigns `start_time` explicitly on the
    SubagentStop path, so the column carried both conventions and the rows were
    indistinguishable afterwards. Both paths must now land on the same one.
    """
    project = make_project()
    moment = BASE.replace(microsecond=635_000)

    omitted = HookSession(
        session_id="dwb634-omitted",
        project_id=project["id"],
        status=HookSessionStatus.active,
    )
    db_session.add(omitted)
    db_session.flush()

    explicit = HookSession(
        session_id="dwb634-explicit",
        project_id=project["id"],
        status=HookSessionStatus.active,
        start_time=timestamps.naive_utc_second(moment),
    )
    db_session.add(explicit)
    db_session.flush()

    for row, label in ((omitted, "server default"), (explicit, "explicit assignment")):
        stored = db_session.execute(
            text("select start_time from hook_sessions where id = :i"), {"i": row.id}
        ).scalar()
        assert stored.microsecond == 0, f"{label} path stored a fraction: {stored}"

    explicit_stored = db_session.execute(
        text("select start_time from hook_sessions where id = :i"), {"i": explicit.id}
    ).scalar()
    assert explicit_stored <= moment, (
        "the explicit path stored ahead of the instant it was given"
    )


@pytest.mark.parametrize(
    "model, column, kwargs_factory",
    [
        (TrackingLog, "timestamp", None),
        (Ticket, "created_at", None),
        (Comment, "created_at", None),
    ],
)
def test_server_stamped_columns_store_without_a_fraction(
    db_session, make_project, make_agent, make_ticket, model, column, kwargs_factory
):
    """The other three pairs, confirmed at the column rather than the model.

    The declaration says `server_default=func.now()`. That is a statement about
    what happens when the column is omitted, not a guarantee about the stored
    value, which is the distinction this whole ticket turns on. So read the
    stored value back.
    """
    project = make_project()
    agent = make_agent(project_id=project["id"])
    if model is TrackingLog:
        row = TrackingLog(
            agent_id=agent["id"],
            project_id=project["id"],
            event_type="start",
        )
        db_session.add(row)
        db_session.flush()
        row_id, table = row.id, "tracking_log"
    elif model is Ticket:
        ticket = make_ticket(project_id=project["id"])
        row_id, table = ticket["id"], "tickets"
    else:
        ticket = make_ticket(project_id=project["id"])
        # author_agent_id, not agent_id - the Comment model names it for the
        # role rather than the relation.
        row = Comment(
            ticket_id=ticket["id"], author_agent_id=agent["id"], body="dwb634"
        )
        db_session.add(row)
        db_session.flush()
        row_id, table = row.id, "comments"

    stored = db_session.execute(
        text(f"select {column} from {table} where id = :i"), {"i": row_id}
    ).scalar()
    assert stored is not None
    assert stored.microsecond == 0, (
        f"{table}.{column} stored {stored} with a fractional second"
    )


# ---------------------------------------------------------------------------
# AC3 - one shared helper, no site truncates privately
# ---------------------------------------------------------------------------


def test_no_module_truncates_privately():
    """Every truncation goes through the shared helper.

    A DISCOVERY CHECK NEEDS A NON-EMPTY ASSERTION, or a rename empties the
    search and the test passes over nothing while reading as coverage. The
    second assertion below names the module that is ALLOWED to contain the
    literal, so deleting or renaming it fails here rather than silently
    disarming the guard.
    """
    import pathlib

    app_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    needle = "replace(microsecond=0)"
    offenders = {
        str(p.relative_to(app_root))
        for p in app_root.rglob("*.py")
        if needle in p.read_text()
    }

    allowed = {"services/timestamps.py"}
    assert allowed <= offenders, (
        f"the shared helper {allowed} no longer contains {needle!r}; this guard "
        "is searching for something that has moved and would pass over nothing"
    )
    assert offenders == allowed, (
        f"these modules truncate privately instead of calling the shared helper: "
        f"{sorted(offenders - allowed)}"
    )


# ---------------------------------------------------------------------------
# AC1 for the remaining three pairs - the PROPERTY, not the proxy
# ---------------------------------------------------------------------------


def _round_half_up_to_second(moment: datetime) -> datetime:
    """What a fractional instant WOULD have stored as before the fix.

    MySQL rounds half-up into a second-precision DATETIME. Reproduced here in
    Python so each case below can prove it is a case where the defect would
    actually have bitten.
    """
    if moment.microsecond >= 500_000:
        return moment.replace(microsecond=0) + timedelta(seconds=1)
    return moment.replace(microsecond=0)


def _insert_server_stamped(db, table, column, value, *, project, agent, make_ticket):
    """A row whose timestamp column holds what the server default would have
    written at that instant, i.e. the truncation that
    `test_server_default_truncates_live` measures.
    """
    if table == "tracking_log":
        row = TrackingLog(
            agent_id=agent["id"], project_id=project["id"],
            event_type="start", timestamp=value,
        )
        db.add(row)
        db.flush()
        return row.id
    ticket = make_ticket(project_id=project["id"])
    if table == "tickets":
        db.execute(
            text("update tickets set created_at = :v where id = :i"),
            {"v": value, "i": ticket["id"]},
        )
        return ticket["id"]
    row = Comment(
        ticket_id=ticket["id"], author_agent_id=agent["id"],
        body="dwb634", created_at=value,
    )
    db.add(row)
    db.flush()
    return row.id


@pytest.mark.parametrize("micro", [500_000, 635_000, 749_000])
@pytest.mark.parametrize(
    "table, column",
    [("tracking_log", "timestamp"), ("tickets", "created_at"), ("comments", "created_at")],
)
def test_later_server_stamped_row_does_not_store_before_the_window_bound(
    db_session, make_project, make_agent, make_ticket, table, column, micro
):
    """The three pairs that were resting on `microsecond == 0`.

    THE PROXY AND THE PROPERTY ARE DIFFERENT CLAIMS. "This value has no
    fraction" is a fact about one side. The ticket exists for a fact about
    BOTH: that two events whose real order is known store in that order. A
    column could satisfy the first and still be compared against a bound that
    rounds forward past it, which is exactly the defect.

    The gap was invisible from the test names. Reviewing this file by reading
    `test_a_later_event_does_not_store_before_an_earlier_window_bound` reads as
    covering every pair; it covered one. Names are claims and nothing checks
    them, so the parametrisation here NAMES each table it covers.

    Same construction as the HookSession pair: event A is the Python-stamped
    window bound, event B is a server-stamped row that really happens after it.
    """
    project = make_project()
    agent = make_agent(project_id=project["id"])
    a_real = BASE.replace(microsecond=micro)        # the session opens
    b_real = a_real + timedelta(milliseconds=1)     # the row is written, just after

    session, _ = dwb_session_service.open_session(
        db_session, project_id=project["id"],
        open_method=DwbOpenMethod.regex, opened_at=a_real,
    )
    db_session.flush()

    row_id = _insert_server_stamped(
        db_session, table, column, _server_stamp_for(b_real),
        project=project, agent=agent, make_ticket=make_ticket,
    )

    stored_a = db_session.execute(
        text("select opened_at from dwb_sessions where id = :i"), {"i": session.id}
    ).scalar()
    stored_b = db_session.execute(
        text(f"select {column} from {table} where id = :i"), {"i": row_id}
    ).scalar()

    # THIS CASE MUST BE ONE WHERE THE DEFECT WOULD HAVE BITTEN, or the
    # assertion below passes without distinguishing the fix from its absence.
    # The fix is already in the tree and cannot be reverted here (other agents
    # are reading these files), so the discrimination is asserted directly
    # rather than demonstrated by mutation.
    would_have_stored = _round_half_up_to_second(a_real)
    assert would_have_stored > stored_b, (
        f"input cannot discriminate: pre-fix the bound would have stored as "
        f"{would_have_stored.time()}, which is already <= {stored_b.time()}"
    )

    assert stored_a <= stored_b, (
        f"session opened at {a_real.time()} stored as {stored_a.time()}; "
        f"{table}.{column} for a row written later, at {b_real.time()}, stored "
        f"as {stored_b.time()}. The later event is recorded first."
    )

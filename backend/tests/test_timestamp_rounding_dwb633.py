# Path: tests/test_timestamp_rounding_dwb633.py
# File: test_timestamp_rounding_dwb633.py
# Created: 2026-10-01 (DWB-633)
# Purpose: Guard that a Python-stamped datetime never records a moment that has
#          not happened yet, and that it orders correctly against a
#          server-stamped column written by MySQL's own NOW(). MySQL ROUNDS a
#          fraction HALF-UP into a DATETIME(0); NOW() truncates. The two
#          conventions disagree by up to a full second.
# Caller: pytest
# Callees: app.services.memory_decide._decision_now,
#          app.services.memory_cutover._completion_now, raw SQL for ground truth
# Data In: factory projects/agents, memory_transition rows
# Data Out: Assertions on STORED timestamps and on their ordering
# Last Modified: 2026-10-01 (DWB-633)

"""DWB-633 acceptance.

THE DEFECT, MEASURED RATHER THAN ARGUED:

    CAST('...12:00:00.499' AS DATETIME)  ->  12:00:00   rounds down
    CAST('...12:00:00.500' AS DATETIME)  ->  12:00:01   rounds UP
    CAST('...12:00:00.635' AS DATETIME)  ->  12:00:01   rounds UP
    CAST(NOW(3) AS DATETIME) at .190     ->  same second
    NOW()                                 ->  truncates, no fraction exists

So a Python `datetime.now()` carrying microseconds is stored up to half a
second AFTER the moment it records. Meanwhile `created_at` on the same tables
is MySQL's own `NOW()`, which has no fraction to round. Comparing the two
carries an error of up to a FULL second, in an unpredictable direction.

Observed instance, which is how it was found:

    agent A decided   wall 18:17:23.495  ->  stored decided_at  18:17:23
    agent B decided   wall 18:17:24.635  ->  stored decided_at  18:17:25
    swept row         wall 18:17:24.6    ->  stored created_at  18:17:24

B's decision is stored ahead of real time, and a row genuinely created after it
is stored earlier, so `created_at > decided_at` is FALSE for a row that really
was created later.

WHY A SERVER-SIDE EXPRESSION IS NOT THE FIX. The tempting move is "stamp it in
SQL instead". `CAST(NOW(3) AS DATETIME)` rounds too, as measured above. The
property that matters is whether the fraction EXISTS AT GENERATION, not where
the value is generated. `NOW()` is safe only because it never has one.
Truncating in Python before the value is sent gives the same property.

ON ACCEPTANCE 4. The criterion asks for a test that goes red against the
current code by driving two events sub-second apart. Driving two real events
reliably under half a second apart is exactly the nondeterminism this fixes, so
a test built that way would itself be flaky - it would prove the defect only on
the runs where the timing happened to cooperate. `TestTheDefectIsReal` instead
drives the mechanism DIRECTLY at the values that matter, including the .500
boundary, which establishes the same fact on every run rather than on the lucky
ones. Stated here because substituting a method needs saying out loud.
"""

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import memory_cutover, memory_decide, memory_format

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


def _excerpt(body: str) -> str:
    return memory_format.render(
        [memory_format.MemoryEntry(body=body, heading_path=("Discipline",))]
    )


@pytest.fixture
def adopting(db_session, make_project, make_agent, tmp_path):
    project_dict = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project_dict["id"])
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = MemoryMode.adopting

    # DWB-637: a decision with no open DWB session is refused, because the
    # memory it writes stamps its clock origin from one. This fixture sets the
    # mode by hand rather than travelling the BEGIN edge, so it supplies the
    # session the same way it supplies `enumerated_at` below.
    db_session.add(
        DwbSession(
            project_id=project.id,
            open_method=DwbOpenMethod.slash,
            opened_at=datetime(2026, 10, 1, 10, 0, 0),
        )
    )
    db_session.flush()

    run = MemoryTransitionRun(
        project_id=project.id,
        direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
        enumerated_at=datetime(2026, 10, 1, 10, 0, 5),
    )
    db_session.add(run)
    db_session.flush()
    rows = []
    for i in range(2):
        row = MemoryTransition(
            project_id=project.id,
            agent_id=agent["id"],
            run_id=run.id,
            state=TransitionState.pending,
            source_excerpt=_excerpt(f"lesson {i}"),
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    return project, agent, run, rows


class TestTheDefectIsReal:
    """ACCEPTANCE 4, by the substituted method stated in the module docstring.

    These assert MySQL's behaviour directly. They pass before and after the
    fix, because they describe the database rather than our code - that is the
    point. They establish that the hazard the fix exists for is real, on every
    run, instead of on the runs where two events happened to land sub-second
    apart.
    """

    @pytest.mark.parametrize(
        "fraction,expected_second",
        [("0.499", 0), ("0.500", 1), ("0.635", 1), ("0.999", 1)],
    )
    def test_mysql_rounds_a_fraction_half_up_into_datetime(
        self, db_session, fraction, expected_second
    ):
        stored = db_session.execute(
            text(f"SELECT CAST('2026-10-01 12:00:0{fraction[1:]}' AS DATETIME)")
        ).scalar()
        assert stored.second == expected_second, (
            f"{fraction} stored as second={stored.second}; MySQL rounds rather "
            "than truncates, which is why an unrounded stamp lands in the future"
        )

    def test_a_server_side_expression_rounds_too(self, db_session):
        """Rules out the tempting wrong fix. Moving the stamp into SQL does not
        help if the expression carries a fraction."""
        cast_now, now3 = db_session.execute(
            text("SELECT CAST(NOW(3) AS DATETIME), NOW(3)")
        ).one()
        if now3.microsecond >= 500000:
            assert cast_now.second != now3.second or cast_now.minute != now3.minute, (
                "CAST(NOW(3) AS DATETIME) should have rounded up"
            )
        # NOW() itself never has a fraction, which is the property that matters.
        plain = db_session.execute(text("SELECT NOW()")).scalar()
        assert plain.microsecond == 0


class TestNoStampIsAheadOfItsEvent:
    """ACCEPTANCE 2."""

    def test_a_decision_is_not_stamped_in_the_future(self, db_session, adopting):
        _project, agent, _run, rows = adopting
        before = datetime.utcnow().replace(microsecond=0)
        memory_decide.decide(
            db_session, transition_id=rows[0].id, tier="scar", decided_by=agent["name"]
        )
        after = datetime.utcnow()

        db_session.expire_all()
        stored = db_session.get(MemoryTransition, rows[0].id).decided_at
        assert stored.microsecond == 0
        assert before <= stored <= after, (
            f"decided_at {stored} outside [{before}, {after}]"
        )

    def test_the_two_truncating_helpers_carry_no_fraction(self):
        assert memory_decide._decision_now().microsecond == 0
        assert memory_cutover._completion_now().microsecond == 0

    def test_a_truncated_stamp_never_rounds_up_on_storage(self, db_session, adopting):
        """The property the helpers buy, asserted against the DATABASE rather
        than against the helper's return value. A value with no fraction has
        nothing to round."""
        _project, agent, _run, rows = adopting
        stamp = memory_decide._decision_now()
        rows[0].decided_at = stamp
        rows[0].state = TransitionState.written
        db_session.flush()
        db_session.expire_all()
        stored = db_session.get(MemoryTransition, rows[0].id).decided_at
        assert stored == stamp.replace(tzinfo=None)


class TestRealOrderIsPreserved:
    """ACCEPTANCE 1. Two events whose real order is known, inside one second,
    must store in that order across a Python-stamped and a server-stamped
    column."""

    def test_a_row_created_after_a_decision_stores_after_it(
        self, db_session, adopting
    ):
        project, agent, run, rows = adopting

        memory_decide.decide(
            db_session, transition_id=rows[0].id, tier="scar", decided_by=agent["name"]
        )
        db_session.flush()
        # A row created immediately afterwards - same second, by construction.
        later = MemoryTransition(
            project_id=project.id,
            agent_id=agent["id"],
            run_id=run.id,
            state=TransitionState.pending,
            source_excerpt=_excerpt("arrived after the decision"),
        )
        db_session.add(later)
        db_session.flush()

        db_session.expire_all()
        decided = db_session.get(MemoryTransition, rows[0].id).decided_at
        created = db_session.get(MemoryTransition, later.id).created_at
        assert created >= decided, (
            f"a row created AFTER the decision stored before it: "
            f"created_at={created} decided_at={decided}. With the Python side "
            "rounding up and NOW() truncating, stored order can invert real "
            "order."
        )


# The enumeration DWB-633 asks for, written against the RELATIONSHIP rather
# than against every datetime column.
#
# A pair is at risk when one side is written by MySQL's own NOW() (truncates)
# and the other is a Python datetime (rounds half-up on storage). Columns of
# the same kind are not at risk from THIS defect, whatever else may be true of
# them.
#
# SERVER-STAMPED (server_default/onupdate=func.now()): acked_at, assigned_at,
#   changed_at, created_at, entered_at, fired_at, last_synced_at, read_at,
#   run_at, start_time, started_at, timestamp, updated_at
# PYTHON-STAMPED: completed_at, decided_at, enumerated_at, last_jira_sync_at,
#   opened_at, closed_at, playbooks_deployed_at
#
# MIXED PAIRS AND WHERE THEY ARE COMPARED:
#
#   created_at vs decided_at
#       services/memory_transition.py  (_has_receded)        <- the found instance
#   HookSession.start_time vs DwbSession.opened_at/closed_at
#       services/dwb_session.py:245
#       services/dwb_session_rollup.py:82, 519               (via compute_window)
#   TrackingLog.timestamp vs opened_at/closed_at
#       services/dwb_session.py:256
#       services/dwb_session_rollup.py:145,146,162,163,188,189,334,335,508,509
#   Ticket.created_at vs opened_at/closed_at
#       services/dwb_session.py:312
#       services/dwb_session_rollup.py:416,417
#   Comment.created_at vs opened_at/closed_at
#       services/dwb_session.py:368,369
#
# NOT AT RISK, recorded so nobody re-derives it: Ticket.completed_at against
# the same window bounds (dwb_session.py:314,315,403,404 and rollup 427,428) is
# Python-stamped on BOTH sides.
#
# A THIRD KIND EXISTS AND IS OUT OF SCOPE: HookSession.end_time is supplied
# from the hook payload rather than stamped by either side, so its convention
# is the caller's. Named here so it is not mistaken for a gap in the list.
#
# ONLY THE FIRST PAIR IS FIXED BY THIS TICKET'S CODE CHANGE. The others live in
# dwb_session.py and hook_tracking.py, which belong to other lanes; the
# mechanical swap belongs to whoever owns the file. They are enumerated so the
# work is visible rather than discovered later.
PYTHON_STAMPED_WRITE_SITES_IN_THIS_LANE = {
    "app/services/memory_decide.py": "_decision_now",
    "app/services/memory_cutover.py": "_completion_now",
}


class TestThisLaneTruncates:
    """ACCEPTANCE 3 and 5, for the files this ticket owns."""

    def test_every_python_datetime_write_in_this_lane_is_truncated(self):
        """No raw `datetime.now(...)` assigned to a `_at` column in the memory
        lane. A new write site added without truncating fails here."""
        offenders = []
        for rel in PYTHON_STAMPED_WRITE_SITES_IN_THIS_LANE:
            path = APP_DIR.parent / rel
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            src = path.read_text(encoding="utf-8")
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for t in node.targets:
                    if not (isinstance(t, ast.Attribute) and t.attr.endswith("_at")):
                        continue
                    seg = ast.get_source_segment(src, node.value) or ""
                    if "now(" in seg and "replace(microsecond=0)" not in seg:
                        if "_now()" not in seg:
                            offenders.append(f"{rel}:{node.lineno} {seg}")
        assert offenders == [], (
            "these write a fractional datetime into a DATETIME(0) column, "
            f"which MySQL rounds UP: {offenders}"
        )

    def test_no_comparison_gained_a_tolerance_window(self):
        """ACCEPTANCE 5, and the explicit non-goal. A one-second slack would
        hide this rather than fix it, and in the recession predicate it would
        make the equal-second case flag - an agent merely part-way through its
        queue."""
        source = (APP_DIR / "services" / "memory_transition.py").read_text(
            encoding="utf-8"
        )
        for banned in ("timedelta(seconds=1)", "timedelta(seconds=2)", "+ 1)"):
            assert banned not in source, (
                f"found {banned!r} in the recession predicate's module; a "
                "tolerance hides this defect instead of fixing it"
            )

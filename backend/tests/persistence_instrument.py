# Path: tests/persistence_instrument.py
# File: persistence_instrument.py
# Created: 2026-10-08 (DWB-653)
# Purpose: Two independent instruments for the question the harness cannot
#          answer - "did this write actually persist". A COMMIT CENSUS that
#          records, per request, whether any commit happened; and a REAL
#          persistence fixture that commits for real and reads back down a
#          second connection that can only see committed rows.
# Caller: tests/conftest.py (installs the census, re-exports the fixtures),
#         tests/test_persistence_instrument_dwb653.py
# Callees: sqlalchemy.orm.Session, app.main.app, app.database.get_db
# Data In: live test requests
# Data Out: CENSUS rows written to .pytest_cache/dwb653_commit_census.json;
#           persisting_client / readback fixtures
# Last Modified: 2026-10-08 (DWB-653)

"""The instrument DWB-653 asks for, in two pieces that can fail independently.

THE DEFECT BEING INSTRUMENTED. `conftest.db_session` opens one connection, begins
one transaction, builds one Session on it and hands that SAME session to the app
through `override_get_db`. The test then reads its own uncommitted writes back
out of the session that wrote them, and the whole transaction is rolled back at
teardown. A route that never commits is indistinguishable from one that does.
DWB-652 is a confirmed instance: it shipped green and sat undetected at 3047
passing tests.

WHY TWO INSTRUMENTS AND NOT ONE. Two readings of one pipeline are one instrument
run twice. These two can fail in different directions and are checked against
each other in test_persistence_instrument_dwb653.py:

  THE CENSUS is cheap, runs over the whole suite, and is SOUND IN THE NEGATIVE
  ONLY. It counts `Session.commit()` calls during each request. Zero commits
  during a 2xx write request is PROOF nothing persisted - there is no other way
  for a row to reach disk. One or more commits is EVIDENCE of persistence and
  not proof: a route could commit the wrong unit of work, or commit an empty
  one. It is a mechanism check, deliberately, and it is labelled as one
  everywhere it is reported.

  THE REAL FIXTURE is expensive, runs only where asked for, and is sound in
  BOTH directions. It gives the app a session that genuinely commits and reads
  the result back down a SECOND, INDEPENDENT connection, which by definition can
  only see committed rows. That is an outcome check.

The census answers "which of the 90 write routes cannot have persisted" across
the whole suite in one pass. The fixture proves any individual one, and is what
AC1's break/restore demonstration runs on.

ON THE COST OF THE REAL FIXTURE, because it decides the shape. It cannot use
rollback isolation - the thing under test is whether a commit happened, so the
data really lands and really has to be cleaned up. That makes it opt-in rather
than universal, which is also what the ticket asks for: the rollback harness is
correct for the ~3000 tests that assert behaviour, and only tests asserting
PERSISTENCE need to pay for it.
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session as SASession

CENSUS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / ".pytest_cache"
    / "dwb653_commit_census.json"
)


# ---------------------------------------------------------------------------
# Instrument 1: the commit census
# ---------------------------------------------------------------------------


class _CommitCounter:
    """Counts Session.commit() calls process-wide.

    A plain counter and not a per-session one: services in this codebase build
    their own sessions through `SessionLocal()` as well as using the injected
    one (`failed_hook` logging does, and `_record_memory_write` commits the
    injected one), and a commit through ANY of them is a commit that could have
    persisted the request's work. Counting the class method catches all of them,
    which is what makes a count of ZERO a sound negative.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.count = 0

    def bump(self) -> None:
        with self._lock:
            self.count += 1


COMMITS = _CommitCounter()
_ORIGINAL_COMMIT = SASession.commit
_INSTALLED = False


def install_commit_spy() -> None:
    """Wrap Session.commit so every call is counted. Idempotent.

    Wraps rather than replaces: the real commit still runs, so this changes no
    behaviour. Under the shared-session harness a `commit()` on a Session joined
    to an external transaction does not actually persist - but it is still
    CALLED, and the call is the thing being counted. That is precisely why the
    census can see the difference the assertions cannot.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    def counting_commit(self, *args, **kwargs):
        COMMITS.bump()
        return _ORIGINAL_COMMIT(self, *args, **kwargs)

    SASession.commit = counting_commit
    _INSTALLED = True


class CensusClient(TestClient):
    """A TestClient that records, per request, whether any commit occurred.

    Instrumented at the CLIENT rather than as app middleware on purpose.
    Middleware has to be installed before the app starts and would sit in the
    real server's stack as well; wrapping the client keeps the instrument
    entirely inside the test process and cannot change production behaviour.
    """

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        before = COMMITS.count
        response = super().request(method, url, *args, **kwargs)
        CENSUS.append(
            {
                "method": str(method).upper(),
                "url": str(url),
                "status": response.status_code,
                "commits": COMMITS.count - before,
            }
        )
        return response


CENSUS: list[dict] = []


def write_census() -> pathlib.Path | None:
    """Persist the census for the classification pass. Returns the path.

    WRITES ITS OWN PROVENANCE, AND THAT IS NOT DECORATION. Every pytest session
    ends here, so a FIVE-TEST run silently overwrites the census a full run
    produced. The classifier downstream cannot tell the difference from the rows
    alone - a partial census makes 86 of 90 routes read as NOT-COVERED, which is
    a plausible-looking catastrophe rather than an obvious error. That happened
    once, during this ticket: an 18-row census from an 8-test run replaced the
    8715-row one and would have been classified as a mass regression.

    So the file records WHAT PRODUCED IT - the argv, the timestamp, the row and
    request counts - and the classifier prints that banner before any verdict.
    The reader is then judging a census they can see the provenance of, instead
    of a number with no origin.
    """
    if not CENSUS:
        return None
    CENSUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "argv": sys.argv[1:],
            "requests": len(CENSUS),
            "write_requests": sum(
                1 for r in CENSUS if r["method"] in {"POST", "PATCH", "PUT", "DELETE"}
            ),
        },
        "rows": CENSUS,
    }
    CENSUS_PATH.write_text(json.dumps(payload))
    return CENSUS_PATH


# ---------------------------------------------------------------------------
# Instrument 2: real persistence
# ---------------------------------------------------------------------------


def _truncate_all(engine) -> None:
    """Empty every table in lat_test.

    FOREIGN_KEY_CHECKS is disabled around the loop because there is no ordering
    of these tables that satisfies every FK, and TRUNCATE will not drop a row a
    FK points at. Scoped to this connection only; it is restored before the
    connection is returned.
    """
    with engine.begin() as conn:
        names = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for name in names:
            conn.execute(text(f"TRUNCATE TABLE `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


class Readback:
    """A reader that can only see COMMITTED rows, and cannot be misread.

    THE WHOLE REASON THIS IS A CLASS AND NOT A BARE SESSION. MySQL here runs
    REPEATABLE READ. A session takes its snapshot at its FIRST read and holds it
    for the life of the transaction, so a bare session that was used once before
    the write under test would keep answering from the OLD snapshot afterwards -
    reporting a row still present long after another transaction deleted and
    committed. That failure looks exactly like "the route did not commit", which
    is the one answer this instrument exists to give. It would be an instrument
    that produces the defect it is looking for.

    So every accessor here ROLLS BACK FIRST. The rollback ends the current
    transaction and the next statement opens a new one with a fresh snapshot.
    There is no way to read through this object without that happening, which is
    the point: a correctness property that depends on remembering to call
    something is not a property.
    """

    def __init__(self, session):
        self._session = session

    @property
    def session(self):
        """The raw session, snapshot already discarded.

        For the rare case that needs to WRITE through the reader (flipping a
        column the API does not expose, say). Reads should use get/count.
        """
        self._session.rollback()
        return self._session

    def get(self, model, pk):
        self._session.rollback()
        return self._session.get(model, pk)

    def count(self, model) -> int:
        self._session.rollback()
        return self._session.query(model).count()

    def close(self):
        self._session.close()


@pytest.fixture
def persisting(request, db_session, engine_, session_factory_):
    """A client whose writes REALLY COMMIT, plus a reader on a second connection.

    Yields `(client, readback)`:
      - `client`  - a TestClient wired to a session that commits for real.
      - `readback`- a `Readback` on an INDEPENDENT connection. It is the whole
                    point: it has its own transaction and therefore can only see
                    rows another transaction has COMMITTED. If a route did not
                    commit, this reader cannot see its work, no matter what the
                    route returned. Every accessor discards its snapshot first -
                    see `Readback` for why that is not optional under
                    REPEATABLE READ.

    THE AUTOUSE ROLLBACK FIXTURE IS STOOD DOWN FIRST. `db_session` is autouse, so
    it has already opened a transaction on its own connection by the time this
    runs. Left open it would hold row locks that block the TRUNCATE in teardown,
    and its `override_get_db` would still be the one the app uses. It is rolled
    back and its override replaced here, then restored afterwards.

    CLEANUP IS A FULL TRUNCATE, in teardown, because the writes are real and
    rollback isolation is exactly what this fixture gives up. Measured at the
    bottom of test_persistence_instrument_dwb653.py so the cost is a number
    rather than a worry.
    """
    from app.database import get_db
    from app.main import app

    # Stand down the rollback harness for the duration.
    db_session.rollback()
    saved_overrides = dict(app.dependency_overrides)

    write_session = session_factory_()

    def override_get_db():
        try:
            yield write_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    readback = Readback(session_factory_())

    client = CensusClient(app)
    try:
        yield client, readback
    finally:
        readback.close()
        write_session.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        _truncate_all(engine_)

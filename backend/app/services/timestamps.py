# Path: app/services/timestamps.py
# File: timestamps.py
# Created: 2026-10-01
# Purpose: DWB-634 - the one place that drops a fractional second, so every writer of a second-precision DATETIME column agrees and no stamp can land ahead of the event it records
# Caller: app/services/dwb_session.py, app/services/dwb_session_rollup.py, app/services/hook_tracking.py, app/services/memory_decide.py, app/services/memory_cutover.py, app/services/jira_sync.py
# Callees: datetime (stdlib only - no DB, no models, deliberately dependency-free)
# Data In: datetime values, aware or naive, from callers and from the clock
# Data Out: datetime values with microsecond=0, tz handling unchanged from the caller's convention
# Last Modified: 2026-10-01

"""Second precision, in one place.

THE PROBLEM IS THE FRACTION, NOT THE WRITER. MySQL does not truncate a value
carrying a fractional second on the way into a `DATETIME`; it ROUNDS IT
HALF-UP. A value generated at second precision has no fraction and so is not
rounded. Measured on the live server (8.0.43):

    python 12:00:00.400         -> 12:00:00     NOW()                     truncates
    python 12:00:00.500         -> 12:00:01     NOW(3)                    ROUNDS UP
    python 12:00:00.635         -> 12:00:01     CAST(NOW(3) AS DATETIME)  ROUNDS UP

So a stamp at :00.635 is stored at :01, half a second in the FUTURE, while a
row genuinely written afterwards at :00.800 through a server default stores at
:00 and looks earlier. Any code ordering a Python-stamped column against a
server-stamped one inherits an error of up to a full second, in the direction
that defeats the comparison.

**MOVING A STAMP TO A SERVER-SIDE EXPRESSION DOES NOT FIX THIS.** That is the
tidy-looking change that reintroduces the bug, and it is tempting because the
asymmetry reads as "Python rounds, MySQL truncates". It is not about where the
value is generated. `NOW(3)` and `CAST(NOW(3) AS DATETIME)` both round. Plain
`NOW()` is safe only because it is GENERATED without a fraction. A server-side
expression is an acceptable substitute only if it generates at second
precision.

**TRUNCATION, NEVER ROUNDING.** A timestamp must not name a moment that has
not happened yet, so the fraction is dropped rather than rounded to nearest.
That is also what makes these functions agree with `NOW()` on every instant
rather than only on average.

**NOT A TOLERANCE WINDOW.** The fix is to make both sides agree at the source.
Comparisons stay exact. A one-second slack downstream would hide this while
blunting every predicate that depends on the ordering, and in at least one
live predicate it would also flag the equal-second case, which means something
entirely different (DWB-633).

TWO TIME CONVENTIONS EXIST IN THIS CODEBASE AND THIS MODULE KEEPS BOTH.
`memory_decide` and `memory_cutover` work in aware UTC; `dwb_session` and
`hook_tracking` work in naive UTC to match the MySQL columns. Unifying those
is a different change with a much wider blast radius, so each caller keeps the
convention it already had and only loses the fraction.
"""

from __future__ import annotations

from datetime import datetime, timezone


def truncate_to_second(value: datetime | None) -> datetime | None:
    """Drop the fractional second, preserving tzinfo and passing None through.

    The primitive. Everything else here is a convenience over it. `None` is
    passed through rather than rejected because several callers hold an
    optional timestamp (a close that has not happened, an end_time absent from
    a hook payload) and forcing each to guard would scatter the check.
    """
    if value is None:
        return None
    return value.replace(microsecond=0)


def aware_utc_now_second() -> datetime:
    """Now, as an aware UTC datetime, at second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def naive_utc_now_second() -> datetime:
    """Now, as a naive UTC datetime, at second precision.

    Naive to match the MySQL `DATETIME` columns, which carry no offset. Built
    from an aware reading rather than `utcnow()` so the conversion is explicit.
    """
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


def naive_utc_second(value: datetime | None) -> datetime | None:
    """A caller-supplied instant as naive UTC at second precision.

    Normalises the two things that have to be true before a value can be
    compared against a stored column at all: a consistent offset, and no
    fraction to round. Aware values are converted to UTC first, so the
    truncation happens on the UTC reading rather than on a local one.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0)

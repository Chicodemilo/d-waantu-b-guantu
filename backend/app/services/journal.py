# Path: app/services/journal.py
# File: journal.py
# Created: 2026-09-29 (DWB-587)
# Purpose: The human_memory journal - append an entry, and search it by tags,
#          date range and term. Every successful retrieval increments
#          retrieval_count here, which is the ONLY place that column is written.
# Caller: app/routers/journal.py
# Callees: app/models/journal_entry, app/services/dwb_session.get_active_session
# Data In: agent_id, body, tags; search filters (tags, date range, term)
# Data Out: JournalEntry rows plus a named retrieval status
# Last Modified: 2026-09-29 (DWB-587)

"""The journal (spec section 5).

Three properties here are load-bearing, and each one is easy to erode by a
change that looks like an improvement.

**There is no full dump.** A search with no filter is REFUSED. Section 5:
"Memory must shrink; the journal may sprawl. Opposite pressures, which is
precisely why they are two stores and not one." An unfiltered read pulls the
sprawl into context and the cost model that makes the journal free collapses. A
default page size does NOT satisfy this: page one of everything is still a read
nobody asked a question to get. `agent_id` deliberately does not count as a
filter either - scoping a dump to one agent is still a dump.

**The increment is server-side and unconditional.** Section 5: "Retrieval is the
reinforcement signal. Reaching for an entry is logged, dated and countable."
There is no request parameter that suppresses it, because a caller able to read
without being counted is a caller able to make the signal lie. It is applied to
exactly the rows returned, after they are selected.

**The count is permanent and never decays.** Section 5, verbatim: "the score is
transient; the count is permanent." The decay in section 3 applies to the
SCORE, which is derived at read time and is DWB-585's; nothing in this module
writes, resets or ages `retrieval_count`, and the single UPDATE below is the
only write site in the application. A test asserts that over the whole of app/.

OUT OF SCOPE, deliberately: section 3's JOURNAL-retrieved decay curve (10, then
5 to 2 to 0 over the following sessions). It cannot be computed from this
schema - `journal_entries` stores a count and no last-retrieved session - and
DWB-584 held the only migration slot. If the curve is wanted it needs
`last_retrieved_session_id` and a migration of its own. Do not derive it from
`entered_at`, which is when the entry was WRITTEN, not when it was last reached
for.
"""

from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.journal_entry import JournalEntry
from app.services import dwb_session as session_svc

# Section 5: "If I reach for it 3 times, write it somewhere." At three
# retrievals an entry stops being a story and becomes a rule, and becomes a
# promotion candidate for DWB-585's consolidation.
#
# Three is deliberately the SAME number as the existing bit-twice threshold for
# working facts, so the system has one number rather than two. Exported so
# DWB-585 imports it instead of writing a second 3 that can drift from this one.
PROMOTION_THRESHOLD = 3

# What happened on a search. Named, for the reason node_retrieval names its
# four: an empty list cannot distinguish "nothing matched" from "nothing ran",
# and that ambiguity hid a broken retrieval path for a whole sprint.
#
# There is no `not_attempted` value here and that is deliberate, not an
# oversight: a filterless request is REFUSED before the query, so there is no
# path on which this endpoint returns without having run. If a future change
# adds one, it needs a name, not a silent empty list.
COMPLETE = "complete"  # ran to the end; an empty list means nothing matched
TRUNCATED = "truncated"  # more rows matched than the limit returned

# The filters that count as ASKING A QUESTION. agent_id is missing on purpose:
# it scopes a dump, it does not narrow one.
REQUIRED_FILTERS = ("tags", "date_from", "date_to", "term")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class JournalError(Exception):
    """Raised by this module; the router maps `code` to a status."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def create_entry(
    db: Session,
    *,
    agent_id: int,
    body: str,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
) -> JournalEntry:
    """Append one journal entry.

    The section 4 moment-tags (cost, caught_by, surprised) are NOT here. They
    moved onto agent_memories in DWB-584: all three are read against memories,
    and section 2 gates the SCAN on `cost` while the SCAN runs over scars. The
    journal carries `tags`, a free list, which is what section 5's retrieval
    ("tags + date + term") actually queries.

    `retrieval_count` is NOT set here, not even to its own default. Leaving the
    column entirely to the schema default keeps this function off the list of
    places that write it, which is what makes the single-write-site guard in the
    tests a real claim rather than a convention.

    `dwb_session_id` is stamped from the project's open session when there is
    one, and left NULL when there is not. NULL means "written outside a
    session", which readers counting sessions must expect to skip.

    `created_at` (DWB-605): the memory's ORIGINAL date, when the caller has
    one - DWB-607's eviction passes the evicted memory's own created_at here,
    because that memory existed long before this journal entry does and
    `entered_at` (stamped below at journal-arrival time) is not that date.
    Omitted (the default, and every call site before DWB-607 exists), the
    column's own server_default applies and created_at == entered_at, which is
    the correct answer for an entry a session journals directly. Passed
    explicitly as None would try to insert NULL and fail the NOT NULL
    constraint, so this only sets the attribute when a real value is given -
    the model's server_default handles the omitted case, not this function.
    """
    if not body or not body.strip():
        raise JournalError(
            "empty_body", "body is required and cannot be empty or whitespace-only"
        )

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise JournalError("agent_not_found", f"agent id {agent_id} not found")

    active = None
    if agent.project_id is not None:
        active = session_svc.get_active_session(db, agent.project_id)

    entry = JournalEntry(
        agent_id=agent.id,
        dwb_session_id=active.id if active is not None else None,
        tags=tags,
        body=body,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(entry)
    # Flush, not commit: the router owns the transaction (project rule, and the
    # same split dwb_sessions uses). The flush is here because the caller needs
    # the generated id and the server-side entered_at default.
    db.flush()
    db.refresh(entry)
    return entry


def search_entries(
    db: Session,
    *,
    agent_id: int | None = None,
    tags: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    term: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Search the journal, and COUNT the retrieval.

    Refuses a request carrying none of REQUIRED_FILTERS. There is no shape of
    this call that returns the whole journal.

    Tag matching is ANY-of, not all-of. Section 5's example is "to do with Greg,
    or ssh" - the caller half-remembers the entry and offers several handles,
    so requiring every tag to match would answer the question the caller is not
    asking.

    Returns a dict carrying the rows AND the named status, as a pair, so a
    caller wanting the rows has to hold the thing that also says why there are
    that many of them.
    """
    supplied = {
        "tags": bool(tags),
        "date_from": date_from is not None,
        "date_to": date_to is not None,
        "term": bool(term and term.strip()),
    }
    if not any(supplied.values()):
        raise JournalError(
            "filter_required",
            "the journal is never read whole. Supply at least one of "
            f"{', '.join(REQUIRED_FILTERS)}. Spec section 5: memory must shrink and "
            "the journal may sprawl, so retrieval is a question (tags + date + term), "
            "never a full read. agent_id alone does not narrow a read, it only "
            "scopes one, so it does not satisfy this.",
        )

    if limit < 1:
        raise JournalError("invalid_limit", "limit must be at least 1")
    limit = min(limit, MAX_LIMIT)

    conditions = []
    if agent_id is not None:
        conditions.append(JournalEntry.agent_id == agent_id)
    if date_from is not None:
        conditions.append(JournalEntry.entered_at >= date_from)
    if date_to is not None:
        conditions.append(JournalEntry.entered_at <= date_to)
    if supplied["term"]:
        conditions.append(JournalEntry.body.like(f"%{term.strip()}%"))
    if tags:
        # ANY-of across the supplied tags. JSON_CONTAINS against the JSON column
        # rather than a LIKE over its serialized text: a LIKE for "ssh" would
        # also match a tag "ssh-config" and an entry whose BODY happened to
        # contain the word, which would quietly inflate the retrieval count for
        # entries nobody reached for.
        tag_clauses = [
            func.json_contains(JournalEntry.tags, func.json_quote(t)) == 1
            for t in tags
        ]
        conditions.append(or_(*tag_clauses))

    total_matched = db.execute(
        select(func.count()).select_from(JournalEntry).where(*conditions)
    ).scalar_one()

    rows = list(
        db.execute(
            select(JournalEntry)
            .where(*conditions)
            .order_by(JournalEntry.entered_at.desc(), JournalEntry.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    # THE ONLY WRITE SITE FOR retrieval_count IN THE APPLICATION.
    #
    # Applied to exactly the rows being returned, after selection, with no
    # parameter reaching it: a caller cannot read without being counted, which
    # is what makes the count a signal rather than a courtesy. Rows that matched
    # but fell outside the limit are NOT counted - they were not handed over, so
    # they were not reached for.
    #
    # One statement rather than a loop over rows: two increment blocks is how a
    # correct fix gets half-applied, and a single UPDATE is also what lets the
    # guard test assert "exactly one write site" and mean it.
    if rows:
        db.execute(
            update(JournalEntry)
            .where(JournalEntry.id.in_([r.id for r in rows]))
            .values(retrieval_count=JournalEntry.retrieval_count + 1)
            # synchronize_session="fetch" so the rows handed back carry the
            # count AFTER this retrieval. Returning the pre-increment value
            # would make the response disagree with the database about a number
            # whose whole job is to be counted.
            .execution_options(synchronize_session="fetch")
        )

    return {
        "status": TRUNCATED if total_matched > len(rows) else COMPLETE,
        "count": len(rows),
        "total_matched": total_matched,
        # Which filters actually narrowed this read. Present so an empty result
        # is readable: "ran with these filters and matched nothing" is a
        # different fact from "ran with no filters", and the caller can see
        # which one it got without guessing from the length of a list.
        "filters_applied": [name for name, used in supplied.items() if used],
        "entries": rows,
    }


def promotion_candidates(
    db: Session, *, agent_id: int | None = None
) -> list[JournalEntry]:
    """Entries at or past PROMOTION_THRESHOLD retrievals (spec section 5).

    Lives here, beside the threshold and the only writer of the column it reads,
    so DWB-585's consolidation calls this instead of re-implementing a
    `>= 3` of its own. Two copies of the threshold is how the system ends up
    with two numbers where the spec ruled there should be one.

    Ordered by count descending: the entry reached for most often is the one
    most overdue to stop being a story.
    """
    conditions = [JournalEntry.retrieval_count >= PROMOTION_THRESHOLD]
    if agent_id is not None:
        conditions.append(JournalEntry.agent_id == agent_id)
    return list(
        db.execute(
            select(JournalEntry)
            .where(*conditions)
            .order_by(JournalEntry.retrieval_count.desc(), JournalEntry.id.asc())
        )
        .scalars()
        .all()
    )

# Path: app/services/memory_origin.py
# File: memory_origin.py
# Created: 2026-10-07 (DWB-637)
# Purpose: ONE rule, at the one place a memory is born: a memory row may not be
#          inserted without a session to count its clock from. Owns the
#          precondition and the refusal text for every writer of
#          `agent_memories`.
# Caller: app/services/raw_memory.py, app/services/memory_decide.py,
#         app/services/memory_promote.py
# Callees: app/services/dwb_session.get_active_session, app/models/project
# Data In: db Session, a project id, the name of the act being refused
# Data Out: the open DwbSession, or MemoryOriginMissing
# Last Modified: 2026-10-07 (DWB-637)

"""A memory with no clock origin reads as stored and behaves as lost.

`agent_memories.created_session_id` is not bookkeeping. It is one half of the
clock origin `memory_score.sessions_since_reinforced` counts from -
`COALESCE(last_reinforced_session_id, created_session_id)`. With both NULL that
function returns None, `memory_score._entry` reports the row `scored: false`
with reason `no_session_origin` and a null band,
`memory_context.assemble_session_context` filters on band so the row appears in
no section, and `memory_mode.memory_full_for` falls through to the sealed
pointer. The row exists, counts in a row count, and can never reach an agent.

THIS HAS FIRED THREE TIMES: 396 rows on the first adoption, 216 across five IND
agents on the second, and once on a single write made seconds after a session
closed. Each time the row was written successfully and the failure surfaced
somewhere else, as an agent spawning with no memory and a full store behind it.

WHY THIS IS A MODULE AND NOT A LINE IN EACH WRITER. Two partial fixes already
existed and neither held. `memory_decide` stamped the origin from the active
session and fell back to None; `project.py` refused to BEGIN an adoption with
no session open, once, at the mode flip, while the stamp ran per decision - 308
times on IND - so a session closing mid-run returned every remaining row to
NULL with nothing re-checking. A rule that each writer restates is a rule the
next writer restates wrong, and the recurrence is the evidence. Every caller
that inserts into `agent_memories` resolves its origin through this module, and
the test that enumerates the write sites (tests/test_memory_origin_dwb637.py)
fails when a new one appears that does not.

WHAT THIS OVERRULES, STATED RATHER THAN DELETED. `raw_memory`'s module
docstring and `memory_decide.decide`'s comment both argued that accepting a
write with no open session is correct, because "losing the lesson because the
bookkeeping was not ready" is the worse outcome. That trade is false in both
directions:

  - An unscoreable row is not a kept lesson. It is a lost one that still counts
    in a row count, which is strictly worse than a visible refusal because
    nobody goes looking for it.
  - Nothing is lost by refusing. The refusal writes nothing, names the fix, and
    the identical request succeeds once a session is open. A 400 is recoverable
    in one call; a NULL origin needed a human ruling and a backfill script.

WHY REFUSE RATHER THAN AUTO-OPEN A SESSION (Miles, 2026-10-07). Opening one to
paper over the gap invents a session boundary that did not happen, which is the
same class of error as stamping now() on a backfill. A DWB session is open
whenever agents are working; when none is open, nothing should be writing
memory. `created_session_id` is an FK to `dwb_sessions`, so there is no
synthetic value to stamp instead - the session has to genuinely exist.

THE TWO RULES BELOW ARE DIFFERENT ON PURPOSE, and the difference is about who
is holding the request, not about how much the row matters.

`require_session_origin` is for a write somebody ASKED FOR: a raw append, an
adopt decision. There is a caller to answer, the refusal reaches them, and the
retry is theirs to make.

`deferrable_session_origin` is for a write a BACKGROUND PASS proposes:
consolidation promoting a journal entry to CORE. There is nobody to answer, the
caller is a hook that must not block, and the source of the promotion is a
journal entry that stays exactly where it is - `memory_promote` recomputes its
candidates from `source_journal_id` every pass, so a promotion skipped for want
of a session is proposed again, unchanged, on the next pass that has one.
Raising there would convert a recoverable deferral into a failed hook.

The invariant is the same in both: no row is inserted without an origin.
"""

from sqlalchemy.orm import Session

from app.models.dwb_session import DwbSession
from app.models.project import Project
from app.services import dwb_session as session_svc

# The one code this module raises. Named so a router maps it without matching
# on message text, and so a reader greping for the refusal finds the rule.
NO_SESSION_ORIGIN = "no_session_origin"


class MemoryOriginMissing(Exception):
    """No DWB session is open, so an inserted memory would have no clock origin.

    Carries `code` and `detail` to match the shape `RawMemoryWriteError` and
    `DecideError` already use, so each writer's existing router mapping needs
    one more branch rather than a new error-handling path.
    """

    def __init__(self, detail: str):
        self.code = NO_SESSION_ORIGIN
        self.detail = detail
        super().__init__(detail)


def _refusal(project: Project | None, project_id: int, action: str) -> str:
    """The refusal text. One copy, so every writer refuses with the same words.

    Names the reason and the fix, in that order, because a refusal that states
    only the rule gets worked around and one that states only the fix teaches
    nothing. The closing sentence exists to answer the question the refused
    caller actually has - whether their lesson just went in the bin.

    THE FIX LINE MAKES NO ASSUMPTION ABOUT WHO IS READING IT, and that is a
    correction rather than a style choice. It used to read "Open a session first
    (/dwb-open, or POST /api/sessions/open)", which is right for a TL and wrong
    for the agent most likely to hit this: session lifecycle is the TL's
    (team-lead playbook section 4e) and workers never participate in it. So the
    refusal was instructing a blocked worker, at the moment it was most likely
    to comply, to do something it is not permitted to do - which either gets
    ignored, training workers to skim refusals, or gets followed.

    Conditional rather than branched by caller. Branching would work today and
    carries an actor assumption per branch that goes stale the moment a new
    caller appears, which is the same failure this module exists to stop: one
    rule in one place beats a rule each caller restates for itself. The routes
    stay, in parentheses, so the line is still actionable for whoever can act.
    """
    who = project.prefix if project is not None else f"project {project_id}"
    return (
        f"{action} refused: {who} has no open DWB session.\n"
        "\n"
        "A memory stamps its clock origin from the session open when it is "
        "written. With none open that origin is NULL, and a memory with no "
        "origin cannot be scored: it is excluded from every candidate list, "
        "never rendered into an agent's context, and reads as stored while "
        "behaving as lost.\n"
        "\n"
        "A DWB session must be open before this write can land. If opening one "
        "is not yours to do (/dwb-open, or POST /api/sessions/open), tell your "
        "team lead rather than working around this. Once a session is open, "
        "send this request again, unchanged.\n"
        "\n"
        "Nothing was written and nothing was lost. This refusal is the "
        "recoverable outcome; a stored row with a NULL origin is not."
    )


def require_session_origin(
    db: Session, *, project_id: int, action: str
) -> DwbSession:
    """The open session a memory write on this project must stamp, or refuse.

    `action` leads the message ("Memory write", "Adopt decision"), so the
    refused caller can tell which of their calls was rejected without reading a
    stack trace.

    Raises MemoryOriginMissing. Deliberately does NOT raise for a missing
    project: a project that is not there cannot have an open session, so the
    same refusal is true, and the caller that cares about the distinction
    (`raw_memory`) checks for the project itself first and says so in its own
    words.
    """
    active = session_svc.get_active_session(db, project_id)
    if active is None:
        raise MemoryOriginMissing(
            _refusal(db.get(Project, project_id), project_id, action)
        )
    return active


def deferrable_session_origin(db: Session, *, project_id: int) -> DwbSession | None:
    """The open session for a background write, or None to defer it.

    None means DO NOT INSERT - not "insert with NULL". The caller skips the
    write entirely and leaves its source untouched so the next pass can make it
    again. See the module docstring on why this path defers where
    `require_session_origin` refuses.

    This is a thin wrapper over `get_active_session` and that is intended: the
    point is that a background writer reaches for a name that says what the
    None means, rather than for a lookup whose None reads as "stamp nothing".
    """
    return session_svc.get_active_session(db, project_id)

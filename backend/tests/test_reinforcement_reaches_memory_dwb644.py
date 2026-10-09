# Path: tests/test_reinforcement_reaches_memory_dwb644.py
# File: test_reinforcement_reaches_memory_dwb644.py
# Created: 2026-10-08 (DWB-644)
# Purpose: The one test that asks whether reinforcement REACHES a memory. A
#          scar whose derived score has decayed below 10 is driven through the
#          real HTTP hook - POST /api/hooks/user-prompt, the endpoint Claude
#          Code calls - and its score is read back at 10. This is DWB-644
#          criterion 5 held as a standing assertion rather than as a live
#          demonstration someone has to remember was done.
# Caller: pytest
# Callees: POST /api/hooks/user-prompt (via the TestClient),
#          app.services.memory_score (sessions_since_reinforced, score),
#          app.models.agent_memory, app.models.dwb_session, app.models.hook_session
# Data In: a project with topoff enabled, an agent, an aged scar, DWB sessions
# Data Out: Assertions on the DERIVED score before and after the hook call
# Last Modified: 2026-10-08 (DWB-644)

"""THE SCORE GOES DOWN AND COMES BACK UP, THROUGH THE REAL ENDPOINT.

WHY THIS FILE EXISTS SEPARATELY FROM THE OTHER DWB-644 TESTS. Seven tickets
built this feature across 2026-09-30 and 10-01, every one of them met its
acceptance criteria with a green suite, and the feature had never executed
once: `fired_count` was 0 on all 877 rows across both human_memory projects
and `last_reinforced_session_id` was NULL on every one. No test in that lane
asked whether reinforcement reaches a memory. They asked whether `_fire`
increments, whether the write site is unique, whether the term is shared -
all true, all green, all about parts.

`test_topoff_match_relation_dwb644.py` has the same shape of blind spot by
design: it is nineteen tests about the MATCH RELATION, exercised through the
service. This one walks the whole path, from an HTTP POST to a number read
back through `memory_score`.

THE ASSERTION THAT MATTERS IS THE SCORE, NOT THE TWO COLUMNS. `fired_count`
and `last_reinforced_session_id` are the mechanism; the score is the thing the
ruling is about ("a scar which is recalled returns to full strength") and it is
DERIVED, from the tier and the number of closed sessions since the clock
origin. A test that asserted only the two columns would pass against a
`sessions_since_reinforced` that had stopped reading
`last_reinforced_session_id` at all - which is precisely the COALESCE bug
DWB-621 was filed for. So the columns are asserted as corroboration and the
score is asserted as the acceptance.

THE SCORE IS ALSO ASSERTED AT 6 FIRST, IN THE FIXTURE, AND THAT IS NOT
CEREMONY. "Came back up to 10" is satisfied by a row that was at 10 the whole
time, and a scar's score is 10 at zero elapsed sessions, which is the state of
every freshly created fixture row. Without the floor assertion this test would
pass against code that does nothing at all.

WHAT THIS TEST DOES NOT PROVE, STATED HERE RATHER THAN LEFT TO BE ASSUMED. The
TestClient shares its session with the test and its writes roll back at
teardown, so a green here is not evidence that the reinforcement COMMITS. That
half was shown live on a throwaway project, in a separate process, re-read on
an independent connection (DWB-644, project 193, scar 1382: 6 -> 10). What this
test owns is the standing fact that the live HTTP path reaches reinforcement
and the score comes back - the fact that had no test at all, and whose absence
is how a feature shipped seven times without running.
"""

from datetime import datetime, timedelta

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.models.project import MemoryMode, Project
from app.services import memory_score

# 91+ elapsed closed sessions puts a scar in the open-ended last bucket of the
# decay curve, where it reads 6. That is the resting floor it never leaves
# without reinforcement.
FLOOR_SESSIONS = 95
SCAR_FLOOR_SCORE = 6
FULL_STRENGTH = 10

CC_SESSION_ID = "dwb644-regression-session"

# The lesson and the situation share NO WORDING, in either direction. Under the
# pre-DWB-644 relation - prompt matched as a literal substring of the body -
# this prompt finds nothing, so a green here cannot be produced by the old code.
BODY = (
    "Reverting a file through the version control system on a tree nobody has "
    "committed today discards every uncommitted change in it, including work "
    "from tickets that are not yours. Copy it aside and restore from the copy."
)
KEYWORDS = ["git checkout", "shared tree"]
SITUATION = "can I git checkout this file to undo my edit on the shared tree"


def _elapse(db, *, project_id, agent_id, n, tag):
    """`n` CLOSED DWB sessions, each with a hook session for this agent.

    Real rows rather than a patched counter: the COALESCE and the INNER JOIN in
    `sessions_since_reinforced` are what decide the number this test asserts,
    and faking the gap would leave exactly those unexercised.
    """
    base = datetime.utcnow() - timedelta(days=400)
    sessions = []
    for i in range(n):
        s = DwbSession(
            project_id=project_id,
            opened_at=base + timedelta(hours=i),
            closed_at=base + timedelta(hours=i, minutes=30),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
        )
        db.add(s)
        db.flush()
        db.add(
            HookSession(
                session_id=f"dwb644-{tag}-{agent_id}-{i}",
                project_id=project_id,
                agent_id=agent_id,
                dwb_session_id=s.id,
                total_tokens=0,
            )
        )
        db.flush()
        sessions.append(s)
    return sessions


def _score_of(db, memory_id):
    """The DERIVED score, re-read. There is no score column and there must
    never be one: this recomputes it from the tier and the session gap exactly
    as every reader does."""
    db.expire_all()
    row = db.get(AgentMemory, memory_id)
    gap = memory_score.sessions_since_reinforced(db, row)
    return memory_score.score(row.tier, gap), gap, row


@pytest.fixture
def decayed_scar(db_session, make_project, make_agent, tmp_path):
    """A scar at its resting floor, on a project where top-off fires, with an
    open DWB session for the reinforcement to land in.

    EVERY PART OF THE START STATE IS ASSERTED HERE, in the fixture, not left
    for the reader to trust. A setup step that fails silently turns the result
    below into a confident measurement of the wrong thing.
    """
    project_json = make_project(repo_path=str(tmp_path))
    project = db_session.get(Project, project_json["id"])
    project.memory_mode = MemoryMode.human_memory
    project.topoff_enabled = True
    project.topoff_interval = 1  # every prompt fires; no filler needed
    db_session.flush()

    agent = make_agent(project_id=project.id)

    origin = _elapse(
        db_session, project_id=project.id, agent_id=agent["id"], n=1, tag="origin"
    )[0]
    _elapse(
        db_session,
        project_id=project.id,
        agent_id=agent["id"],
        n=FLOOR_SESSIONS,
        tag="decay",
    )

    scar = AgentMemory(
        agent_id=agent["id"],
        tier=MemoryTier.scar,
        body=BODY,
        keywords=list(KEYWORDS),
        created_session_id=origin.id,
        last_reinforced_session_id=None,
        fired_count=0,
    )
    db_session.add(scar)
    db_session.flush()

    # The currently-happening session. Open, so it never counts itself as
    # elapsed experience, and so there is somewhere for the clock origin to
    # move to - with none open, `_fire` leaves the origin alone by design and
    # the score would not come back.
    active = DwbSession(
        project_id=project.id,
        opened_at=datetime.utcnow(),
        closed_at=None,
        open_method=DwbOpenMethod.slash,
    )
    db_session.add(active)
    db_session.flush()

    # The hook session the UserPromptSubmit payload will key on. Without a row
    # here top-off reports `no_hook_session` and never reaches the scar.
    db_session.add(
        HookSession(
            session_id=CC_SESSION_ID,
            project_id=project.id,
            agent_id=agent["id"],
            dwb_session_id=active.id,
            prompt_count=0,
            total_tokens=0,
        )
    )
    db_session.flush()

    score, gap, _ = _score_of(db_session, scar.id)
    assert gap >= 91, f"fixture never reached the floor bucket: gap={gap}"
    assert score == SCAR_FLOOR_SCORE, (
        f"the scar must start BELOW full strength or 'came back to 10' proves "
        f"nothing; got {score}"
    )
    assert scar.fired_count == 0
    assert scar.last_reinforced_session_id is None
    assert SITUATION.lower() not in BODY.lower()
    assert BODY.lower() not in SITUATION.lower()

    return {
        "project": project,
        "agent_id": agent["id"],
        "scar_id": scar.id,
        "active_session_id": active.id,
    }


class TestReinforcementReachesTheMemory:
    """DWB-644 CRITERION 5, as a standing assertion."""

    def test_a_decayed_scar_returns_to_full_strength_through_the_hook(
        self, client, db_session, decayed_scar
    ):
        scar_id = decayed_scar["scar_id"]
        before, gap_before, _ = _score_of(db_session, scar_id)
        assert before == SCAR_FLOOR_SCORE

        response = client.post(
            "/api/hooks/user-prompt",
            json={
                "hook_event_name": "UserPromptSubmit",
                "session_id": CC_SESSION_ID,
                "cwd": decayed_scar["project"].repo_path,
                "prompt": SITUATION,
            },
        )

        assert response.status_code == 200, response.text
        topoff = response.json().get("topoff")
        assert topoff is not None and topoff["fired"] is True, response.json()
        check = topoff["scar_check"]
        assert check["searched"] is True, check
        assert check["matched"] == 1, check
        assert check["memory_ids"] == [scar_id], check

        after, gap_after, row = _score_of(db_session, scar_id)

        # THE ACCEPTANCE. The derived score, read back the way every reader
        # computes it.
        assert after == FULL_STRENGTH, (
            f"the scar went into the consultation at {before} and came out at "
            f"{after}; reinforcement did not reach it"
        )
        assert gap_before >= 91 and gap_after == 0

        # Corroboration, and the reason the score above is 10. A scar at zero
        # elapsed sessions scores 10; so does a row promoted to CORE, at every
        # bucket. Asserting the tier is what makes this 10 the right 10.
        assert row.tier == MemoryTier.scar
        assert row.fired_count == 1
        assert row.last_reinforced_session_id == decayed_scar["active_session_id"]

    def test_an_unrelated_prompt_leaves_the_scar_at_its_floor(
        self, client, db_session, decayed_scar
    ):
        """THE PAIRED STATE. Without it the test above is satisfied by a
        top-off that reinforces everything it is handed, which is the other way
        this feature can be wrong - and the way that promotes scars nobody
        recalled into CORE, which never decays and has no demotion path.
        """
        scar_id = decayed_scar["scar_id"]

        response = client.post(
            "/api/hooks/user-prompt",
            json={
                "hook_event_name": "UserPromptSubmit",
                "session_id": CC_SESSION_ID,
                "cwd": decayed_scar["project"].repo_path,
                "prompt": "add a colour token for the sprint badge please",
            },
        )

        assert response.status_code == 200, response.text
        check = response.json()["topoff"]["scar_check"]
        assert check["searched"] is True, check
        assert check["matched"] == 0, check

        after, gap_after, row = _score_of(db_session, scar_id)
        assert after == SCAR_FLOOR_SCORE
        assert gap_after >= 91
        assert row.fired_count == 0
        assert row.last_reinforced_session_id is None

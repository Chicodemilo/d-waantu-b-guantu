# Path:          tests/test_memory_mode_toggle_dwb588.py
# File:          test_memory_mode_toggle_dwb588.py
# Created:       2026-09-29
# Purpose:       DWB-588 - the per-project memory_mode switch is refused unless the PATCH
#                body confirms it, the refusal carries the spec's warning verbatim, and the
#                warning copy itself is pinned against an independent literal so a silent
#                reword goes red
# Caller:        pytest
# Callees:       PATCH /api/projects/:id, POST /api/projects,
#                app.services.project.MEMORY_MODE_SWITCH_WARNING
# Data In:       Factory-created projects via conftest fixtures
# Data Out:      Assertions on HTTP status codes, the refusal body, and persisted memory_mode
# Last Modified: 2026-09-30 (DWB-593: guard moved to the BEGIN edges; DWB-588)

"""DWB-588: the memory_mode toggle and its warning.

TWO KINDS OF TEST LIVE HERE AND THEY ARE NOT INTERCHANGEABLE.

`TestSwitchGuard` names the behavioural defect: a mode change that lands with
nobody having been warned. Delete the guard and those cases go red.

`TestWarningCopy` names a different defect entirely: the copy drifting. This is
the part that needs saying out loud, because the obvious version of this test is
worthless. Asserting that the API response equals MEMORY_MODE_SWITCH_WARNING
only proves the plumbing carries whatever the constant holds - it passes just as
happily against an empty string. So the constant is ALSO pinned against
EXPECTED_WARNING below, an independent second copy typed out in this file. That
duplication is the point: changing the copy now costs a deliberate edit in two
places, which is exactly the pause that a silent reword skips.

EXPECTED_WARNING is a copy of docs/human_memory_spec.md section 6 with ALL
markup removed: the leading warning icon, the bold, the italics and the
backticks. One rule rather than a per-mark judgement call, which is what stops
this test arguing about punctuation instead of words: the constant carries the
words, the UI carries the presentation. The test does NOT read the spec at
runtime: parsing the doc would invert the source of truth and turn any doc edit
into a red suite.
"""

from datetime import datetime, timezone

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.project import MemoryMode
from app.services.project import MEMORY_MODE_SWITCH_WARNING

EXPECTED_WARNING = """Switching memory modes rewrites every memory this project has.

human_memory stores memory in a completely different structure, under different rules, with a different lifecycle. Switching is not a migration you can run and walk away from: every existing memory has to be re-read and re-tiered, and that is a judgment call an agent makes one entry at a time. It costs real time and real tokens, and switching back costs them again and loses the tiering.

Decide this at the start of a project.

We'll let you do it... but think it thru this time, sport."""


def _mode(client, project_id: int) -> str:
    return client.get(f"/api/projects/{project_id}").json()["memory_mode"]


class TestWarningCopy:
    """The copy guard. These go red on a reword, which is the whole job."""

    def test_constant_matches_the_pinned_literal(self):
        assert MEMORY_MODE_SWITCH_WARNING == EXPECTED_WARNING

    def test_opens_with_the_rewrite_sentence(self):
        assert MEMORY_MODE_SWITCH_WARNING.startswith(
            "Switching memory modes rewrites every memory this project has."
        )

    def test_keeps_the_sport_line_exactly(self):
        # Miles's voice, and the part people actually read. Pinned on its own so
        # a trim of the last line cannot hide inside a larger diff.
        assert MEMORY_MODE_SWITCH_WARNING.endswith(
            "We'll let you do it... but think it thru this time, sport."
        )

    def test_says_to_decide_at_the_start_of_a_project(self):
        assert (
            "Decide this at the start of a project."
            in MEMORY_MODE_SWITCH_WARNING
        )

    def test_carries_no_icon_and_no_em_dash(self):
        # The spec renders this with a leading warning icon. It is UI copy, so
        # the icon is dropped. isascii() catches the icon and an em dash in one
        # assertion; both are standing house-style violations.
        assert MEMORY_MODE_SWITCH_WARNING.isascii()
        assert "\u2014" not in MEMORY_MODE_SWITCH_WARNING  # em dash

    def test_carries_no_markdown_at_all(self):
        # One rule: the constant carries the words, the UI carries the
        # presentation. Bold, italics and backticks all go, so nobody has to
        # remember which marks were the exception. Underscore is NOT checked:
        # human_memory carries one and it is part of the identifier, not markup.
        assert "*" not in MEMORY_MODE_SWITCH_WARNING
        assert "`" not in MEMORY_MODE_SWITCH_WARNING


class TestSwitchGuard:
    """AC1 and AC2: unconfirmed is refused with the warning, confirmed flips."""

    def test_unconfirmed_switch_is_refused(self, client, make_project):
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}",
            json={"memory_mode": "adopting"},
        )
        assert r.status_code == 400

    def test_refusal_body_is_the_warning(self, client, make_project):
        """DWB-593 moved the edge this guard sits on, not the guard.

        The act that commits to re-reading and re-tiering every entry is now
        `stock -> adopting`, so the confirmation requirement moved there with
        it. The warning text is unchanged and is still asserted verbatim
        against the constant.
        """
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}",
            json={"memory_mode": "adopting"},
        )
        assert r.json()["detail"] == MEMORY_MODE_SWITCH_WARNING

    def test_refused_switch_does_not_persist(self, client, make_project):
        project = make_project()
        client.patch(
            f"/api/projects/{project['id']}",
            json={"memory_mode": "adopting"},
        )
        assert _mode(client, project["id"]) == MemoryMode.stock.value

    def test_confirmed_switch_is_allowed_through(
        self, client, db_session, make_project
    ):
        """Confirmation lets the transition BEGIN. What it lands in is not
        asserted here on purpose.

        DWB-593 enumerates inside this request, so a project with no memory to
        move completes immediately and lands in `human_memory`, while one with
        entries rests in `adopting`. Both are correct, and pinning either here
        would make DWB-588's confirmation test fail whenever DWB-594's
        enumerator changed. This test owns the guard; the landing state is
        covered by tests/test_memory_transitions_dwb593.py.
        """
        project = make_project()
        # An adoption also requires an open DWB session: without one every
        # memory it writes gets a NULL clock origin and is unreachable. That
        # guard lives in the same refusal function as confirmation, so this
        # test has to satisfy it to reach the thing it is actually asserting.
        db_session.add(
            DwbSession(
                project_id=project["id"],
                open_method=DwbOpenMethod.slash,
                opened_at=datetime.now(timezone.utc),
            )
        )
        db_session.flush()
        r = client.patch(
            f"/api/projects/{project['id']}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        assert r.status_code == 200, r.text
        # One of the TWO legal outcomes, not merely "not stock". Still
        # decoupled from whether DWB-594's enumerator found candidates, which
        # is the coupling this test is avoiding, but no longer satisfiable by
        # an arbitrary state: "not stock" would have passed if a bug landed the
        # project in `reverting`.
        assert r.json()["memory_mode"] in (
            MemoryMode.adopting.value,
            MemoryMode.human_memory.value,
        )

    def test_switching_back_warns_too(self, client, db_session, make_project):
        # Per the spec, switching back costs the tokens again and loses the
        # tiering, so it is a switch in both directions. DWB-593: the reverse
        # BEGIN edge is `human_memory -> reverting`.
        #
        # The project is put into human_memory directly rather than walked
        # there through the machine, so this test depends only on the guard it
        # is about. Walking would drag DWB-594's enumerator into a DWB-588
        # test.
        from app.models.project import Project

        project = make_project()
        db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
        db_session.flush()

        r = client.patch(
            f"/api/projects/{project['id']}", json={"memory_mode": "reverting"}
        )
        assert r.status_code == 400
        assert r.json()["detail"] == MEMORY_MODE_SWITCH_WARNING
        assert _mode(client, project["id"]) == MemoryMode.human_memory.value

    def test_switching_back_confirmed_works(self, client, db_session, make_project):
        from app.models.project import Project

        project = make_project()
        db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
        db_session.flush()

        r = client.patch(
            f"/api/projects/{project['id']}",
            json={"memory_mode": "reverting", "memory_mode_confirmed": True},
        )
        assert r.status_code == 200, r.text
        # Same reasoning in the reverse direction: the two legal landings from
        # human_memory are `reverting` and, when there is nothing to move back,
        # `stock`.
        assert _mode(client, project["id"]) in (
            MemoryMode.reverting.value,
            MemoryMode.stock.value,
        )


class TestGuardDoesNotOverreach:
    """Adjacent risks: a guard that warns when nothing is changing trains people
    to click through it. These pass under the pre-DWB-588 code too, and are NOT
    evidence that the guard above exists."""

    def test_unrelated_patch_is_untouched(self, client, make_project):
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}", json={"description": "still stock"}
        )
        assert r.status_code == 200
        assert r.json()["description"] == "still stock"

    def test_setting_the_mode_it_already_has_is_not_a_switch(
        self, client, make_project
    ):
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}", json={"memory_mode": "stock"}
        )
        assert r.status_code == 200
        assert _mode(client, project["id"]) == MemoryMode.stock.value

    def test_confirming_without_naming_a_mode_changes_nothing(
        self, client, make_project
    ):
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}", json={"memory_mode_confirmed": True}
        )
        assert r.status_code == 200
        assert _mode(client, project["id"]) == MemoryMode.stock.value

    def test_confirmation_flag_is_not_persisted_as_a_field(
        self, client, make_project
    ):
        # It is a request flag, not a column. update_project setattrs every key
        # it is handed, so a missed pop would hang it off the ORM instance.
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}",
            json={"memory_mode": "human_memory", "memory_mode_confirmed": True},
        )
        assert "memory_mode_confirmed" not in r.json()


class TestModeAtCreation:
    """The warning's own advice is to decide this at the start of a project. A
    project being created has no memories to rewrite, so creation carries no
    confirmation flag and no warning."""

    def test_defaults_to_stock(self, client, make_project):
        project = make_project()
        assert project["memory_mode"] == MemoryMode.stock.value
        assert project["memory_schema_version"] == 1

    def test_can_be_created_in_human_memory_mode(self, client, tmp_path):
        r = client.post(
            "/api/projects",
            json={
                "prefix": "HM588",
                "name": "Born in human_memory",
                "repo_path": str(tmp_path),
                "memory_mode": "human_memory",
            },
        )
        assert r.status_code == 201
        assert r.json()["memory_mode"] == MemoryMode.human_memory.value

    def test_schema_version_is_not_settable_by_a_caller(
        self, client, make_project
    ):
        project = make_project()
        r = client.patch(
            f"/api/projects/{project['id']}", json={"memory_schema_version": 99}
        )
        assert r.status_code == 200
        assert r.json()["memory_schema_version"] == 1

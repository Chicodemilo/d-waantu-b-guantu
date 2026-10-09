# Path: tests/test_memory_fill_dwb664.py
# File: test_memory_fill_dwb664.py
# Created: 2026-10-08 (DWB-664)
# Purpose: Guard the fill route's five constraints - owner only, fill not edit,
#          nothing else mutable, history provably untouched, and validation
#          shared with the write gate rather than reimplemented.
# Caller: pytest
# Callees: app.services.memory_fill, POST /api/agents/{id}/memories/{mid}/fill
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on the persisted row, before and after
# Last Modified: 2026-10-09 (DWB-667: the assignment guard is now per FUNCTION,
#                so `rekey_memory` is proved never to assign `condensed`)

"""DWB-664: the constraints ARE the deliverable.

The route is four lines of assignment. What makes it safe is what it refuses,
and the reason this file is longer than the thing it tests is that eight agents
are about to run it across ~820 rows. A missing constraint here is 820 rows of
damage rather than one.

THE HISTORY ASSERTION IS A WHOLE-ROW DIFF, NOT A FIELD LIST. `test_only_
condensed_keywords_and_updated_at_change` captures every column before and
after and compares the sets. A test that checked `created_at` and `fired_count`
by name would pass against a route that quietly cleared `source_journal_id`, or
any column added to this table next month. The whole point of the route is that
withdraw-and-repost destroyed history, so the guard has to cover history that
does not exist yet.

`updated_at` IS EXPECTED TO MOVE. The model carries `onupdate=func.now()`, so
any UPDATE touches it. It is named in the allowed set rather than suppressed:
freezing it would make the row lie about when it last changed, and a test that
simply ignored it would also ignore a route that started writing it by hand.

THE STRUCTURAL GUARD IS THE ONE THAT SURVIVES A REWRITE. `test_the_service_
assigns_exactly_two_attributes` walks the AST of memory_fill and asserts that
the only attribute assignments on a memory object are `condensed` and
`keywords`. Behavioural tests prove the route does not change `tier` TODAY; the
AST guard is what fails the day somebody adds a third assignment, including one
reachable only from a branch no test covers.
"""

import ast
import pathlib

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project
from tests.conftest import MEMORY_WRITE_EXTRAS

SERVICE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "memory_fill.py"
)


def _row_snapshot(db_session, memory_id) -> dict:
    """Every column of the row, by name. Read fresh, not from the identity map."""
    db_session.expire_all()
    row = db_session.get(AgentMemory, memory_id)
    assert row is not None, f"memory {memory_id} is gone"
    return {c.name: getattr(row, c.name) for c in AgentMemory.__table__.columns}


def _unfilled_memory(client, db_session, make_project, make_agent):
    """An agent on a human_memory project holding one row with neither field.

    Written directly rather than through the API because the write gate
    (DWB-657) now REQUIRES both fields - so the population this route exists
    for cannot be created through the API at all. That is the point: these rows
    predate the columns.
    """
    project = make_project()
    db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
    db_session.flush()
    agent = make_agent(project_id=project["id"])
    row = AgentMemory(
        agent_id=agent["id"],
        tier=MemoryTier.scar,
        body="a lesson written before the columns existed",
        fired_count=3,
    )
    db_session.add(row)
    db_session.flush()
    assert row.condensed is None and row.keywords is None
    return agent["id"], row.id


class TestTheFillItself:
    """AC1 and AC2."""

    def test_an_owner_fills_its_own_row_and_a_fresh_read_shows_it(
        self, client, db_session, make_project, make_agent
    ):
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/fill",
            json={
                "condensed": "grade the account, not the headline",
                "keywords": ["retraction", "accounting"],
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 200, r.text
        assert r.json()["filled"] == ["condensed", "keywords"]

        after = _row_snapshot(db_session, memory_id)
        assert after["condensed"] == "grade the account, not the headline"
        assert after["keywords"] == ["retraction", "accounting"]
        assert isinstance(after["keywords"], list)

    def test_only_condensed_keywords_and_updated_at_change(
        self, client, db_session, make_project, make_agent
    ):
        """AC2, as a whole-row diff rather than a list of field names.

        Named fields would pass against a route that cleared a column this test
        did not think to name, including one added to the table later. The set
        difference cannot.
        """
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        before = _row_snapshot(db_session, memory_id)

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/fill",
            json={"condensed": "one line", "keywords": ["a", "b"]},
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 200, r.text

        after = _row_snapshot(db_session, memory_id)
        changed = {k for k in before if before[k] != after[k]}
        assert changed <= {"condensed", "keywords", "updated_at"}, (
            f"the fill changed columns it must not: {changed - {'condensed', 'keywords', 'updated_at'}}"
        )
        # Asserted positively too: a route that changed NOTHING would also
        # satisfy the subset check above.
        assert {"condensed", "keywords"} <= changed
        # The fields withdraw-and-repost would have destroyed, named
        # individually because they are the reason this route exists.
        for field in (
            "id",
            "created_at",
            "fired_count",
            "last_reinforced_session_id",
            "source_journal_id",
            "created_session_id",
        ):
            assert before[field] == after[field], f"{field} moved"
        assert before["fired_count"] == 3, "the fixture lost its history before the test"

    def test_filling_is_per_field(
        self, client, db_session, make_project, make_agent
    ):
        """One field at a time, because a half-filled row must not be stranded.

        A both-or-nothing rule would make a row with `condensed` and no
        `keywords` permanently unfillable, and the only way out would be the
        withdraw-and-repost this whole ticket exists to avoid.
        """
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        headers = {"X-Agent-ID": str(agent_id)}
        url = f"/api/agents/{agent_id}/memories/{memory_id}/fill"

        first = client.post(url, json={"keywords": ["only", "keywords"]}, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["filled"] == ["keywords"]
        assert first.json()["condensed"] is None

        second = client.post(url, json={"condensed": "now the line"}, headers=headers)
        assert second.status_code == 200, second.text
        assert second.json()["filled"] == ["condensed"]

        after = _row_snapshot(db_session, memory_id)
        assert after["condensed"] == "now the line"
        assert after["keywords"] == ["only", "keywords"]


class TestTheRefusals:
    """AC3, AC4, and the blank cases. Each asserts the REASON, not just a code -
    a refusal for the wrong reason reads identically to the caller."""

    def test_another_agent_is_refused_and_nothing_is_written(
        self, client, db_session, make_project, make_agent
    ):
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        stranger = make_agent()["id"]

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/fill",
            json={"condensed": "not mine to write", "keywords": ["a"]},
            headers={"X-Agent-ID": str(stranger)},
        )
        assert r.status_code == 403, r.text
        assert "Only the owning agent may" in r.json()["detail"]

        after = _row_snapshot(db_session, memory_id)
        assert after["condensed"] is None and after["keywords"] is None

    def test_a_field_that_is_already_set_is_refused(
        self, client, db_session, make_project, make_agent
    ):
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        headers = {"X-Agent-ID": str(agent_id)}
        url = f"/api/agents/{agent_id}/memories/{memory_id}/fill"
        assert client.post(
            url, json={"condensed": "the first one", "keywords": ["a"]}, headers=headers
        ).status_code == 200

        again = client.post(url, json={"condensed": "second thoughts"}, headers=headers)
        assert again.status_code == 409, again.text
        assert "fills rather than edits" in again.json()["detail"]

        after = _row_snapshot(db_session, memory_id)
        assert after["condensed"] == "the first one", "the refusal overwrote anyway"

    def test_every_other_column_is_rejected_by_the_schema(
        self, client, db_session, make_project, make_agent
    ):
        """AC5. `extra="forbid"` makes this structural rather than remembered.

        `tier` is the one that matters most: memory_decide refuses to let an
        agent grant itself CORE because only a human does that, and a route
        that silently ignored a `tier` key would look identical to one that
        honoured it from the caller's side.
        """
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        for key, value in (
            ("tier", "core"),
            ("body", "rewritten"),
            ("fired_count", 99),
            ("agent_id", 1),
            ("created_at", "2020-01-01T00:00:00"),
            ("source_journal_id", 1),
        ):
            r = client.post(
                f"/api/agents/{agent_id}/memories/{memory_id}/fill",
                json={"condensed": "x", "keywords": ["y"], key: value},
                headers={"X-Agent-ID": str(agent_id)},
            )
            assert r.status_code == 422, f"{key}: expected 422, got {r.status_code}"
            locs = {".".join(str(p) for p in d["loc"]) for d in r.json()["detail"]}
            assert f"body.{key}" in locs, f"{key}: 422 for the wrong field: {locs}"

        after = _row_snapshot(db_session, memory_id)
        assert after["condensed"] is None, "a rejected request wrote anyway"

    def test_blank_values_are_refused_with_the_write_gates_own_words(
        self, client, db_session, make_project, make_agent
    ):
        """Constraint 5. The same rule broken gives the same sentence.

        Asserted on the TEXT rather than only the status, because the value of
        sharing the validators is that a caller cannot be told two different
        things about one rule.
        """
        agent_id, memory_id = _unfilled_memory(
            client, db_session, make_project, make_agent
        )
        url = f"/api/agents/{agent_id}/memories/{memory_id}/fill"
        headers = {"X-Agent-ID": str(agent_id)}

        blank = client.post(url, json={"condensed": "   "}, headers=headers)
        assert blank.status_code == 400
        assert "ONE LINE CARRYING THE LESSON" in blank.json()["detail"]

        empty = client.post(url, json={"keywords": []}, headers=headers)
        assert empty.status_code == 400
        assert "at least one non-blank term" in empty.json()["detail"]

        mixed = client.post(url, json={"keywords": ["real", "  "]}, headers=headers)
        assert mixed.status_code == 400
        assert "index [1]" in mixed.json()["detail"], mixed.json()["detail"]

        nothing = client.post(url, json={}, headers=headers)
        assert nothing.status_code == 400
        assert "naming neither" in nothing.json()["detail"]

        after = _row_snapshot(db_session, memory_id)
        assert after["condensed"] is None and after["keywords"] is None


class TestTheServiceCannotTouchAnythingElse:
    """The structural half. Behaviour proves what the route does today; this
    fails the day a third assignment appears, including on a branch no test
    reaches."""

    def test_the_service_assigns_exactly_two_attributes(self):
        """Every attribute assignment in the module, GROUPED BY THE FUNCTION IT
        IS IN AND BY WHAT IT IS ASSIGNED ON, and the whole mapping asserted.

        The first version of this collected bare attribute NAMES and failed on
        `self.code` / `self.detail` in the exception's __init__ - a true
        finding about the wrong objects. The fix is not to filter `self` out:
        a filter keyed on what I expect would silently drop an assignment on
        some third object I did not picture. Grouping makes an unanticipated
        target arrive as a NEW KEY in the mapping instead of as an absence.

        DWB-667 ADDED THE FUNCTION DIMENSION, AND IT IS A TIGHTENING. A
        module-wide grouping was exactly right while the module held one
        operation. `rekey_memory` arrived and assigns `keywords` and
        `situation`; under the old grouping the union became
        {condensed, keywords, situation} and the guard could no longer tell
        whether `condensed` was assigned by the fill path or by the rekey path.
        That is the distinction the whole lane rests on - rekey REPLACES an
        index and must never revise a lesson - so the guard now proves it
        per function rather than losing it in a union. A module-level
        assignment would arrive as the key '<module>' and fail here too.
        """
        tree = ast.parse(SERVICE_PATH.read_text())

        def _owner(node):
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    if child is node:
                        return parent
            return None

        by_scope: dict[str, dict[str, set]] = {}
        scope_of: dict[int, str] = {}
        for func in ast.walk(tree):
            if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(func):
                    scope_of.setdefault(id(node), func.name)

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute):
                    scope = scope_of.get(id(node), "<module>")
                    by_scope.setdefault(scope, {}).setdefault(
                        ast.unparse(target.value), set()
                    ).add(target.attr)

        assert by_scope == {
            # The exception carrying its own code and detail. Not a row.
            "__init__": {"self": {"code", "detail"}},
            # The ONLY row attributes the FILL path may ever set. `situation`
            # is absent here deliberately: fill completes the two DWB-654
            # columns and nothing else.
            "fill_memory": {"memory": {"condensed", "keywords"}},
            # The ONLY row attributes the REKEY path may ever set, and
            # `condensed` is absent here deliberately and is the point of the
            # separation. Rekey repairs an index; it may not revise a lesson.
            "rekey_memory": {"memory": {"keywords", "situation"}},
        }, (
            f"memory_fill's attribute assignments are {by_scope}. Each function "
            "may set only the row attributes listed for it and nothing else - "
            "not tier, not body, not the moment-tags, not either session id - "
            "and in particular `rekey_memory` may never assign `condensed`. A "
            "new target object, a new attribute, or an assignment in a new "
            "function needs its own ticket and its own argument."
        )

    def test_the_validators_are_imported_not_redefined(self):
        """Constraint 5, structurally. Two implementations of one rule drift,
        and the drift is invisible because both keep returning a valid answer."""
        tree = ast.parse(SERVICE_PATH.read_text())
        defined = {
            n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
        }
        assert "_require_condensed" not in defined, (
            "memory_fill defines its own _require_condensed. It must import the "
            "write gate's, or the two will disagree about what counts as blank "
            "and nobody will see it until the data does."
        )
        assert "_require_keywords" not in defined

        imported = {
            alias.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module == "app.services.raw_memory"
            for alias in n.names
        }
        assert {"_require_condensed", "_require_keywords"} <= imported, imported


class TestTheWriteGateStillRefusesTheseRows:
    """Context, pinned: the population this route serves cannot be created
    through the write API at all, which is why a fill route was needed rather
    than a re-post."""

    def test_the_create_route_still_requires_both_fields(
        self, client, db_session, make_project, make_agent
    ):
        project = make_project()
        db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
        db_session.flush()
        agent = make_agent(project_id=project["id"])
        assert client.post(
            "/api/sessions/open",
            json={"project_id": project["id"], "open_method": "slash"},
        ).status_code == 201

        bare = client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": "no condensed"}
        )
        assert bare.status_code == 400

        full = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "with both"},
        )
        assert full.status_code == 201, full.text

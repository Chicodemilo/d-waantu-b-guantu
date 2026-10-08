# Path: backend/tests/test_request_schema_extra_forbid_dwb651.py
# File: test_request_schema_extra_forbid_dwb651.py
# Created: 2026-10-08
# Purpose: Guard DWB-651 - every request body model bound to a write route must
#          refuse undeclared keys, or be a NAMED member of the permissive
#          allowlist below with a reason. A write that returns 200 and changes
#          nothing is the defect this exists to prevent.
# Caller: pytest
# Callees: app.main (route table), pydantic
# Data In: the live FastAPI route table
# Data Out: assertions
# Last Modified: 2026-10-08 (DWB-651: created)

"""DWB-651: request schemas refuse undeclared keys.

WHY THIS IS DISCOVERY-BASED AND NOT A HAND-WRITTEN LIST OF SCHEMAS.
A list of schemas to check can be escaped by writing a new schema and not adding
it, which is exactly how 52 of 53 ended up permissive after the ruling had
already been made once (DWB-509 applied `extra="forbid"` to
`TicketTokenIncrement` and nothing swept the rest). So the set under test is
derived from the live route table at run time: a new write route is in scope the
moment it is registered, with nothing to remember.

THE ALLOWLIST IS NAMED MEMBERS WITH REASONS, NOT A PATTERN.
A pattern (`everything under /hooks/`) would silently absorb a future hook
endpoint that we DO control. Naming each one means adding a permissive schema is
a deliberate edit to this file with a reason attached, which is the point: a
schema left open with no reason is indistinguishable from one nobody looked at.
"""

import inspect
import typing

import pytest
from pydantic import BaseModel

from app.main import app

WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# Permissive BY DECISION (DWB-651). Each entry: why it cannot forbid, naming the
# caller whose payload makes it necessary. Full rationale sits next to each model.
PERMISSIVE_WITH_REASON = {
    "HookEventInput":
        "Claude Code harness payload: .claude/settings.json pipes raw hook stdin "
        "through `-d \"$(cat)\"`. The field list is the harness's, not ours, and "
        "grows between releases. A 422 drops the whole event (curl -sf, output "
        "discarded) and silently loses token attribution for that session.",
    "ToolUseInput":
        "Same harness ingress, PostToolUse payload. Same always-200 "
        "delivery-gap-tolerance contract.",
    "LifecycleEventInput":
        "Same harness ingress, Notification / PreCompact payload.",
    "AgentMessageInput":
        "SendMessage hook. A filter in .claude/settings.json narrows it today, but "
        "that file is owned by each cloning repo and may widen, and this endpoint "
        "shares the always-200 contract.",
}


def _bound_request_models():
    """Every pydantic model bound as a request body on a write route."""
    found = {}
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        if not (methods & WRITE_METHODS):
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        try:
            hints = typing.get_type_hints(endpoint)
        except Exception:
            hints = getattr(endpoint, "__annotations__", {})
        for name, ann in hints.items():
            if name == "return":
                continue
            if inspect.isclass(ann) and issubclass(ann, BaseModel):
                found.setdefault(ann.__name__, ann)
    return found


BOUND = _bound_request_models()


def test_discovery_found_the_request_surface():
    """A guard whose discovery returns nothing passes every check it guards.

    This asserts the instrument had an input before any conclusion rests on it.
    The floor is deliberately well below the current count so ordinary growth
    does not trip it; it only catches discovery breaking outright.
    """
    assert len(BOUND) >= 50, (
        f"only {len(BOUND)} request models discovered - the route walk is broken, "
        "so every assertion below is vacuously true"
    )


@pytest.mark.parametrize("name", sorted(BOUND))
def test_bound_request_model_refuses_undeclared_keys(name):
    """Parametrized over the DISCOVERED set, so a new write route is covered
    the moment it is registered rather than when someone remembers this file."""
    model = BOUND[name]
    if name in PERMISSIVE_WITH_REASON:
        assert PERMISSIVE_WITH_REASON[name].strip(), (
            f"{name} is allowlisted with an empty reason"
        )
        assert model.model_config.get("extra") != "forbid", (
            f"{name} now forbids extras but is still on the permissive allowlist - "
            "remove it from PERMISSIVE_WITH_REASON"
        )
        return
    assert model.model_config.get("extra") == "forbid", (
        f"{name} accepts undeclared keys: a caller that mistypes a field gets a "
        "200 and a write that did nothing. Add "
        'model_config = ConfigDict(extra="forbid"), or add it to '
        "PERMISSIVE_WITH_REASON with the caller that makes it necessary."
    )


def test_allowlist_has_no_stale_entries():
    """A guard must reject a STALE entry as well as a missing one: an allowlist
    naming a model that no longer exists reads as covered and checks nothing."""
    stale = sorted(set(PERMISSIVE_WITH_REASON) - set(BOUND))
    assert not stale, (
        f"allowlist names models that are no longer bound to a write route: {stale}"
    )


def test_the_original_defect_is_refused():
    """The literal payload from the DWB-651 report: PATCH /api/tickets/{id} with
    `description_append` returned 200 and changed nothing.

    Asserted on the MODEL rather than through the client so it names the cause.
    The paired positive case is what makes this a guard and not a tautology: a
    model that refused EVERYTHING would also pass the first half.
    """
    from pydantic import ValidationError

    from app.schemas.ticket import TicketUpdate

    with pytest.raises(ValidationError) as exc:
        TicketUpdate(description_append="silently discarded before DWB-651")
    assert any(e["type"] == "extra_forbidden" for e in exc.value.errors())

    # and the real field still lands
    assert TicketUpdate(description="x").description == "x"

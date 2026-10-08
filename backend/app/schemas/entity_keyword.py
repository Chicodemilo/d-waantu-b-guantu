# Path: app/schemas/entity_keyword.py
# File: entity_keyword.py
# Created: 2026-06-25
# Purpose: Pydantic schemas for the generic weighted keyword table (DWB-481).
#          Create/Read shapes for EntityKeyword rows mined by the deterministic
#          extractor (DWB-482) and consumed by the session synthesizer (DWB-483).
# Caller: app/services/* (keyword extraction/synthesis), future routers
# Callees: pydantic
# Data In: JSON request body / ORM rows
# Data Out: EntityKeywordBase, EntityKeywordCreate, EntityKeywordRead
# Last Modified: 2026-10-08 (DWB-651: recorded why this stays permissive -
#                it is bound to no route and the module is dead)

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityKeywordBase(BaseModel):
    """Shared fields for a weighted keyword row.

    entity_type + entity_id are a polymorphic pointer (no hard FK); weight is
    the per-entity occurrence count; source labels the mining origin.
    """

    entity_type: str
    entity_id: int
    keyword: str
    weight: int = 1
    source: str


class EntityKeywordCreate(EntityKeywordBase):
    """Body to persist one weighted keyword.

    DWB-651: PERMISSIVE, and deliberately so rather than overlooked. CALLER:
    NONE. This class is bound to no route and imported by nothing - the whole
    module is, including EntityKeywordBase and EntityKeywordRead. Checked by
    grepping the entire repo (app, tests, scripts, frontend, alembic) for all
    three names: the only hits are this file's own header and these
    definitions. The header's "Caller: app/services/* (keyword extraction/
    synthesis), future routers" describes an intention from DWB-481, not a
    caller that exists.

    So there is no payload that can reach it and nothing for extra="forbid" to
    protect. It is left untouched rather than deleted because the sibling pair
    DwbSessionCreate/DwbSessionUpdate were deleted under this ticket on the same
    evidence, while removing THIS one would leave a half-gutted module whose
    remaining two classes are equally dead. That is a whole-module dead-code
    call belonging to the DWB-481/482/483 lane, not to a schema-hardening
    ticket. Reported rather than actioned.

    If anything ever binds this to a route, forbid it then; the DWB-651 guard in
    tests/ is discovery-based and will fail the moment it becomes reachable.
    """


class EntityKeywordRead(EntityKeywordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime

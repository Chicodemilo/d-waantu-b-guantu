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
# Last Modified: 2026-06-25

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
    """Body to persist one weighted keyword."""


class EntityKeywordRead(EntityKeywordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime

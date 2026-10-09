# Path: app/schemas/agent_memory.py
# File: agent_memory.py
# Created: 2026-09-29 (DWB-586)
# Purpose: Pydantic schemas for the raw memory write - POST /api/agents/{id}/memories
# Caller: app/routers/agents.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: RawMemoryCreate, RawMemoryResponse
# Last Modified: 2026-10-09 (DWB-667: `situation` on the write request and
#                response; MemoryRekeyRequest/Response for the keywords-only
#                replace)
#                (DWB-649: response tier is derived at insert and is
#                never `raw`; the request field is still refused)
#                (DWB-651: both request models refuse undeclared keys)
#                (DWB-657: condensed + keywords accepted here, enforced in the
#                service so the refusal can teach rather than 422)

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RawMemoryCreate(BaseModel):
    """POST /api/agents/{agent_id}/memories body (DWB-586).

    body: the memory, as written in the moment. Required, non-empty.
    context_key: what this is bound TO, when the writer already knows. Consolidation
                 is what decides whether a row is context-bound; naming the context
                 at write time is recording a fact, not making that judgment.
    cost / caught_by / surprised: section 4's moment-tags - what the moment knows
                 and cannot later be reconstructed. All optional; section 4's rule
                 is to tag only what the moment knows, so an untagged memory is the
                 normal case. `caught_by` earns its place through one query:
                 everything the human had to catch is a map of where the agent's
                 own checks do not look.
    tier: accepted ONLY so that a request naming one can be refused with a reason.
          Spec section 4 rules out the CALLER tiering at write time and section 7
          hard rule 5 rules out CORE outright. Dropping the field from the schema
          would make a tiering attempt silently succeed, which is worse than a 400:
          the caller would believe its tier had been honoured when the server had
          derived its own. DWB-649 note: the response `tier` is a real tier, set
          at insert from the moment-tags below, never `raw`. The field being
          refused on the way IN and populated on the way OUT is the point - the
          tier is the server's answer, not the caller's assertion.
    condensed / keywords: author-supplied at write time and MANDATORY in effect,
          enforced by `raw_memory.append_raw_memory` (DWB-657). See the note
          below on why they are declared Optional here.
    """
    model_config = ConfigDict(extra="forbid")  # DWB-651

    body: str
    context_key: str | None = None
    cost: Literal["none", "low", "high"] | None = None
    caught_by: Literal["me", "worker", "human", "ci"] | None = None
    # Tri-state: True, False, and "nobody said". None is not False - section 1
    # makes prediction error the driver of encoding strength, so the difference
    # between "was not surprised" and "was never asked" is a real one.
    surprised: bool | None = None
    tier: str | None = None

    # DWB-657: condensed and keywords are REQUIRED IN EFFECT and declared
    # OPTIONAL HERE ON PURPOSE. Read this before "fixing" them to required.
    #
    # A schema-level required field produces pydantic's generic 422 - "Field
    # required", the field name, nothing about what the field is FOR. These two
    # are the one part of a memory an extractor cannot produce, so an author who
    # omits them needs to be told what to write, not merely that something is
    # missing. Only the service layer can carry that sentence, so the refusal
    # lives in `raw_memory.append_raw_memory` and returns 400 with it.
    #
    # Exactly the same reasoning as `tier` two lines up, in the opposite
    # direction: `tier` is declared so a caller naming one can be ANSWERED
    # instead of silently dropped; these are declared optional so a caller
    # omitting one can be TAUGHT instead of generically rejected. Both exist to
    # make the schema layer hand the question to the layer that can explain it.
    #
    # Note the asymmetry with undeclared keys: because this model forbids extras
    # (DWB-651), a MISSPELLED key - `condense`, `keyword`, `key_words` - is a 422
    # `extra_forbidden` from pydantic and never reaches the 400 below. A typo and
    # an omission therefore return different codes, which is correct: one is a
    # malformed request, the other is a complete request that did not do the work.
    condensed: str | None = None
    keywords: list[str] | None = None

    # DWB-667: ONE LINE naming the moment this lesson applies to, and REQUIRED
    # IN EFFECT, declared Optional here for exactly the reason the two above
    # are. The service matches `keywords` against it with `memory_consult`'s own
    # predicate and refuses the write when the author's own sentence would not
    # have recalled the author's own keywords. That refusal has to carry a
    # worked contrast between a reachable keyword and a filing label, which
    # pydantic's "Field required" cannot.
    situation: str | None = None


class RawMemoryResponse(BaseModel):
    """The written row, plus what the session lookup found.

    `session_state` used to exist because `created_session_id: null` on its own
    is ambiguous - it cannot distinguish "no session was open" from "we never
    looked" - and it carried two values, `open` and `none_open`.

    DWB-637 REMOVED THE AMBIGUOUS CASE RATHER THAN DISAMBIGUATING IT. A row with
    a null `created_session_id` has no clock origin, so it cannot be scored, so
    it is excluded from every candidate list and never reaches an agent: it read
    as stored and behaved as lost. That write is now refused with 400, and
    `none_open` is gone rather than documented as unreachable, because a name for
    a bad state sitting in the success path reads as a supported mode.

    So `session_state` has exactly one value, `open`, and `created_session_id` is
    never null on a response from this endpoint. The field is kept rather than
    dropped: it is a positive confirmation that the row has an origin, which is
    the fact this endpoint exists to guarantee, and a consumer reading `open` is
    reading a checked claim rather than a default.
    """

    id: int
    agent_id: int
    tier: str
    body: str
    context_key: str | None
    cost: str | None
    caught_by: str | None
    surprised: bool | None
    # DWB-657: echoed back for the same reason every other column is - a write
    # response that omitted two columns it had just stored would be a quiet
    # version of the defect this endpoint's gate exists to prevent.
    condensed: str | None
    keywords: list[str] | None
    # DWB-667: echoed back so the caller can see WHICH sentence its keywords
    # were cleared against, rather than only that a gate existed.
    situation: str | None
    created_session_id: int | None
    session_state: str
    fired_count: int
    created_at: datetime


class MemoryFillRequest(BaseModel):
    """POST /api/agents/{agent_id}/memories/{memory_id}/fill body (DWB-664).

    BOTH FIELDS OPTIONAL, AND `extra="forbid"` IS THE LOAD-BEARING LINE. The
    ticket's third constraint is that nothing else on the row is mutable - not
    `body`, not `tier`, not the moment-tags, not either session id. Forbidding
    extras makes that STRUCTURAL rather than something the service remembers:
    a caller that sends `tier` gets a 422 naming the field, instead of a 200
    that quietly ignored it. A silently-dropped `tier` would be
    indistinguishable from an honoured one at the call site, and `tier` is the
    field `memory_decide` deliberately keeps behind a human.

    Optional rather than required because a row can be half-filled - condensed
    set, keywords not - and a both-or-nothing request would leave that row
    permanently incomplete. At least one is required; the service refuses a
    request naming neither rather than returning a 200 that did nothing.

    "Not sent" and "sent as null" are different requests, and the router tells
    them apart with `model_fields_set` rather than by comparing to None.
    """

    model_config = ConfigDict(extra="forbid")  # DWB-651 / DWB-664

    condensed: str | None = None
    keywords: list[str] | None = None


class MemoryFillResponse(BaseModel):
    """The row after the fill, including the history fields it did NOT touch.

    `created_at`, `fired_count` and the two session ids are echoed back not
    because a caller asked, but because this route exists precisely because
    withdraw-and-repost destroyed them. Returning them lets the caller SEE they
    survived instead of trusting that they did.
    """

    memory_id: int
    agent_id: int
    condensed: str | None
    keywords: list[str] | None
    filled: list[str]
    tier: str
    created_at: datetime
    fired_count: int
    created_session_id: int | None
    last_reinforced_session_id: int | None
    source_journal_id: int | None


class MemoryRekeyRequest(BaseModel):
    """POST /api/agents/{agent_id}/memories/{memory_id}/rekey body (DWB-667).

    BOTH REQUIRED, which is the difference from `MemoryFillRequest` and is the
    whole point of the operation. Fill completes a row that is missing a value;
    rekey REPLACES a keyword set that is present and dead, and a replacement
    that could not be checked against a situation would just write the next
    generation of filing labels.

    `extra="forbid"` carries the same load it carries on fill: nothing else on
    the row is mutable, and in particular `condensed` is NOT a field here. A
    caller that sends one gets a 422 naming it rather than a 200 that quietly
    revised a lesson. That separation is the reason this operation is allowed to
    replace at all - see `memory_fill.rekey_memory`.
    """

    model_config = ConfigDict(extra="forbid")

    keywords: list[str]
    situation: str


class MemoryRekeyResponse(BaseModel):
    """The row after re-keywording, with the keywords it REPLACED.

    `previous_keywords` is the load-bearing field. A rekey that could not say
    what it overwrote would be indistinguishable from a fill on an empty column,
    and this is the one operation in the lane that destroys a value rather than
    completing one. The history fields are echoed for DWB-664's reason: this
    route exists because withdraw-and-repost would have destroyed them.
    """

    memory_id: int
    agent_id: int
    previous_keywords: list[str] | None
    keywords: list[str] | None
    situation: str | None
    condensed: str | None
    tier: str
    created_at: datetime
    fired_count: int
    created_session_id: int | None
    last_reinforced_session_id: int | None


class MemoryWithdrawRequest(BaseModel):
    """DWB-626: retract one of your own memory rows.

    `reason` is optional and free text. It is appended to the JOURNALED body
    rather than added to `tags`, because tags are the controlled vocabulary the
    journal search filters on and a free-text reason in there would make every
    retraction its own unsearchable tag.
    """
    model_config = ConfigDict(extra="forbid")  # DWB-651

    reason: str | None = None


class MemoryWithdrawResponse(BaseModel):
    """What was withdrawn, and WHERE IT WENT.

    `journal_entry_id` is the load-bearing field. A withdrawal that could not
    say where the content landed would be indistinguishable from a deletion,
    and the retraction is recoverable precisely because this id exists.
    """

    memory_id: int
    agent_id: int
    tier: str
    body: str
    context_key: str | None
    withdrawn: bool
    journal_entry_id: int
    journal_tags: list[str]
    reason: str | None

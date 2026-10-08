# Path: tests/test_memory_condensed_keywords_dwb654.py
# File: test_memory_condensed_keywords_dwb654.py
# Created: 2026-10-08 (DWB-654)
# Purpose: Guard the two new agent_memories columns at the DB/MODEL level -
#          that they exist, stay nullable until DWB-656, carry no default, and
#          round-trip their declared types. API enforcement is DWB-657's and is
#          deliberately NOT asserted here.
# Caller: pytest
# Callees: app.models.agent_memory.AgentMemory
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on the ORM round-trip and on DB-level nullability
# Last Modified: 2026-10-08 (DWB-654: rescoped off the API path after DWB-657's
#                write gate landed mid-ticket - see the module docstring)

"""DWB-654: `condensed` and `keywords` on agent_memories.

WHAT THIS FILE CAN AND CANNOT PROVE, STATED FIRST BECAUSE IT CHANGES HOW TO READ
EVERY ASSERTION BELOW.

`tests/conftest.py` builds the test schema with `Base.metadata.create_all`, from
the MODELS. It does not run migrations. So a green run here proves the code
agrees with the model; it proves NOTHING about whether the migration applied
cleanly to a populated database, and it would stay green against a live schema
that never got the columns at all.

That gap is not hypothetical for this ticket - the live table had 831 rows and
the whole reason both columns are nullable is that a populated table fails in
ways an empty one cannot. The migration evidence is therefore a LIVE
information_schema read plus a down/up round trip against a copy of the live
structure, recorded in the ticket, and it is deliberately not reproduced here as
if a passing test were the same thing.

WHAT IS WORTH ASSERTING HERE: the model shape three other tickets are building
against, and that the DATABASE still tolerates NULL. The second matters more
than it looks. 657 owns the write gate, 655 owns the backfill, 656 owns the NOT
NULL flip, and they have to land IN THAT ORDER. If the column goes NOT NULL
before the backfill, 832 existing rows become unwritable and the backfill that
would have fixed them cannot run. If a default appears instead, those rows
silently acquire a condensed line nobody wrote, indistinguishable from an
author-supplied one at every later read. These tests fail on either.

THIS FILE WAS RESCOPED MID-TICKET AND THE REASON IS WORTH KEEPING. It originally
asserted, through the API, that a write with neither field still succeeds -
true when written, and false about twenty minutes later when DWB-657's write
gate landed in the same tree. That gate is correct and it is not 654's to argue
with. But it showed the tests were pointed at the wrong layer: an API-path
assertion about these columns is a test of somebody else's contract, and it
goes red every time that contract legitimately moves. Everything here now goes
through the ORM, which is the layer 654 actually owns.
"""

from sqlalchemy import JSON, Text

from app.models.agent_memory import AgentMemory, MemoryTier


class TestTheColumnsExistAndAreNullable:
    """The shape 657, 658, 659, 660 and 661 are building against."""

    def test_both_columns_are_declared_nullable_with_the_agreed_types(self):
        condensed = AgentMemory.__table__.columns["condensed"]
        keywords = AgentMemory.__table__.columns["keywords"]

        assert condensed.nullable is True, (
            "condensed became NOT NULL at the model level. The NOT NULL flip is "
            "DWB-656 and comes AFTER the DWB-655 backfill; doing it here breaks "
            "every write until that backfill exists."
        )
        assert keywords.nullable is True, "keywords became NOT NULL - see DWB-656"

        # Types asserted because three other tickets serialise against them.
        assert isinstance(condensed.type, Text), (
            f"condensed is {condensed.type!r}. It is Text and NOT a capped "
            "String on purpose: 'one line' is a policy owned by DWB-657's write "
            "gate, and a length here would commit that gate to a number chosen "
            "in a migration."
        )
        assert isinstance(keywords.type, JSON), (
            f"keywords is {keywords.type!r}. It is JSON to match "
            "journal_entries.tags rather than invent a second convention for a "
            "short list of short strings."
        )

    def test_neither_column_has_a_default(self):
        """A default is the quiet version of the thing DWB-656 is for.

        If either column acquired a server default, every one of the 831
        pre-existing rows would carry a value nobody wrote, and it would read
        exactly like an author-supplied one forever after. NULL has to stay
        legible as "written before this was asked for".
        """
        for name in ("condensed", "keywords"):
            column = AgentMemory.__table__.columns[name]
            assert column.default is None, f"{name} gained a Python-side default"
            assert column.server_default is None, f"{name} gained a server default"


class TestTheyRoundTripThroughTheORM:
    """Declared type versus what actually comes back out.

    ASSERTED THROUGH THE ORM AND NOT THROUGH THE API, DELIBERATELY. DWB-657's
    write gate landed in this tree while this file was being written, and it
    now refuses a POST with no `condensed`. That is correct and it is 657's
    contract, not mine - but it means an API-path test of these columns is a
    test of somebody else's gate, and it would go red every time that gate's
    rules move. DWB-654 owns the column and the model; this tests exactly that.
    """

    def test_a_row_written_with_neither_value_is_accepted_by_the_DATABASE(
        self, db_session, make_agent
    ):
        """The DB-level permissiveness that DWB-656 will one day remove.

        This is the assertion that actually belongs to 654. 832 live rows carry
        NULL in both columns, the DWB-655 backfill has not run, and until it
        does the database MUST keep accepting NULL - otherwise every one of
        those rows becomes unwritable and the backfill itself cannot run.

        Written through the ORM rather than the API on purpose: 657's gate
        refuses this shape at the HTTP layer, which is right, and says nothing
        about what the column permits underneath.
        """
        agent = make_agent()
        row = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.working,
            body="a row from before anyone asked for a condensed line",
        )
        db_session.add(row)
        db_session.flush()

        assert row.id is not None, "the insert was rejected at the database level"
        assert row.condensed is None
        assert row.keywords is None

    def test_values_set_directly_survive_a_refresh(self, db_session, make_agent):
        """A list goes in and a LIST comes back, not a string of one.

        JSON columns are the usual place this goes wrong: a driver that stored
        the repr would round-trip a two-item list as a 20-character string and
        every length check downstream would read 20.
        """
        agent = make_agent()
        row = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.scar,
            body="the setup, at length",
            condensed="assert the match count, do not print it",
            keywords=["instrument", "self-match"],
        )
        db_session.add(row)
        db_session.flush()
        memory_id = row.id
        db_session.expire(row)

        reloaded = db_session.get(AgentMemory, memory_id)
        assert reloaded.condensed == "assert the match count, do not print it"
        assert reloaded.keywords == ["instrument", "self-match"]
        assert isinstance(reloaded.keywords, list), (
            f"keywords came back as {type(reloaded.keywords).__name__}, not a list"
        )
        assert len(reloaded.keywords) == 2


class TestTheConstraintFlipHasNotHappenedYet:
    """DWB-656 flips these to NOT NULL, AFTER the DWB-655 backfill.

    These tests fail the day that lands, which is the point - the flip should
    be a deliberate change to this file, not something that happens to a
    nullable column while nobody is looking. 654 must not pre-empt it and
    neither must 657, whose enforcement is at the API.
    """

    def test_the_model_still_permits_null_in_both_columns(self):
        for name in ("condensed", "keywords"):
            assert AgentMemory.__table__.columns[name].nullable is True, (
                f"{name} is NOT NULL at the model level. The DWB-655 backfill "
                "has not run; flipping now makes 832 existing rows unwritable "
                "and blocks the backfill that would have fixed them."
            )

    def test_a_null_row_and_a_filled_row_coexist(self, db_session, make_agent):
        """Both states in one table at once, which is the whole transitional
        period 655 and 656 exist to end.

        Asserted together rather than as two tests: the interesting property is
        that the column tolerates BOTH, and two separate tests would each pass
        against a table that only permitted its own case.
        """
        agent = make_agent()
        bare = AgentMemory(
            agent_id=agent["id"], tier=MemoryTier.working, body="pre-654 shape"
        )
        filled = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.scar,
            body="post-657 shape",
            condensed="grade the account, not the headline",
            keywords=["retraction", "accounting"],
        )
        db_session.add_all([bare, filled])
        db_session.flush()

        assert bare.id is not None and filled.id is not None
        assert bare.condensed is None
        assert filled.condensed == "grade the account, not the headline"

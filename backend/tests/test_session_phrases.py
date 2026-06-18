# Path: tests/test_session_phrases.py
# File: test_session_phrases.py
# Created: 2026-06-09
# Purpose: Unit tests for app.config.session_phrases regex matchers (DWB-336)
# Caller: pytest
# Callees: app.config.session_phrases
# Data In: free-form strings
# Data Out: Assertions on match_open / match_close return values
# Last Modified: 2026-06-17
#
# DWB-378 (2026-06-11): added TestCloseVariants for the broadened
# _CLOSE_SOURCES catalogue (target-suffixed + lighter wrap-up variants).
# DWB-394 (2026-06-17): added TestCloseNegativeContext for the close-matcher
# interrogative / reported-speech guard + <name> stop-word exclusion.

"""Tests for the DWB session phrase regex catalogue.

Covers:
  - positive matches across every "real" variant in OPEN_PATTERNS / CLOSE_PATTERNS
  - case-insensitivity and whitespace fuzz
  - rejection of bare chitchat / non-phrases (no false positives)
  - returned substring is suitable for storing in open_phrase / close_phrase
  - empty / None inputs do not crash
"""

import pytest

from app.config.session_phrases import (
    CLOSE_PATTERNS,
    OPEN_PATTERNS,
    match_close,
    match_open,
)


class TestOpenMatchPositive:
    """Every open variant we ship documentation for must match."""

    @pytest.mark.parametrize(
        "text",
        [
            "you are archie, you are team lead, read the playbook",
            "You Are Archie, You Are Team Lead, Read The Playbook",  # case-insensitive
            "you are archie, read the playbook",
            "you are sylvie, read your playbook",
            "you are barry, read your handoff and playbook",
            "you are archie,  read   the  playbook",  # extra whitespace
            "you are archie,\nread the playbook",  # newline whitespace
            "read your handoff and playbook",
            "Read the handoff and playbook",
            "open a dwb session",
            "open the session",
            "you are archie, read your handoff",
        ],
    )
    def test_matches(self, text):
        result = match_open(text)
        assert result is not None, f"expected match for {text!r}"
        # Returned substring should be non-empty and recognisable
        assert len(result.strip()) > 0


class TestOpenMatchNegative:
    """Bare chitchat must NOT match — false positives are worse than misses."""

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "you are archie",  # no discriminator
            "you are great",  # not a session phrase
            "read the docs",  # wrong noun
            "playbook is great",  # discriminator without trigger
            "",
            "   ",
        ],
    )
    def test_does_not_match(self, text):
        assert match_open(text) is None, f"unexpected match for {text!r}"

    def test_none_input(self):
        assert match_open(None) is None


class TestCloseMatchPositive:
    """Every close variant we ship documentation for must match."""

    @pytest.mark.parametrize(
        "text",
        [
            "have the team write docs and exit",
            "Have The Team Write Docs And Exit",  # case-insensitive
            "team write docs and exit",
            "write docs and exit",
            "close the session",
            "close this session",
            "close the dwb session",
            "shut it down for the night",
            "shut it down",
            "wrap it up for the night",
            "wrap up for the night",
            "end of session",
            "that's a wrap",
            "team   write   docs   and   exit",  # extra whitespace
            "team\twrite\tdocs\tand\texit",  # tabs
        ],
    )
    def test_matches(self, text):
        result = match_close(text)
        assert result is not None, f"expected close match for {text!r}"
        assert len(result.strip()) > 0


class TestCloseMatchNegative:
    """Conversational language must not trip the close matcher."""

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "exit",  # too generic
            "write docs",  # missing "and exit"
            "the session was good",
            "",
            "   ",
        ],
    )
    def test_does_not_match(self, text):
        assert match_close(text) is None, f"unexpected close match for {text!r}"

    def test_none_input(self):
        assert match_close(None) is None


class TestSubstringExtraction:
    """The returned substring should be the matched phrase — not the whole
    input — so the dashboard can show what triggered the open/close."""

    def test_open_substring_when_wrapped(self):
        wrapper = "great, now: you are archie, read the playbook — let's go"
        match = match_open(wrapper)
        assert match is not None
        # The matched slice is a contiguous chunk of the wrapper text
        assert match in wrapper
        # And contains the discriminator
        assert "playbook" in match.lower()

    def test_close_substring_when_wrapped(self):
        wrapper = "okay team, have the team write docs and exit when ready"
        match = match_close(wrapper)
        assert match is not None
        assert match in wrapper
        assert "write docs" in match.lower()


class TestOpenCommaOptional:
    """DWB-376: comma between <name> and the trailing clause is optional.

    Natural English drops the comma ("you are archie read your playbook").
    Layer-1 must match both forms identically.
    """

    @pytest.mark.parametrize(
        "text",
        [
            # "you are <name>, you are team lead, read the playbook" — both commas dropped
            "you are archie you are team lead read the playbook",
            "you are archie, you are team lead, read the playbook",
            # "you are <name>, you are team lead, read your playbook"
            "you are barry you are team lead read your playbook",
            "you are barry, you are team lead, read your playbook",
            # "you are <name>, read the playbook"
            "you are sylvie read the playbook",
            "you are sylvie, read the playbook",
            # "you are <name>, read your playbook"
            "you are pam read your playbook",
            "you are pam, read your playbook",
            # "you are <name>, read your handoff and playbook"
            "you are archie read your handoff and playbook",
            "you are archie, read your handoff and playbook",
            # "you are <name>, read the handoff and playbook"
            "you are barry read the handoff and playbook",
            "you are barry, read the handoff and playbook",
            # "you are <name>, read your handoff"
            "you are sylvie read your handoff",
            "you are sylvie, read your handoff",
        ],
    )
    def test_with_and_without_comma_match(self, text):
        result = match_open(text)
        assert result is not None, f"expected match for {text!r}"
        assert len(result.strip()) > 0

    def test_bare_name_still_no_match(self):
        # No discriminator clause = no open. Comma-optional must not turn
        # this into a false positive.
        assert match_open("you are archie") is None

    def test_close_with_no_commas_still_matches(self):
        # CLOSE patterns currently have no commas. The comma-optional pass
        # must not regress them.
        for text in [
            "have the team write docs and exit",
            "close the dwb session",
            "shut it down for the night",
            "that's a wrap",
        ]:
            assert match_close(text) is not None, f"close regressed on {text!r}"


class TestCloseVariants:
    """DWB-378: target-suffixed + lighter wrap-up close variants.

    Each new phrase is tested in two shapes: the bare canonical form and a
    natural-English form with surrounding text ("ok shut down ci for the
    night now"). Negative case: the leading token of a multi-token phrase
    (e.g., "time" alone) must not match — the trailing clause discriminator
    is the load-bearing half of every catalogue entry.
    """

    @pytest.mark.parametrize(
        "text",
        [
            # shut down for the night
            "shut down for the night",
            "ok shut down for the night now",
            # shut down <name>
            "shut down ci",
            "barry, shut down dwb please",
            # shut down <name> for the night
            "shut down ci for the night",
            "ok shut down ci for the night now",
            # wrap up <name>
            "wrap up ci",
            "lets wrap up barry and call it",
            # wrap up <name> for the night
            "wrap up ci for the night",
            "ok wrap up barry for the night",
            # done for the day
            "done for the day",
            "im done for the day",
            # done for the night
            "done for the night",
            "alright, done for the night",
            # logging off
            "logging off",
            "ok logging off now",
            # lets close it
            "lets close it",
            "alright lets close it for now",
            # time to close
            "time to close",
            "i think its time to close this out",
            # thats it for tonight
            "thats it for tonight",
            "alright thats it for tonight team",
            # thats it for the night
            "thats it for the night",
            "ok thats it for the night",
        ],
    )
    def test_new_close_variants_match(self, text):
        result = match_close(text)
        assert result is not None, f"expected close match for {text!r}"
        assert len(result.strip()) > 0

    def test_bare_leading_token_does_not_match(self):
        # "time" alone is not a close phrase. The trailing-clause
        # discriminator ("to close") is required.
        assert match_close("time") is None
        # Same for other leading tokens that would be too generic on their own.
        assert match_close("logging") is None
        assert match_close("done") is None
        assert match_close("wrap") is None

    def test_existing_close_phrases_still_match(self):
        # Belt-and-suspenders: the new appends must not regress the
        # original catalogue.
        for text in [
            "have the team write docs and exit",
            "close the session",
            "shut it down for the night",
            "end of session",
            "that's a wrap",
        ]:
            assert match_close(text) is not None, f"close regressed on {text!r}"


class TestCloseNegativeContext:
    """DWB-394: questions / reported speech about shutting down must never
    close a session.

    The trigger bug: "...didn't close when I said shut down last?" matched the
    "shut down <name>" pattern because <name> compiled to a bare ``\\w+`` and
    "last" satisfied the name slot. Two layers now prevent it: a stop-word
    exclusion on the close <name> slot, and an interrogative / reported-speech
    guard on the matched span.
    """

    def test_regression_question_does_not_close(self):
        # The exact phrase from the incident must NOT match.
        assert (
            match_close("...didn't close when I said shut down last?") is None
        )

    @pytest.mark.parametrize(
        "text",
        [
            # Stop-word fillers can't satisfy the <name> slot, so these never
            # match regardless of punctuation.
            "shut down last",
            "shut down when",
            "shut down it",
            "shut down that",
            "shut down this",
            "wrap up last",
        ],
    )
    def test_stopword_name_slot_does_not_match(self, text):
        assert match_close(text) is None, f"unexpected close match for {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            # A real agent name (archie) DOES satisfy the slot, so these are
            # blocked purely by the interrogative / reported-speech guard.
            "what happens when I said shut down archie?",
            "why did you shut down archie",
            "what does shut down archie even do",
            "should I shut down archie",
            "when I said shut down archie I meant later",
            "did you shut it down for the night already?",
        ],
    )
    def test_interrogative_or_reported_speech_does_not_close(self, text):
        assert match_close(text) is None, f"unexpected close match for {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            # Genuine commands still close.
            "shut it down for the night",
            "shut down archie",
            "shut down ci",
            "wrap up barry for the night",
            "close the session",
            "that's a wrap",
        ],
    )
    def test_genuine_commands_still_close(self, text):
        result = match_close(text)
        assert result is not None, f"expected close match for {text!r}"
        assert len(result.strip()) > 0

    def test_command_after_a_separate_question_still_closes(self):
        # The question is its own sentence; the close command stands alone in
        # the next sentence and must still fire.
        result = match_close("Are you done? shut it down for the night.")
        assert result is not None
        assert "shut it down" in result.lower()

    def test_command_later_in_text_after_quoted_span_still_closes(self):
        # An earlier quoted/questioned span is skipped; a real command later
        # in the same text still closes.
        text = "I didn't say shut down archie. anyway, shut it down for the night"
        result = match_close(text)
        assert result is not None
        assert "shut it down" in result.lower()


class TestCatalogueShape:
    """Sanity-check the compiled catalogue itself so a future edit can't
    accidentally empty a list and silently disable detection."""

    def test_open_patterns_non_empty(self):
        assert len(OPEN_PATTERNS) > 0
        assert all(hasattr(p, "search") for p in OPEN_PATTERNS)

    def test_close_patterns_non_empty(self):
        assert len(CLOSE_PATTERNS) > 0
        assert all(hasattr(p, "search") for p in CLOSE_PATTERNS)

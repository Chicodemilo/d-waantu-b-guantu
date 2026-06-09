# Path: tests/test_session_phrases.py
# File: test_session_phrases.py
# Created: 2026-06-09
# Purpose: Unit tests for app.config.session_phrases regex matchers (DWB-336)
# Caller: pytest
# Callees: app.config.session_phrases
# Data In: free-form strings
# Data Out: Assertions on match_open / match_close return values
# Last Modified: 2026-06-09

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


class TestCatalogueShape:
    """Sanity-check the compiled catalogue itself so a future edit can't
    accidentally empty a list and silently disable detection."""

    def test_open_patterns_non_empty(self):
        assert len(OPEN_PATTERNS) > 0
        assert all(hasattr(p, "search") for p in OPEN_PATTERNS)

    def test_close_patterns_non_empty(self):
        assert len(CLOSE_PATTERNS) > 0
        assert all(hasattr(p, "search") for p in CLOSE_PATTERNS)

# Path: tests/test_keyword_extraction.py
# File: test_keyword_extraction.py
# Created: 2026-06-25
# Purpose: Unit tests for the pure keyword extraction + normalization module
#          (DWB-482). Covers normalization (lower/kebab/ticket-key-verbatim),
#          tokenization, stopword drop, ticket-key preservation regardless of
#          frequency, the min-frequency floor, the top-N cap, weight=count, and
#          deterministic ranking. No DB - the module is pure.
# Caller: pytest
# Callees: app.services.keyword_extraction
# Data In: literal strings
# Data Out: assertions
# Last Modified: 2026-06-25

from app.services.keyword_extraction import (
    DEFAULT_MIN_FREQUENCY,
    KeywordWeight,
    extract_keywords,
    is_ticket_key,
    normalize_term,
    tokenize,
)


class TestIsTicketKey:
    def test_matches_standard_keys(self):
        assert is_ticket_key("DWB-468")
        assert is_ticket_key("CI-401")
        assert is_ticket_key("RVP-007")

    def test_rejects_non_keys(self):
        assert not is_ticket_key("tmux")
        assert not is_ticket_key("a-1")  # prefix must be 2+ letters
        assert not is_ticket_key("DWB-")
        assert not is_ticket_key("123-456")


class TestNormalizeTerm:
    def test_lowercases_plain_word(self):
        assert normalize_term("Sprint") == "sprint"

    def test_strips_surrounding_punctuation(self):
        assert normalize_term("tmux,") == "tmux"
        assert normalize_term("(migration)") == "migration"

    def test_kebab_cases_underscores_and_slashes(self):
        assert normalize_term("Archie_DWB") == "archie-dwb"
        assert normalize_term("team/lead") == "team-lead"

    def test_already_kebab_unchanged(self):
        assert normalize_term("system-ops") == "system-ops"

    def test_ticket_key_preserved_verbatim_uppercased(self):
        assert normalize_term("DWB-468") == "DWB-468"
        assert normalize_term("dwb-468") == "DWB-468"  # case variants dedupe

    def test_pure_punctuation_returns_none(self):
        assert normalize_term("---") is None
        assert normalize_term("!!!") is None


class TestTokenize:
    def test_splits_and_normalizes(self):
        assert tokenize("Fix the Migration bug") == ["fix", "the", "migration", "bug"]

    def test_preserves_ticket_keys(self):
        assert tokenize("commit for DWB-468 done") == ["commit", "for", "DWB-468", "done"]

    def test_empty_text(self):
        assert tokenize("") == []
        assert tokenize("   ") == []


class TestExtractKeywords:
    def test_stopword_dropped_nonstopword_kept_and_ranked(self):
        # "the" x60 must drop; "tmux" x50 must stay and rank high.
        texts = ["the " * 60 + "tmux " * 50]
        result = extract_keywords(texts)
        kws = {k.keyword: k.weight for k in result}
        assert "the" not in kws
        assert kws.get("tmux") == 50
        # tmux should be the top-ranked term here.
        assert result[0].keyword == "tmux"

    def test_ticket_key_kept_regardless_of_frequency(self):
        # A single mention of a ticket key (weight 1) is kept even though the
        # default min-frequency floor is > 1.
        assert DEFAULT_MIN_FREQUENCY > 1
        result = extract_keywords(["touched DWB-468 once"])
        keys = [k for k in result if k.is_ticket_key]
        assert len(keys) == 1
        assert keys[0].keyword == "DWB-468"
        assert keys[0].weight == 1

    def test_min_frequency_floor_drops_low_freq_normals(self):
        # "alpha" x1 is below the floor and dropped; "beta" x3 is kept.
        texts = ["alpha", "beta beta beta"]
        result = extract_keywords(texts, min_frequency=2)
        kws = {k.keyword: k.weight for k in result}
        assert "alpha" not in kws
        assert kws["beta"] == 3

    def test_weight_equals_count(self):
        result = extract_keywords(["migration migration migration"], min_frequency=1)
        kws = {k.keyword: k.weight for k in result}
        assert kws["migration"] == 3

    def test_top_n_caps_normal_terms_but_not_ticket_keys(self):
        # Five distinct normal terms each x2, plus three ticket keys x1.
        # top_n=2 keeps only the top 2 normals, but all 3 keys survive.
        texts = [
            "aaa aaa bbb bbb ccc ccc ddd ddd eee eee",
            "DWB-1 DWB-2 DWB-3",
        ]
        result = extract_keywords(texts, min_frequency=2, top_n=2)
        normals = [k for k in result if not k.is_ticket_key]
        keys = [k for k in result if k.is_ticket_key]
        assert len(normals) == 2
        assert len(keys) == 3

    def test_deterministic_ranking_weight_desc_then_alpha(self):
        # gamma x3, alpha x2, beta x2 -> gamma first, then alpha before beta
        # (alphabetical tie-break on equal weight).
        texts = ["gamma gamma gamma alpha alpha beta beta"]
        result = extract_keywords(texts, min_frequency=2)
        ordered = [k.keyword for k in result]
        assert ordered == ["gamma", "alpha", "beta"]

    def test_same_input_same_output(self):
        texts = ["DWB-468 migration migration sprint sprint sprint tmux tmux"]
        assert extract_keywords(texts) == extract_keywords(texts)

    def test_returns_keywordweight_instances(self):
        result = extract_keywords(["beta beta"], min_frequency=2)
        assert result and all(isinstance(k, KeywordWeight) for k in result)

    def test_empty_corpus(self):
        assert extract_keywords([]) == []
        assert extract_keywords(["", "   "]) == []

    def test_role_and_agent_names_normalize(self):
        # Agent/role names are part of the corpus; they kebab-case cleanly.
        texts = ["system-ops system-ops Archie_DWB Archie_DWB"]
        result = extract_keywords(texts, min_frequency=2)
        kws = {k.keyword: k.weight for k in result}
        assert kws.get("system-ops") == 2
        assert kws.get("archie-dwb") == 2

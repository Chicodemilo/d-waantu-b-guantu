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
    rank_tfidf,
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

    def test_bare_numbers_dropped_letters_kept(self):
        # DWB-500: bare digits / numeric fragments are noise (digit analogue of
        # number-words); anything with a letter survives; ticket keys exempt.
        assert normalize_term("2") is None
        assert normalize_term("100") is None
        assert normalize_term("1)") is None
        assert normalize_term("3.0") is None
        assert normalize_term("utf8") == "utf8"  # has a letter -> kept
        assert normalize_term("DWB-500") == "DWB-500"  # ticket key preserved


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


class TestStopwordsDwb499:
    """Number-words + generic filler are dropped; DWB domain terms are NOT."""

    def test_number_words_dropped(self):
        # Cardinals + ordinals are pure counting noise (the "one" x133 bug).
        texts = ["one " * 60 + "two three first second migration migration"]
        result = extract_keywords(texts, min_frequency=1)
        kws = {k.keyword for k in result}
        for noise in ("one", "two", "three", "first", "second"):
            assert noise not in kws
        assert "migration" in kws  # real term survives

    def test_generic_filler_dropped(self):
        texts = ["real real really new actually stuff etc migration migration"]
        result = extract_keywords(texts, min_frequency=1)
        kws = {k.keyword for k in result}
        for filler in ("real", "really", "new", "actually", "stuff", "etc"):
            assert filler not in kws
        assert "migration" in kws

    def test_domain_terms_NOT_dropped(self):
        # The principle (DWB-499): DWB vocabulary stays - it's legitimately
        # relevant when a session is about it. TF-IDF, not stopwords, handles
        # cross-session ubiquity.
        texts = ["ticket session keyword summary sprint test"]
        result = extract_keywords(texts, min_frequency=1)
        kws = {k.keyword for k in result}
        for domain in ("ticket", "session", "keyword", "summary", "sprint", "test"):
            assert domain in kws


class TestRankTfidf:
    """DWB-500: TF-IDF re-rank. df/N passed in; module stays pure."""

    def test_ubiquitous_term_in_every_doc_is_dropped(self):
        # "tests" in every session (df==N) -> idf 0 -> dropped; a term in one
        # session survives.
        texts = ["tests tests tests tests distinctive distinctive"]
        df = {"tests": 10, "distinctive": 1}
        result = rank_tfidf(texts, document_frequencies=df, total_documents=10)
        kws = {k.keyword for k in result}
        assert "tests" not in kws
        assert "distinctive" in kws

    def test_distinctive_outranks_higher_tf_ubiquitous(self):
        # Archie's case: a high-TF near-ubiquitous term must NOT outrank a
        # lower-TF distinctive term once IDF is applied.
        texts = ["tests " * 20 + "distinctive " * 5]
        df = {"tests": 50, "distinctive": 1}
        result = rank_tfidf(texts, document_frequencies=df, total_documents=53)
        order = [k.keyword for k in result]
        assert order[0] == "distinctive"
        d = next(k for k in result if k.keyword == "distinctive")
        t = next(k for k in result if k.keyword == "tests")
        assert d.weight > t.weight  # relevance score, not raw TF (20 vs 5)

    def test_weight_is_relevance_score_not_raw_count(self):
        import math

        texts = ["alpha alpha"]  # tf=2
        df = {"alpha": 1}
        result = rank_tfidf(texts, document_frequencies=df, total_documents=10)
        alpha = next(k for k in result if k.keyword == "alpha")
        expected = max(1, round(2 * math.log((10 + 1) / (1 + 1))))
        assert alpha.weight == expected
        assert alpha.weight != 2  # not the raw count

    def test_brand_new_term_surfaces(self):
        # df=0 (term never stored) -> high idf -> distinctive.
        result = rank_tfidf(
            ["novelterm novelterm"], document_frequencies={}, total_documents=10
        )
        assert "novelterm" in {k.keyword for k in result}

    def test_ticket_key_always_kept_even_if_ubiquitous(self):
        # A ticket key in every doc (df==N -> idf 0) is still kept, floored >=1.
        result = rank_tfidf(
            ["DWB-500 work"], document_frequencies={"DWB-500": 100}, total_documents=100
        )
        keys = [k for k in result if k.is_ticket_key]
        assert any(k.keyword == "DWB-500" and k.weight >= 1 for k in keys)

    def test_low_n_falls_back_to_pure_tf(self):
        # N<2 -> degenerate IDF -> pure-TF ranking (weight == raw count).
        texts = ["alpha alpha alpha beta"]
        result = rank_tfidf(texts, document_frequencies={}, total_documents=1)
        kws = {k.keyword: k.weight for k in result}
        assert kws.get("alpha") == 3  # raw TF preserved, not a score

    def test_deterministic(self):
        texts = ["tests tests distinctive distinctive distinctive"]
        df = {"tests": 8, "distinctive": 1}
        a = rank_tfidf(texts, document_frequencies=df, total_documents=10)
        b = rank_tfidf(texts, document_frequencies=df, total_documents=10)
        assert a == b

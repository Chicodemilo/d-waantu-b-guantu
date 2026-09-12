# Path: tests/test_token_over_attribution_dwb506.py
# File: test_token_over_attribution_dwb506.py
# Created: 2026-07-28
# Purpose: Regression tests for DWB-506 - cache_read_input_tokens must NOT be summed into total_tokens (it re-counts cached context every turn and inflated attribution to billions)
# Caller: pytest
# Callees: app.services.hook_tracking.parse_transcript
# Data In: JSONL transcript files written per test (realistic multi-turn shapes)
# Data Out: assertions on parse_transcript total_tokens vs breakdown
# Last Modified: 2026-07-28

"""Regression coverage for DWB-506 (token over-attribution).

Root cause: `_parse_transcript_lines` summed `cache_read_input_tokens` into
`total_tokens`. cache_read is the volume re-read from the prompt cache on each
turn, which for a multi-turn session is ~the entire prior context EVERY turn.
Summing it across turns is cumulative double counting - each cached token is
re-counted on every subsequent turn. On DWB session 65 this inflated a real
~33M-token teammate session to 1.33B (97.5% of the figure was cache_read),
which in turn produced the 5.47B rollup that overflowed the INT column (DWB-505).

Fix: total_tokens = input + output + cache_creation (the NEW / delta tokens each
turn). cache_read is retained in the breakdown for cache-efficiency visibility
but excluded from the total.
"""

import json


def _write_transcript(tmp_path, messages, *, agent_name="backend-worker"):
    """Write a realistic Claude Code JSONL transcript: an identity line then one
    assistant entry per turn with a nested message.usage block."""
    path = tmp_path / "dwb506_transcript.jsonl"
    lines = [json.dumps({"agentName": agent_name})]
    for u in messages:
        lines.append(json.dumps({"message": {"usage": {
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": u.get("cache_read_input_tokens", 0),
        }}}))
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_cache_read_excluded_from_total_multi_turn(tmp_path):
    """A multi-turn session whose cache_read grows every turn (the cache is
    re-read cumulatively) must NOT have that cumulative volume in the total.

    Five turns, cache_read doubling each turn (10k..160k) = 310k of pure
    re-reads. The delta tokens (input+output+cache_creation) are tiny by
    comparison. Pre-fix total would have been dominated by the 310k cache_read.
    """
    from app.services.hook_tracking import parse_transcript

    messages = [
        {"input_tokens": 100, "output_tokens": 500, "cache_creation_input_tokens": 2000,
         "cache_read_input_tokens": 10_000},
        {"input_tokens": 80, "output_tokens": 400, "cache_creation_input_tokens": 1500,
         "cache_read_input_tokens": 20_000},
        {"input_tokens": 60, "output_tokens": 300, "cache_creation_input_tokens": 1000,
         "cache_read_input_tokens": 40_000},
        {"input_tokens": 40, "output_tokens": 200, "cache_creation_input_tokens": 800,
         "cache_read_input_tokens": 80_000},
        {"input_tokens": 20, "output_tokens": 100, "cache_creation_input_tokens": 500,
         "cache_read_input_tokens": 160_000},
    ]
    path = _write_transcript(tmp_path, messages)
    result = parse_transcript(path)

    delta = sum(
        m["input_tokens"] + m["output_tokens"] + m["cache_creation_input_tokens"]
        for m in messages
    )
    cache_read_total = sum(m["cache_read_input_tokens"] for m in messages)

    # total_tokens is the delta only - the 310k of cache_read is excluded.
    assert result["total_tokens"] == delta
    assert result["total_tokens"] == 100 + 500 + 2000 + 80 + 400 + 1500 + 60 + 300 + 1000 + 40 + 200 + 800 + 20 + 100 + 500
    # cache_read is still fully reported in the breakdown for visibility.
    assert result["breakdown"]["cache_read"] == cache_read_total == 310_000
    # The cumulative cache_read dwarfs the real work; excluding it is the fix.
    assert result["total_tokens"] < cache_read_total


def test_session_65_shape_is_not_inflated(tmp_path):
    """One turn matching the live session-65 row that reported 1,329,461,919
    tokens. The honest (delta) figure is ~33M; the 1.296B was cache_read.
    """
    from app.services.hook_tracking import parse_transcript

    path = _write_transcript(tmp_path, [{
        "input_tokens": 607_247,
        "output_tokens": 5_142_260,
        "cache_creation_input_tokens": 27_159_267,
        "cache_read_input_tokens": 1_296_553_145,
    }])
    result = parse_transcript(path)

    expected_delta = 607_247 + 5_142_260 + 27_159_267  # 32,908,774
    old_inflated = expected_delta + 1_296_553_145  # 1,329,461,919 (the live value)

    assert result["total_tokens"] == expected_delta
    assert result["total_tokens"] != old_inflated
    # Confirms the ~40x over-attribution is gone.
    assert old_inflated / result["total_tokens"] > 40
    assert result["breakdown"]["cache_read"] == 1_296_553_145


def test_no_cache_read_total_unchanged(tmp_path):
    """When a session has no cache_read, the total is unchanged by the fix -
    it stays input + output + cache_creation. Guards against over-correction."""
    from app.services.hook_tracking import parse_transcript

    path = _write_transcript(tmp_path, [
        {"input_tokens": 1000, "output_tokens": 500, "cache_creation_input_tokens": 200},
        {"input_tokens": 300, "output_tokens": 150},
    ])
    result = parse_transcript(path)

    assert result["total_tokens"] == 1000 + 500 + 200 + 300 + 150
    assert result["breakdown"]["cache_read"] == 0

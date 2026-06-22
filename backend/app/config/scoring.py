# Path: app/config/scoring.py
# File: scoring.py
# Created: 2026-06-22
# Purpose: Tunable point values + influence budget for the agent scoring system (DWB-424). Single source of truth shared by the apply helper, the auto-trigger engine (DWB-425), and the human/peer tools (DWB-426/427).
# Caller: app/services/scoring.py, app/services/* (auto-triggers)
# Callees: none
# Data In: none
# Data Out: SCORE_POINTS dict, INITIAL_INFLUENCE int, helper accessors
# Last Modified: 2026-06-22

"""Scoring point values (DWB-424).

The ledger (score_event) is authoritative; these are the deltas the auto and
human/peer paths apply. Values are SIGNED so callers read the delta directly
without re-deriving direction. Kept here so they are tunable in one place.

Defaults (epic 28 spec):
  ticket_closed     +5
  no_rework_bonus   +3
  rework            -8
  test_failure      -3
  stale             -1
  zero_token_close  -2
  gate_miss         -2
  forgot            -1
  INITIAL_INFLUENCE 20  (per-sprint peer budget; per-sprint reset is DWB-427)
"""

# Signed point deltas keyed by a stable string. The auto-trigger engine
# (DWB-425) and human/peer tools (DWB-426/427) look up deltas here rather than
# hardcoding magnitudes. Note: `no_rework_bonus` is a modifier applied on a
# ticket close (it has no standalone trigger_type); every other key maps 1:1 to
# a score_event.trigger_type value.
SCORE_POINTS: dict[str, int] = {
    "ticket_closed": 5,
    "no_rework_bonus": 3,
    "rework": -8,
    "test_failure": -3,
    "stale": -1,
    "zero_token_close": -2,
    "gate_miss": -2,
    "forgot": -1,
}

# Per-sprint influence budget each agent receives for the peer economy
# (DWB-427). Created on the agent_score cache row now; the per-sprint reset and
# the spend paths land in wave 2.
INITIAL_INFLUENCE: int = 20


def points_for(key: str, default: int = 0) -> int:
    """Return the signed delta for a scoring key, or `default` if unknown."""
    return SCORE_POINTS.get(key, default)

# Path: app/config/scoring.py
# File: scoring.py
# Created: 2026-06-22
# Purpose: Tunable point values + influence budget for the agent scoring system (DWB-424). Single source of truth shared by the apply helper, the auto-trigger engine (DWB-425), and the human/peer tools (DWB-426/427).
# Caller: app/services/scoring.py, app/services/* (auto-triggers)
# Callees: none
# Data In: none
# Data Out: SCORE_POINTS dict, INITIAL_INFLUENCE int, helper accessors
# Last Modified: 2026-06-23 (DWB-427: anti-gaming caps)

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
# (DWB-427). Remaining influence is DERIVED from the ledger per active sprint
# (INITIAL_INFLUENCE - sum of actor_cost the agent spent this sprint), so it
# auto-resets each sprint and never drifts from a stored counter.
INITIAL_INFLUENCE: int = 20

# Peer-economy anti-gaming caps (DWB-427), all tunable here.
# - MAX_DING_PER_ACTION: most reputation one peer-stick can remove at once.
# - MAX_DING_PER_TARGET_PER_SPRINT: most one agent can dock a specific peer
#   across a whole sprint (kills vendettas).
# - MAX_GRANT_PER_TARGET_PER_SPRINT: symmetric cap on awarding a specific peer
#   across a sprint (kills collusion rings).
# Total outgoing is additionally bounded by INITIAL_INFLUENCE.
MAX_DING_PER_ACTION: int = 5
MAX_DING_PER_TARGET_PER_SPRINT: int = 10
MAX_GRANT_PER_TARGET_PER_SPRINT: int = 10


def points_for(key: str, default: int = 0) -> int:
    """Return the signed delta for a scoring key, or `default` if unknown."""
    return SCORE_POINTS.get(key, default)

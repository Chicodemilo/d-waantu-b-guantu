// Path: src/utils/scoring.js
// File: scoring.js
// Created: 2026-06-23
// Purpose: Shared helpers for the scoring leaderboard UI (DWB-433). Maps the API tier enum to terse plain-text labels, resolves a 1-based rank with a fall-back to row position, formats signed deltas, and decides which rows get the top/bottom-place highlight. Built against the rank/tier fields Stan is adding in DWB-432; degrades cleanly to position-based behaviour when those fields are absent.
// Caller: components/project/Scoreboard.jsx, components/project/LiveSessions.jsx
// Callees: None (leaf utility module)
// Data In: Leaderboard row objects { reputation, sprint_delta, influence, rank?, tier? }, index, total
// Data Out: Display strings + booleans
// Last Modified: 2026-06-23

// API tier enum (DWB-432) -> terse, icon-free label. Empty string for an
// unscored / missing tier so the cell renders blank rather than a placeholder.
export const TIER_LABELS = {
  best: 'TOP',
  podium: 'PODIUM',
  above: 'ABOVE',
  mid: 'MID',
  below: 'BELOW',
  dead_last: 'BOTTOM',
  unscored: '',
};

export function tierLabel(tier) {
  if (!tier) return '';
  if (tier in TIER_LABELS) return TIER_LABELS[tier];
  return String(tier).replace(/_/g, ' ').toUpperCase();
}

// 1-based rank. Prefer the API's `rank` field (DWB-432); otherwise fall back to
// the row's position in the already-sorted leaderboard.
export function rowRank(row, index) {
  const r = Number(row?.rank);
  return Number.isFinite(r) && r > 0 ? r : index + 1;
}

export function formatDelta(delta) {
  const n = Number(delta) || 0;
  return n > 0 ? `+${n}` : `${n}`;
}

export function deltaDirection(delta) {
  const n = Number(delta) || 0;
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'flat';
}

// Highlight the #1 row. Prefer the explicit tier when present, else the leader
// of a non-empty list.
export function isTopRow(row, index, total) {
  if (row?.tier) return row.tier === 'best';
  return total > 0 && index === 0;
}

// Highlight the last-place row. Prefer the explicit tier, else the final row of
// a list with more than one member (a single-row list is not "last place").
export function isBottomRow(row, index, total) {
  if (row?.tier) return row.tier === 'dead_last';
  return total > 1 && index === total - 1;
}

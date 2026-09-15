// Path: src/utils/format.js
// File: format.js
// Created: 2026-03-29
// Purpose: Shared formatting utilities for time and token display across all components. relativeAge (DWB-551) renders an API timestamp as a plain age; the API sends naive UTC (no trailing Z), so it normalizes before parsing, which a raw new Date(ts) gets wrong by the viewer's UTC offset. DWB-554 pointed ActivityFeed and AlertBanner here and added the absoluteAfterDays option so AlertBanner keeps its long-age absolute fallback without a private parser.
// Caller: All components that display time or token values
// Callees: None (leaf utility module)
// Data In: Numeric values (seconds, token counts)
// Data Out: Formatted display strings
// Last Modified: 2026-09-15 (DWB-554: absoluteAfterDays)

export function formatTime(seconds) {
  if (!seconds || seconds === 0) return '0m';
  if (seconds < 60) return '< 1m';
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`;
}

export function formatTokens(tokens) {
  if (!tokens || tokens === 0) return '0';
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return String(tokens);
}

// API timestamps are naive UTC ("2026-09-15T18:56:05"). Append Z so the browser
// does not read them as local time. Already-zoned strings pass through.
export function parseApiDate(ts) {
  if (!ts) return null;
  const s = typeof ts === 'string' ? ts : String(ts);
  const normalized = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Absolute local rendering of an API timestamp ("Sep 8, 14:30"). The instant is
// parsed as UTC; the output is deliberately in the viewer's local zone.
export function formatApiDateTime(ts, options = ABSOLUTE_DATE_OPTIONS) {
  const d = parseApiDate(ts);
  return d ? d.toLocaleDateString('en-US', options) : '';
}

const ABSOLUTE_DATE_OPTIONS = {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
};

// Plain relative age: "just now", "5m ago", "3h ago", "2d ago". Future or
// unparseable timestamps render as "just now" and "" respectively.
// `absoluteAfterDays` switches to an absolute local date once the age reaches
// that many days, which is what the alert banner wants for stale alerts.
export function relativeAge(ts, now = Date.now(), { absoluteAfterDays = null } = {}) {
  const d = parseApiDate(ts);
  if (!d) return '';
  const mins = Math.floor((now - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (absoluteAfterDays != null && days >= absoluteAfterDays) return formatApiDateTime(ts);
  return `${days}d ago`;
}

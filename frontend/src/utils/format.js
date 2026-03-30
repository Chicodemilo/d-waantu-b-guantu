// Path: src/utils/format.js
// File: format.js
// Created: 2026-03-29
// Purpose: Shared formatting utilities for time and token display across all components
// Caller: All components that display time or token values
// Callees: None (leaf utility module)
// Data In: Numeric values (seconds, token counts)
// Data Out: Formatted display strings
// Last Modified: 2026-03-29

export function formatTime(seconds) {
  if (!seconds || seconds === 0) return '\u2014';
  if (seconds < 60) return '< 1m';
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`;
}

export function formatTokens(tokens) {
  if (!tokens || tokens === 0) return '\u2014';
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return String(tokens);
}

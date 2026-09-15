// Path: src/utils/__tests__/format.test.js
// File: format.test.js
// Created: 2026-09-15
// Purpose: Tests for the shared relative-age helpers added in DWB-551: parseApiDate normalizes the API's naive-UTC timestamps (no trailing Z) so they are not read as local time, passes zoned strings through, and rejects junk; relativeAge renders just now / Nm / Nh / Nd against an injected clock.
// Caller: vitest test runner
// Callees: ../format
// Data In: Timestamp strings
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect } from 'vitest';
import { parseApiDate, relativeAge } from '../format';

describe('parseApiDate (DWB-551)', () => {
  it('reads a naive API timestamp as UTC, not local time', () => {
    expect(parseApiDate('2026-09-15T18:56:05').toISOString()).toBe('2026-09-15T18:56:05.000Z');
  });

  it('passes through timestamps that already carry a zone', () => {
    expect(parseApiDate('2026-09-15T18:56:05Z').toISOString()).toBe('2026-09-15T18:56:05.000Z');
    expect(parseApiDate('2026-09-15T20:56:05+02:00').toISOString()).toBe('2026-09-15T18:56:05.000Z');
  });

  it('returns null for empty or unparseable input', () => {
    expect(parseApiDate(null)).toBeNull();
    expect(parseApiDate('')).toBeNull();
    expect(parseApiDate('not a date')).toBeNull();
  });
});

describe('relativeAge (DWB-551)', () => {
  const now = Date.parse('2026-09-15T20:00:00Z');
  const ago = (ms) => new Date(now - ms).toISOString().replace('Z', '');

  it('renders minutes, hours and days against the injected clock', () => {
    expect(relativeAge(ago(30 * 1000), now)).toBe('just now');
    expect(relativeAge(ago(5 * 60000), now)).toBe('5m ago');
    expect(relativeAge(ago(59 * 60000), now)).toBe('59m ago');
    expect(relativeAge(ago(3 * 3600000), now)).toBe('3h ago');
    expect(relativeAge(ago(23 * 3600000), now)).toBe('23h ago');
    expect(relativeAge(ago(50 * 3600000), now)).toBe('2d ago');
  });

  it('treats a future timestamp as just now and empty input as an empty string', () => {
    expect(relativeAge(ago(-60000), now)).toBe('just now');
    expect(relativeAge(null, now)).toBe('');
    expect(relativeAge('nonsense', now)).toBe('');
  });
});

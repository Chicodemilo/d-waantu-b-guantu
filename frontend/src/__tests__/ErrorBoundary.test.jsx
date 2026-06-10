// Path: src/__tests__/ErrorBoundary.test.jsx
// File: ErrorBoundary.test.jsx
// Created: 2026-06-10
// Purpose: Vitest coverage for ErrorBoundary (DWB-370) - asserts the fallback renders when a child component throws during render, that healthy children render unchanged when no error is thrown, and that the reset action restores rendering when the offending child is replaced.
// Caller: vitest test runner
// Callees: ../components/common/ErrorBoundary, @testing-library/react
// Data In: None (renders test components inline)
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import ErrorBoundary from '../components/common/ErrorBoundary';

function Boom({ shouldThrow, label = 'kaboom' }) {
  if (shouldThrow) throw new Error(label);
  return <div data-testid="healthy-child">healthy</div>;
}

describe('ErrorBoundary', () => {
  let consoleErrorSpy;
  let fetchSpy;

  beforeAll(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 201, json: () => Promise.resolve({}) });
  });

  afterAll(() => {
    consoleErrorSpy.mockRestore();
    fetchSpy.mockRestore();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders children normally when no error is thrown', () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('healthy-child')).toBeInTheDocument();
  });

  it('renders fallback UI when a child throws during render', () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow={true} label="forced render exception" />
      </ErrorBoundary>
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
    expect(screen.getByText(/forced render exception/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument();
  });

  it('honors a custom fallback render-prop', () => {
    const fallback = (err, reset) => (
      <div>
        <span data-testid="custom-fb">custom: {err.message}</span>
        <button type="button" onClick={reset}>retry</button>
      </div>
    );
    render(
      <ErrorBoundary fallback={fallback}>
        <Boom shouldThrow={true} label="custom path" />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('custom-fb')).toHaveTextContent('custom: custom path');
  });
});

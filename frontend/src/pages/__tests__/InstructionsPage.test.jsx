// Path: src/pages/__tests__/InstructionsPage.test.jsx
// File: InstructionsPage.test.jsx
// Created: 2026-09-16
// Purpose: Shape guard for the Code Standards block (DWB-573). The page used to
//          read `template || header_template || JSON.stringify(response)`, and
//          since GET /api/status/code-standards has only ever returned
//          {header_format: {fields, template, placement}}, both named reads
//          missed and the page printed the raw response to a human. That failed
//          SILENTLY and looked deliberate. These tests pin the contract three
//          ways so the next shape move is loud: the template renders from its
//          real path, a raw JSON dump never renders under any response, and a
//          moved key produces a visible error state instead of plausible output.
// Caller: vitest test runner
// Callees: ../InstructionsPage (component + codeHeaderTemplate), ../../api/instructions (mocked), ../../api/status (mocked), ../../services/logger (mocked)
// Data In: Mocked getCodeStandards / syncCheck / getPlaybooks responses
// Data Out: Test assertions
// Last Modified: 2026-09-16

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';

vi.mock('../../api/instructions', () => ({
  syncCheck: vi.fn(),
  syncInstructions: vi.fn(),
  getPlaybooks: vi.fn(),
}));

vi.mock('../../api/status', () => ({
  getCodeStandards: vi.fn(),
}));

vi.mock('../../services/logger', () => ({
  log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

vi.mock('../../components/instructions/InstructionList', () => ({
  default: () => null,
}));

import InstructionsPage, { codeHeaderTemplate } from '../InstructionsPage';
import { syncCheck, getPlaybooks } from '../../api/instructions';
import { getCodeStandards } from '../../api/status';
import { log } from '../../services/logger';

// The live response, trimmed. `template` sits INSIDE header_format; that nesting
// is the whole point of this file, so the fixture must keep it.
const LIVE_SHAPE = {
  header_format: {
    fields: [{ name: 'Path', description: 'Relative path to file', example: 'app/services/sprint.py' }],
    template: '# Path: relative/path/to/file.py\n# File: filename.py\n# Created: YYYY-MM-DD',
    placement: 'First comment block after imports',
  },
};

beforeEach(() => {
  syncCheck.mockReset();
  getPlaybooks.mockReset();
  getCodeStandards.mockReset();
  log.error.mockReset();
  syncCheck.mockResolvedValue({ unsynced_count: 0 });
  getPlaybooks.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

describe('codeHeaderTemplate (shape reader)', () => {
  it('reads the template from header_format.template', () => {
    expect(codeHeaderTemplate(LIVE_SHAPE)).toBe(LIVE_SHAPE.header_format.template);
  });

  it('returns null rather than a guess when the shape moves', () => {
    // Each of these is a plausible drift. None may silently produce output.
    expect(codeHeaderTemplate(null)).toBeNull();
    expect(codeHeaderTemplate({})).toBeNull();
    expect(codeHeaderTemplate({ header_format: {} })).toBeNull();
    // The two keys the old chain guessed at. They have never existed on this
    // endpoint, and reading them must not resurrect the silent path.
    expect(codeHeaderTemplate({ template: 'top-level' })).toBeNull();
    expect(codeHeaderTemplate({ header_template: 'top-level' })).toBeNull();
    // Present but useless values are misses, not content.
    expect(codeHeaderTemplate({ header_format: { template: '   ' } })).toBeNull();
    expect(codeHeaderTemplate({ header_format: { template: 42 } })).toBeNull();
  });
});

describe('InstructionsPage Code Standards block (DWB-573)', () => {
  it('renders the header template text once expanded', async () => {
    getCodeStandards.mockResolvedValue(LIVE_SHAPE);
    render(<InstructionsPage />);

    fireEvent.click(await screen.findByText('File Header Template'));

    const pre = await screen.findByText(/# Path: relative\/path\/to\/file\.py/);
    expect(pre).toBeInTheDocument();
    expect(pre.className).toContain('code-standards__template');
    expect(log.error).not.toHaveBeenCalled();
  });

  it('never renders the raw response as JSON, whatever shape arrives', async () => {
    // The exact regression: a response the named reads miss must not be dumped.
    getCodeStandards.mockResolvedValue(LIVE_SHAPE);
    const { container } = render(<InstructionsPage />);

    fireEvent.click(await screen.findByText('File Header Template'));
    await screen.findByText(/# Path: relative/);

    // A JSON dump of this fixture would carry the quoted key and the brace.
    expect(container.textContent).not.toContain('"header_format"');
    expect(container.textContent).not.toContain('"placement"');
  });

  it('shows a visible error state, not plausible output, when the key moves', async () => {
    // Simulates the shape moving under us: header_format present, template gone.
    getCodeStandards.mockResolvedValue({ header_format: { fields: [], placement: 'x' } });
    const { container } = render(<InstructionsPage />);

    const missing = await screen.findByText(/Code standards unavailable/);
    expect(missing).toBeInTheDocument();
    expect(missing.className).toContain('code-standards__missing');
    // The failure is not hidden behind the expander.
    expect(screen.queryByText('File Header Template')).not.toBeInTheDocument();
    // And it is still not a JSON dump.
    expect(container.textContent).not.toContain('"placement"');
  });

  it('reports shape drift to the telemetry feed so the team sees it too', async () => {
    getCodeStandards.mockResolvedValue({ unexpected: true });
    render(<InstructionsPage />);

    await waitFor(() => expect(log.error).toHaveBeenCalled());
    const [category, message, context] = log.error.mock.calls[0];
    expect(category).toBe('shape');
    expect(message).toMatch(/header_format\.template/);
    expect(context.keys).toEqual(['unexpected']);
  });
});

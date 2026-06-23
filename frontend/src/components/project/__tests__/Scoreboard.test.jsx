// Path: src/components/project/__tests__/Scoreboard.test.jsx
// File: Scoreboard.test.jsx
// Created: 2026-06-23
// Purpose: Tests for the per-project Scoreboard leaderboard (DWB-433) + inline carrot/stick controls (DWB-434). Covers rank rendering (API rank field + position fall-back), tier label mapping, signed sprint delta, per-row link to the agent ledger, top/bottom accent classes, the empty + loading states, and the carrot/stick button -> inline confirm -> award flow including the inline error path.
// Caller: vitest test runner
// Callees: ../Scoreboard, ../../../api/scores (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked getProjectScores + awardScore responses
// Data Out: Test assertions
// Last Modified: 2026-06-23

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../api/scores', () => ({
  getProjectScores: vi.fn(),
  awardScore: vi.fn(),
}));

import Scoreboard from '../Scoreboard';
import { getProjectScores, awardScore } from '../../../api/scores';

function renderBoard(projectId = 1) {
  return render(
    <MemoryRouter>
      <Scoreboard projectId={projectId} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  getProjectScores.mockReset();
  awardScore.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('Scoreboard (DWB-433)', () => {
  it('renders ranked rows with name, rep, signed delta, influence and links to the ledger', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 21, agent_name: 'Barry', agent_role: 'backend-worker', reputation: 35, sprint_delta: 35, influence: 20, rank: 1, tier: 'best' },
      { agent_id: 19, agent_name: 'Freddie', agent_role: 'frontend-worker', reputation: 6, sprint_delta: -2, influence: 18, rank: 2, tier: 'mid' },
    ]);
    renderBoard(1);

    const barry = await screen.findByText('Barry');
    expect(barry).toBeInTheDocument();
    expect(screen.getByText('+35')).toBeInTheDocument();
    expect(screen.getByText('-2')).toBeInTheDocument();
    expect(screen.getByText('TOP')).toBeInTheDocument();
    expect(screen.getByText('MID')).toBeInTheDocument();
    // name links to the agent ledger
    const link = barry.closest('a');
    expect(link).toHaveAttribute('href', '/projects/1/agents/21');
  });

  it('falls back to row position for rank when the API omits the rank field', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 7, agent_name: 'Alpha', agent_role: 'tester', reputation: 10, sprint_delta: 0, influence: 20 },
      { agent_id: 8, agent_name: 'Beta', agent_role: 'tester', reputation: 5, sprint_delta: 0, influence: 20 },
    ]);
    renderBoard(1);

    await screen.findByText('Alpha');
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('applies top and bottom accent classes to the first and last rows', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 1, agent_name: 'First', agent_role: 'tester', reputation: 9, sprint_delta: 0, influence: 20 },
      { agent_id: 2, agent_name: 'Middle', agent_role: 'tester', reputation: 5, sprint_delta: 0, influence: 20 },
      { agent_id: 3, agent_name: 'Last', agent_role: 'tester', reputation: 1, sprint_delta: 0, influence: 20 },
    ]);
    renderBoard(1);

    const firstRow = (await screen.findByText('First')).closest('.scoreboard__row');
    const lastRow = screen.getByText('Last').closest('.scoreboard__row');
    const middleRow = screen.getByText('Middle').closest('.scoreboard__row');
    expect(firstRow.className).toContain('scoreboard__row--top');
    expect(lastRow.className).toContain('scoreboard__row--bottom');
    expect(middleRow.className).not.toContain('scoreboard__row--top');
    expect(middleRow.className).not.toContain('scoreboard__row--bottom');
  });

  it('renders an empty state when there are no scores', async () => {
    getProjectScores.mockResolvedValue([]);
    renderBoard(1);
    await waitFor(() => expect(screen.getByText('No scores yet')).toBeInTheDocument());
  });
});

describe('Scoreboard carrot/stick (DWB-434)', () => {
  it('carrot button -> inline confirm -> award posts +10 and refreshes', async () => {
    getProjectScores
      .mockResolvedValueOnce([
        { agent_id: 19, agent_name: 'Freddie', agent_role: 'frontend-worker', reputation: 6, sprint_delta: 6, influence: 20 },
      ])
      .mockResolvedValueOnce([
        { agent_id: 19, agent_name: 'Freddie', agent_role: 'frontend-worker', reputation: 16, sprint_delta: 16, influence: 20 },
      ]);
    awardScore.mockResolvedValue({ status: 'ok', reputation: 16, sprint_delta: 16 });
    renderBoard(1);

    fireEvent.click(await screen.findByText('carrot +10'));
    // inline confirm appears
    const reasonInput = screen.getByPlaceholderText('reason (optional)');
    fireEvent.change(reasonInput, { target: { value: 'great work' } });
    fireEvent.click(screen.getByText('confirm'));

    await waitFor(() => expect(awardScore).toHaveBeenCalledWith(1, {
      agent: 'Freddie', delta: 10, reason: 'great work',
    }));
    // refreshed leaderboard reflects new reputation
    await waitFor(() => expect(screen.getByText('16')).toBeInTheDocument());
    // confirm strip closed
    expect(screen.queryByPlaceholderText('reason (optional)')).not.toBeInTheDocument();
  });

  it('stick button sends -10', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', agent_role: 'frontend-worker', reputation: 6, sprint_delta: 6, influence: 20 },
    ]);
    awardScore.mockResolvedValue({ status: 'ok', reputation: 1, sprint_delta: 1 });
    renderBoard(1);

    fireEvent.click(await screen.findByText('stick -10'));
    fireEvent.click(screen.getByText('confirm'));

    await waitFor(() => expect(awardScore).toHaveBeenCalledWith(1, {
      agent: 'Freddie', delta: -10, reason: '',
    }));
  });

  it('shows the API error detail inline when the award fails', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', agent_role: 'frontend-worker', reputation: 6, sprint_delta: 6, influence: 20 },
    ]);
    awardScore.mockRejectedValue(Object.assign(new Error("Agent 'Freddie' is not on project DWB"), { status: 404 }));
    renderBoard(1);

    fireEvent.click(await screen.findByText('carrot +10'));
    fireEvent.click(screen.getByText('confirm'));

    await waitFor(() => expect(screen.getByText("Agent 'Freddie' is not on project DWB")).toBeInTheDocument());
    // strip stays open so the user can retry or cancel
    expect(screen.getByPlaceholderText('reason (optional)')).toBeInTheDocument();
  });

  it('cancel closes the confirm strip without awarding', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', agent_role: 'frontend-worker', reputation: 6, sprint_delta: 6, influence: 20 },
    ]);
    renderBoard(1);

    fireEvent.click(await screen.findByText('carrot +10'));
    expect(screen.getByPlaceholderText('reason (optional)')).toBeInTheDocument();
    fireEvent.click(screen.getByText('cancel'));
    expect(screen.queryByPlaceholderText('reason (optional)')).not.toBeInTheDocument();
    expect(awardScore).not.toHaveBeenCalled();
  });
});

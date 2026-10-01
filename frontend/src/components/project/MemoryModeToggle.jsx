// Path: src/components/project/MemoryModeToggle.jsx
// File: MemoryModeToggle.jsx
// Created: 2026-09-29
// Purpose: DWB-588 + DWB-597 Tools-panel control for the per-project memory_mode. Starts a transition (stock to adopting, human_memory to reverting) or aborts one in flight, attempts the start unconfirmed so the API supplies the warning, and swaps the trigger's own text to an inline confirm - never a modal.
// Caller: src/pages/ProjectPage.jsx
// Callees: react (useState), ../../api/projects (updateProject)
// Data In: project (the ProjectRead row, for memory_mode + memory_schema_version)
// Data Out: Default export MemoryModeToggle component; PATCHes /api/projects/:id
// Last Modified: 2026-09-30 (DWB-597: start or abort a transition; report a start that completed immediately)

import { useState } from 'react';
import { updateProject } from '../../api/projects';

const MODES = {
  stock: 'stock',
  human_memory: 'human_memory',
  adopting: 'adopting',
  reverting: 'reverting',
};

// DWB-597: what this control STARTS, per project state. It is deliberately a
// lookup rather than a ternary, mirroring the backend's own edge map
// (services/project.LEGAL_MEMORY_MODE_EDGES) so an unlisted state offers
// nothing instead of guessing.
//
// The direct stock -> human_memory flip this component used to perform is now
// an illegal edge (DWB-593): it sealed the flat file against an empty store and
// every agent on the project spawned amnesiac until someone flipped it back.
// The only route in is through a transition, which moves entries across while
// stock stays authoritative.
//
// adopting and reverting are absent ON PURPOSE. There is no legal move that
// STARTS something from inside a transition, so a control offered there could
// only ever produce a refusal. Aborting a transition is a legal edge and a real
// need, but no ticket owns that control yet, so this does not invent one.
const STARTS = {
  [MODES.stock]: { target: MODES.adopting, label: 'adopt human_memory' },
  [MODES.human_memory]: { target: MODES.reverting, label: 'revert to stock' },
};

// The way OUT of a transition, back to wherever it came from. These edges were
// always legal in the backend's map and nothing in the UI reached them, so an
// operator who started an adoption and changed their mind needed an agent or a
// curl to escape. A rule that exists only in code is not a rule anyone can use.
//
// Both edges verified against the running API before this was written: each
// returns 200 and NEITHER takes a confirmation flag, because the server does
// not treat an abort as the consequential act. Do not send one; there is no
// warning to render and a flag the server ignores is cargo cult.
const ABORTS = {
  [MODES.adopting]: MODES.stock,
  [MODES.reverting]: MODES.human_memory,
};

// The warning copy deliberately does NOT live here. It is a module constant in
// the backend (services/project.MEMORY_MODE_SWITCH_WARNING) and this component
// renders whatever the refusal hands back, so there is no second copy to drift.
// The only presentation applied is the lead paragraph's weight, which the spec
// renders as bold.
function warningParagraphs(text) {
  return String(text || '')
    .split('\n\n')
    .map((p) => p.trim())
    .filter(Boolean);
}

function MemoryModeToggle({ project }) {
  const [warning, setWarning] = useState(null);
  const [pending, setPending] = useState(null);
  const [aborting, setAborting] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);

  const mode = project.memory_mode || MODES.stock;
  const start = STARTS[mode] || null;
  const target = start ? start.target : null;
  const abortTo = ABORTS[mode] || null;

  const reset = () => {
    setWarning(null);
    setPending(null);
    setAborting(false);
    setFailure(null);
    setOutcome(null);
  };

  // First click: ask for the switch WITHOUT confirmation, on purpose. The API
  // refuses it and the refusal carries the warning, so the words the reader
  // sees are the server's own rather than a copy kept here.
  const handleRequest = async () => {
    if (!target) return;
    setBusy(true);
    setFailure(null);
    try {
      await updateProject(project.id, { memory_mode: target });
      // A switch that goes through unconfirmed means the guard is gone. Say so
      // rather than rendering a success that hides it.
      reset();
      setFailure(
        'The transition started without asking for confirmation. The guard is not working; tell the team lead.'
      );
    } catch (err) {
      if (err.status === 400 && err.message) {
        setWarning(err.message);
        setPending(target);
      } else {
        setFailure(err.message || 'Could not reach the API.');
      }
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async () => {
    setBusy(true);
    try {
      const updated = await updateProject(project.id, {
        memory_mode: pending,
        memory_mode_confirmed: true,
      });
      reset();
      // READ THE MODE OFF THE RESPONSE RATHER THAN ASSUMING IT ECHOES THE
      // REQUEST. Enumeration runs inside this request, so a project where every
      // memory file is empty produces zero candidates and lands DIRECTLY in the
      // destination: we ask for `adopting` and get back `human_memory`. That is
      // success, not an error, and there is no transition to watch.
      //
      // Saying so matters because the alternative is silence: the mode changes,
      // no status strip ever appears, and the operator is left wondering
      // whether the thing they just confirmed actually ran.
      if (updated && updated.memory_mode && updated.memory_mode !== pending) {
        setOutcome(
          `Nothing to move, so the project is already in ${updated.memory_mode}. ` +
          'Every agent memory was empty, so there was no entry to migrate.'
        );
      }
    } catch (err) {
      setFailure(err.message || 'The transition was refused.');
    } finally {
      setBusy(false);
    }
  };

  // The abort ask is OURS, not the server's. The API needs no confirmation
  // here, so there is no warning to render and nothing would otherwise stand
  // between a misclick and discarding migration work already done. It stays
  // one inline line: an escape hatch that is tedious to use is one people
  // route around.
  const handleAbortAsk = () => {
    setFailure(null);
    setAborting(true);
  };

  const handleAbortConfirm = async () => {
    if (!abortTo) return;
    setBusy(true);
    try {
      await updateProject(project.id, { memory_mode: abortTo });
      reset();
    } catch (err) {
      setFailure(err.message || 'The abort was refused.');
    } finally {
      setBusy(false);
    }
  };

  const paragraphs = warningParagraphs(warning);

  return (
    <div className="project-tools__section">
      <div className="project-tools__section-title">Memory Mode</div>
      <div className="project-tools__row">
        <span className="memory-mode__current">
          Mode [{mode}] schema v{project.memory_schema_version} (beta)
        </span>
      </div>
      <div className="project-tools__row">
        {/* AC3: the confirm text renders inside the trigger's own node. There
            is no dialog and no overlay anywhere in this component. */}
        <span className="memory-mode__trigger" data-testid="memory-mode-trigger">
          {abortTo ? (
            aborting ? (
              <>
                <span className="memory-mode__confirm-text">
                  discard the work done so far?
                </span>
                <button
                  className="sync-btn sync-btn--danger"
                  onClick={handleAbortConfirm}
                  disabled={busy}
                >
                  {busy ? '$ aborting...' : '$ yes'}
                </button>
                <span className="memory-mode__confirm-sep">/</span>
                <button className="sync-btn" onClick={reset} disabled={busy}>
                  $ cancel
                </button>
              </>
            ) : (
              <>
                <span className="memory-mode__in-transition">
                  A transition is running. Nothing else can start until it
                  finishes.
                </span>
                <button
                  className="sync-btn sync-btn--danger"
                  onClick={handleAbortAsk}
                  disabled={busy}
                >
                  $ abort
                </button>
              </>
            )
          ) : !start ? (
            <span className="memory-mode__in-transition">
              This project is in a state with nothing to start.
            </span>
          ) : pending ? (
            <>
              <span className="memory-mode__confirm-text">confirm?</span>
              <button
                className="sync-btn"
                onClick={handleConfirm}
                disabled={busy}
              >
                {busy ? '$ switching...' : '$ yes'}
              </button>
              <span className="memory-mode__confirm-sep">/</span>
              <button className="sync-btn" onClick={reset} disabled={busy}>
                $ cancel
              </button>
            </>
          ) : (
            <button className="sync-btn" onClick={handleRequest} disabled={busy}>
              {busy ? '$ checking...' : `$ ${start.label}`}
            </button>
          )}
        </span>
        <span className="tooltip-trigger">
          ?
          <span className="tooltip-content">
            Which memory system this project's agents run on. stock is one
            markdown file per agent with a token ceiling. human_memory is a beta
            mode that stores memory as scored entries across tiers. Moving
            between them rewrites every memory the project has, so it runs as a
            transition that moves entries one at a time, and it asks first.
            Stock memory stays authoritative until the transition completes.
          </span>
        </span>
      </div>
      {paragraphs.length > 0 && (
        <div className="memory-mode__warning">
          {paragraphs.map((p, i) => (
            <p
              key={p}
              className={
                i === 0
                  ? 'memory-mode__warning-line memory-mode__warning-line--lead'
                  : 'memory-mode__warning-line'
              }
            >
              {p}
            </p>
          ))}
        </div>
      )}
      {failure && <div className="memory-mode__failure">{failure}</div>}
      {outcome && <div className="memory-mode__outcome">{outcome}</div>}
      <div className="project-tools__row">
        <span className="memory-mode__note">
          human_memory stays in beta permanently, by design: it keeps the schema
          free to move. Beta here does not mean unfinished work on its way to
          graduating. Separately, this control sets the project's mode only. The
          read path, the write path and enforcement are not built yet, so
          switching does not change how any agent behaves.
        </span>
      </div>
    </div>
  );
}

export default MemoryModeToggle;

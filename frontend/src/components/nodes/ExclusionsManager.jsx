// Path: src/components/nodes/ExclusionsManager.jsx
// File: ExclusionsManager.jsx
// Created: 2026-09-15
// Purpose: Contents of the exclusions manager modal (DWB-552). Lists the project's node scan exclusions as repo-relative patterns, each deletable through the project's inline-text confirm (delete -> confirm? yes / cancel) rather than a nested dialog, adds new patterns by free text with the server's own rejection text shown inline, and offers a rescan that starts the pass and closes the modal. Seeded defaults carry no marker and are ordinary rows by design (Miles: defaults are deletable like any other). This renders INSIDE components/common/Overlay, which the page owns; it is not a dialog itself.
// Caller: pages/NodesPage.jsx (as the child of Overlay)
// Callees: react (useState), hooks/useNodeExclusions
// Data In: projectId, onRescan (fn, starts the pass and closes), rescanning (bool), browserSlot (optional React node: the DWB-553 directory browser plugs in here when it exists)
// Data Out: default export ExclusionsManager component
// Last Modified: 2026-09-15

import { useState } from 'react';
import useNodeExclusions from '../../hooks/useNodeExclusions';

function ExclusionRow({ row, onDelete }) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState(null);

  const confirmDelete = async () => {
    const result = await onDelete(row.id);
    if (!result.ok) {
      setError(result.error);
      setConfirming(false);
    }
  };

  return (
    <li className="exclusions__row">
      <code className="exclusions__pattern">{row.pattern}</code>
      {confirming ? (
        <span className="exclusions__confirm">
          confirm?{' '}
          <button type="button" className="exclusions__link exclusions__link--danger" onClick={confirmDelete}>yes</button>
          {' / '}
          <button type="button" className="exclusions__link" onClick={() => setConfirming(false)}>cancel</button>
        </span>
      ) : (
        <button
          type="button"
          className="exclusions__link exclusions__link--danger"
          onClick={() => { setError(null); setConfirming(true); }}
        >
          delete
        </button>
      )}
      {error && <span className="exclusions__row-error">{error}</span>}
    </li>
  );
}

function ExclusionsManager({ projectId, onRescan, rescanning = false, browserSlot = null }) {
  const { rows, loading, error, adding, add, remove } = useNodeExclusions(projectId);
  const [draft, setDraft] = useState('');
  const [addError, setAddError] = useState(null);

  const submitAdd = async (e) => {
    if (e) e.preventDefault();
    const result = await add(draft);
    if (result.ok) {
      setDraft('');
      setAddError(null);
    } else {
      setAddError(result.error);
    }
  };

  return (
    <div className="exclusions" data-testid="exclusions-manager">
      <div className="exclusions__intro">
        paths the node scan skips, repo-relative. a directory prefix ends with a slash
        (<code className="exclusions__pattern">backend/tests/</code>); a bare name or glob matches
        anywhere (<code className="exclusions__pattern">conftest.py</code>).
      </div>

      <div className="exclusions__section-title">
        current exclusions
        {!loading && !error && <span className="exclusions__count">{rows.length}</span>}
      </div>

      {loading && <div className="exclusions__empty">loading exclusions...</div>}
      {error && <div className="exclusions__error">could not load exclusions: {error.message || 'unknown error'}</div>}
      {!loading && !error && rows.length === 0 && (
        <div className="exclusions__empty">nothing excluded: the scan reads the whole repo.</div>
      )}
      {rows.length > 0 && (
        <ul className="exclusions__list">
          {rows.map((row) => (
            <ExclusionRow key={row.id} row={row} onDelete={remove} />
          ))}
        </ul>
      )}

      <div className="exclusions__section-title">add an exclusion</div>
      <form className="exclusions__add" onSubmit={submitAdd}>
        <label className="exclusions__add-label">
          <span className="exclusions__add-prompt">path or glob</span>
          <input
            type="text"
            className="exclusions__input"
            value={draft}
            placeholder="docs/vendor/ or *.snap"
            aria-label="path or glob"
            onChange={(e) => { setDraft(e.target.value); setAddError(null); }}
          />
        </label>
        <button type="submit" className="exclusions__add-btn" disabled={adding || draft.trim() === ''}>
          {adding ? 'adding...' : 'add'}
        </button>
      </form>
      {addError && <div className="exclusions__error" role="alert">{addError}</div>}

      {/* DWB-553 directory browser plugs in here as a whole component. Absent until
          it lands: a guessed stub would be worse than nothing. */}
      {browserSlot}

      <div className="exclusions__foot">
        <button
          type="button"
          className="exclusions__rescan"
          onClick={onRescan}
          disabled={rescanning}
        >
          {rescanning ? 'rescanning...' : 'rescan now'}
        </button>
        <span className="exclusions__foot-note">
          rebuilds the index with these exclusions and closes this panel.
        </span>
      </div>
    </div>
  );
}

export default ExclusionsManager;

// Path: src/components/nodes/DirectoryBrowser.jsx
// File: DirectoryBrowser.jsx
// Created: 2026-09-15
// Purpose: Directory picker for the exclusions modal (DWB-552, over Stan's DWB-553 endpoint). Browses the repo one level at a time from the root, showing a breadcrumb built from the parent the server echoes back, and offers "exclude" beside each directory. A directory path is a plain path, not a glob, so excluding one appends a trailing slash to match the subtree rather than a file of that exact name. Paths are repo-relative throughout, which is what pointer refs are, so what the user picks is what the scan matches.
// Caller: components/nodes/ExclusionsManager.jsx (passed in as its browserSlot)
// Callees: react (useState), hooks/useRepoDirectories
// Data In: projectId, onExclude (fn(pattern) -> {ok, error}), excluded (Set of existing patterns)
// Data Out: default export DirectoryBrowser component
// Last Modified: 2026-09-15

import { useState } from 'react';
import useRepoDirectories from '../../hooks/useRepoDirectories';

// A directory pattern excludes the subtree, so it carries a trailing slash.
export function directoryPattern(path) {
  const trimmed = (path || '').trim().replace(/\/+$/, '');
  return trimmed === '' ? '' : `${trimmed}/`;
}

function DirectoryBrowser({ projectId, onExclude, excluded }) {
  const { parent, directories, crumbs, loading, error, open, up, goTo } = useRepoDirectories(projectId);
  const [busyPath, setBusyPath] = useState(null);
  const [excludeError, setExcludeError] = useState(null);

  const exclude = async (path) => {
    const pattern = directoryPattern(path);
    setBusyPath(path);
    setExcludeError(null);
    const result = await onExclude(pattern);
    if (!result?.ok) setExcludeError(result?.error || 'could not add exclusion');
    setBusyPath(null);
  };

  const isExcluded = (path) => excluded instanceof Set && excluded.has(directoryPattern(path));

  return (
    <div className="dir-browser" data-testid="dir-browser">
      <div className="exclusions__section-title">browse the repo</div>

      <div className="dir-browser__crumbs">
        <button type="button" className="exclusions__link" onClick={() => goTo('')}>repo root</button>
        {crumbs.map((c) => (
          <span key={c.path} className="dir-browser__crumb">
            <span className="dir-browser__crumb-sep">/</span>
            <button type="button" className="exclusions__link" onClick={() => goTo(c.path)}>{c.name}</button>
          </span>
        ))}
        {parent !== '' && (
          <button type="button" className="exclusions__link dir-browser__up" onClick={up}>up</button>
        )}
      </div>

      {error && (
        <div className="exclusions__error">could not list directories: {error.message || 'unknown error'}</div>
      )}
      {loading && <div className="exclusions__empty">loading directories...</div>}
      {!loading && directories.length === 0 && !error && (
        <div className="exclusions__empty">no subdirectories here.</div>
      )}

      {directories.length > 0 && (
        <ul className="dir-browser__list">
          {directories.map((dir) => (
            <li key={dir.path} className="dir-browser__row">
              <button
                type="button"
                className="dir-browser__name"
                onClick={() => open(dir.path)}
                title={`open ${dir.path}`}
              >
                {dir.name}/
              </button>
              {isExcluded(dir.path) ? (
                <span className="dir-browser__already">excluded</span>
              ) : (
                <button
                  type="button"
                  className="exclusions__link"
                  disabled={busyPath === dir.path}
                  onClick={() => exclude(dir.path)}
                >
                  {busyPath === dir.path ? 'adding...' : 'exclude'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {excludeError && <div className="exclusions__error" role="alert">{excludeError}</div>}
    </div>
  );
}

export default DirectoryBrowser;

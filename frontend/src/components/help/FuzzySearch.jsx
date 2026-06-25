// Path: src/components/help/FuzzySearch.jsx
// File: FuzzySearch.jsx
// Created: 2026-06-25
// Purpose: Generic controlled search input (DWB-468). Pure presentational text box
//          for live filtering; the parent owns the query string and runs the
//          useFuzzyFilter hook. Optional result-count hint and clear affordance.
//          No icons, no external dependency.
// Caller: pages/HelpPage.jsx (and any page needing live fuzzy filtering)
// Callees: none (controlled by parent via value/onChange)
// Data In: value (string), onChange (fn), placeholder (string), resultCount (number|null),
//          totalCount (number|null), label (string)
// Data Out: default export FuzzySearch component; fires onChange(nextValue)
// Last Modified: 2026-06-25

import '../../styles/help.css';

function FuzzySearch({
  value,
  onChange,
  placeholder = 'filter...',
  resultCount = null,
  totalCount = null,
  label = 'search',
}) {
  const query = value || '';
  const showCount = query.trim() !== '' && resultCount !== null;

  return (
    <div className="fuzzy-search">
      <label className="fuzzy-search__label">
        <span className="fuzzy-search__prompt">{label}</span>
        <input
          type="text"
          className="fuzzy-search__input"
          value={query}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          aria-label={label}
        />
      </label>
      {query !== '' && (
        <button
          type="button"
          className="fuzzy-search__clear"
          onClick={() => onChange('')}
        >
          clear
        </button>
      )}
      {showCount && (
        <span className="fuzzy-search__count">
          {resultCount}
          {totalCount !== null ? ` / ${totalCount}` : ''} match
          {resultCount === 1 ? '' : 'es'}
        </span>
      )}
    </div>
  );
}

export default FuzzySearch;

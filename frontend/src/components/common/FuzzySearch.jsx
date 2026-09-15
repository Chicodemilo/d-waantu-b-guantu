// Path: src/components/common/FuzzySearch.jsx
// File: FuzzySearch.jsx
// Created: 2026-06-25
// Purpose: Generic controlled search input (DWB-468). Pure presentational text box
//          for live filtering; the parent owns the query string and decides what
//          to do with it (useFuzzyFilter, a debounced API match, ...). Optional
//          result-count hint, clear affordance, and onEscape (Esc inside the box).
//          Moved from components/help to components/common in DWB-536 once it was
//          used by help, sessions, and nodes. No icons, no external dependency.
// Caller: pages/HelpPage.jsx, components/project/SessionsTable.jsx, pages/NodesPage.jsx
// Callees: none (controlled by parent via value/onChange)
// Data In: value (string), onChange (fn), placeholder (string), resultCount (number|null),
//          totalCount (number|null), label (string), onEscape (fn|undefined)
// Data Out: default export FuzzySearch component; fires onChange(nextValue), onEscape()
// Last Modified: 2026-09-15 (DWB-536)


function FuzzySearch({
  value,
  onChange,
  placeholder = 'filter...',
  resultCount = null,
  totalCount = null,
  label = 'search',
  onEscape,
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
          onKeyDown={(e) => {
            if (e.key === 'Escape' && onEscape) {
              e.preventDefault();
              onEscape();
            }
          }}
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

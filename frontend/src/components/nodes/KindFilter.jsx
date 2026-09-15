// Path: src/components/nodes/KindFilter.jsx
// File: KindFilter.jsx
// Created: 2026-09-15
// Purpose: Row of plain-text toggle buttons, one per pointer kind present in the loaded node set (DWB-542): code, docs, memory, plus any other kind under its own name. Selected state is aria-pressed with a visible style; each button shows the count of nodes carrying that kind. Presentational: the page owns the selected set and the filtering.
// Caller: pages/NodesPage.jsx
// Callees: none (controlled via props)
// Data In: kinds ([{kind, label, count}]), selected (Set<string>|null; null = all), onToggle(kind), onSelectAll()
// Data Out: default export KindFilter component
// Last Modified: 2026-09-15

function KindFilter({ kinds, selected, onToggle, onSelectAll }) {
  if (!kinds || kinds.length === 0) return null;
  const isOn = (kind) => selected == null || selected.has(kind);
  const allOn = kinds.every((k) => isOn(k.kind));

  return (
    <div className="kind-filter" data-testid="kind-filter">
      <span className="kind-filter__label">kinds</span>
      {kinds.map(({ kind, label, count }) => (
        <button
          key={kind}
          type="button"
          className={`kind-filter__toggle${isOn(kind) ? ' kind-filter__toggle--on' : ''}`}
          aria-pressed={isOn(kind)}
          onClick={() => onToggle(kind)}
        >
          {label}
          <span className="kind-filter__count">{count}</span>
        </button>
      ))}
      {!allOn && (
        <button type="button" className="kind-filter__all" onClick={onSelectAll}>
          select all
        </button>
      )}
    </div>
  );
}

export default KindFilter;

// Path: src/components/common/DataTable.jsx
// File: DataTable.jsx
// Created: 2026-03-29
// Purpose: Reusable sortable data table with column definitions, click-to-sort headers, and optional row click handler
// Caller: None currently (available for use)
// Callees: react (useState), common.css
// Data In: props { columns[], data[], onRowClick }
// Data Out: default export DataTable component
// Last Modified: 2026-03-29

import { useState } from 'react';
import '../../styles/common.css';

function DataTable({ columns, data, onRowClick }) {
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sorted = [...data].sort((a, b) => {
    if (!sortKey) return 0;
    const aVal = a[sortKey];
    const bVal = b[sortKey];
    if (aVal == null) return 1;
    if (bVal == null) return -1;
    if (typeof aVal === 'string') {
      return sortDir === 'asc'
        ? aVal.localeCompare(bVal)
        : bVal.localeCompare(aVal);
    }
    return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
  });

  return (
    <table className="data-table">
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col.key}
              className={sortKey === col.key ? 'th--sorted' : ''}
              onClick={() => handleSort(col.key)}
            >
              {col.label}
              {sortKey === col.key && (sortDir === 'asc' ? ' ^' : ' v')}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((row, i) => (
          <tr
            key={row.id || i}
            onClick={() => onRowClick?.(row)}
            className={onRowClick ? 'data-table__row--clickable' : ''}
          >
            {columns.map((col) => (
              <td key={col.key}>
                {col.render ? col.render(row[col.key], row) : row[col.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default DataTable;

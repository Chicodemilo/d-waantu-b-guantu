// Path: src/components/project/SessionResultCard.jsx
// File: SessionResultCard.jsx
// Created: 2026-06-25
// Purpose: One result card for the DWBG-012 cross-project Session Recall page. Renders a
//          slim search row (DWBG-011 contract: id, project_id, headline, opened_at,
//          closed_at, total_tokens, snippet, keywords[]) as a clickable card. Header
//          carries the headline + a meta line (project label, opened date, total tokens);
//          the matched snippet sits below, then the keyword chips. Keyword chips reuse the
//          SessionSummary keyword-tag styling (.session-summary__tag) so chips look the same
//          across the detail page and recall results. Clicking the card navigates to the
//          per-session detail page (/projects/:pid/sessions/:sid). Null-guards every field
//          so a partial/legacy row still renders.
// Caller: pages/SessionRecallPage.jsx
// Callees: react-router-dom (Link), styles/sessions.css
// Data In: row ({ id, project_id, headline, opened_at, closed_at, total_tokens, snippet, keywords }), projectLabel (string), recallSearch (the Recall page's current URL query string, e.g. "?q=...&project_id=...")
// Data Out: default export SessionResultCard component
// Last Modified: 2026-06-25 (DWBG-023: pass recall source + query string in router state for source-aware back-nav)

import { Link } from 'react-router-dom';
import '../../styles/sessions.css';

function formatTokens(n) {
  const v = Number(n) || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

function parseUtc(iso) {
  if (!iso) return null;
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d;
}

function formatDate(iso) {
  const d = parseUtc(iso);
  if (!d) return '-';
  return d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}

function SessionResultCard({ row, projectLabel, recallSearch }) {
  if (!row || row.id == null) return null;

  const headline = row.headline || `Session #${row.id}`;
  const tags = (Array.isArray(row.keywords) ? row.keywords : [])
    .filter((k) => k && k.keyword)
    .slice()
    .sort((a, b) => (Number(b.weight) || 0) - (Number(a.weight) || 0));

  const label = projectLabel || (row.project_id != null ? `project ${row.project_id}` : '-');

  return (
    <Link
      to={`/projects/${row.project_id}/sessions/${row.id}`}
      // DWBG-023: mark the navigation source so the detail page can show a
      // "back to search" affordance that returns to this exact query + facets.
      // Only the recall path sets this; the per-project sessions list does not.
      state={{ from: 'recall', recallSearch: recallSearch || '' }}
      className="session-result"
      data-testid="session-result-card"
    >
      <div className="session-result__head">
        <span className="session-result__headline">{headline}</span>
        <span className="session-result__id">#{row.id}</span>
      </div>

      <div className="session-result__meta">
        <span className="session-result__project" data-testid="session-result-project">
          {label}
        </span>
        <span className="session-result__sep">·</span>
        <span className="session-result__date">{formatDate(row.opened_at)}</span>
        <span className="session-result__sep">·</span>
        <span className="session-result__tokens">{formatTokens(row.total_tokens)} tokens</span>
      </div>

      {row.snippet && (
        <p className="session-result__snippet" data-testid="session-result-snippet">
          {row.snippet}
        </p>
      )}

      {tags.length > 0 && (
        <div className="session-summary__keywords session-result__keywords" data-testid="session-result-keywords">
          {tags.map((k, i) => (
            <span
              key={`${k.keyword}-${i}`}
              className="session-summary__tag"
              title={k.weight != null ? `weight ${k.weight}` : undefined}
            >
              {k.keyword}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}

export default SessionResultCard;

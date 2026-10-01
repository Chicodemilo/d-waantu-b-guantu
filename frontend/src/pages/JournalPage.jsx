// Path: src/pages/JournalPage.jsx
// File: JournalPage.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: Journal search view (spec section 5) - tags, date range, term.
//          There is no full-dump button here because there is no full-dump
//          route: GET /journal refuses a request with none of those filters
//          (422), and this page shows that refusal rather than working
//          around it. Every row rendered is a row the backend just
//          incremented retrieval_count on (DWB-587's single write site), so
//          the count shown is a live consequence of running the search, not
//          a stored label.
// Caller: App.jsx (route: /projects/:id/journal)
// Callees: react (useState), react-router-dom (useParams, Link),
//          store/useStore, api/memory (searchJournal)
// Data In: Route param (id), form inputs (tags, term, date range)
// Data Out: Default export JournalPage component
// Last Modified: 2026-09-30 (DWB-613)

import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { searchJournal } from '../api/memory';

function formatTime(iso) {
  if (!iso) return '-';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '-';
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

function JournalPage() {
  const { id } = useParams();
  const project = useStore((s) => s.projects).find((p) => p.id === Number(id));

  const [term, setTerm] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const hasFilter = term.trim() || tagsInput.trim() || dateFrom || dateTo;

  const runSearch = (e) => {
    e.preventDefault();
    if (!hasFilter) {
      setError('the journal is never read whole - enter at least a term, a tag, or a date');
      setResult(null);
      setSearched(true);
      return;
    }
    setSearching(true);
    setError(null);
    searchJournal({
      tags: tagsInput.split(',').filter(Boolean),
      term: term.trim() || undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
    })
      .then((res) => setResult(res))
      .catch((err) => {
        setResult(null);
        setError(err?.data?.detail || err?.message || 'search failed');
      })
      .finally(() => {
        setSearching(false);
        setSearched(true);
      });
  };

  if (!project) {
    return <div className="empty-state" data-testid="journal-page">Project not found</div>;
  }

  return (
    <div className="journal-page" data-testid="journal-page">
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; {project.prefix}</Link>
        <span>Journal</span>
      </div>

      <form className="journal-page__form" onSubmit={runSearch}>
        <input
          className="journal-page__input"
          type="text"
          placeholder="term (substring of an entry)"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <input
          className="journal-page__input"
          type="text"
          placeholder="tags, comma separated"
          value={tagsInput}
          onChange={(e) => setTagsInput(e.target.value)}
        />
        <input
          className="journal-page__input journal-page__input--date"
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          aria-label="date from"
        />
        <input
          className="journal-page__input journal-page__input--date"
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          aria-label="date to"
        />
        <button className="journal-page__submit" type="submit" disabled={searching}>
          {searching ? 'searching...' : 'search'}
        </button>
      </form>

      {error && <div className="journal-page__error" data-testid="journal-error">{error}</div>}

      {!searched ? (
        <div className="empty-state">the journal is never read whole - search by tag, date, or term</div>
      ) : result ? (
        result.entries.length === 0 ? (
          <div className="empty-state" data-testid="journal-empty">no entries matched</div>
        ) : (
          <>
            <div className="journal-page__meta">
              {result.count} of {result.total_matched} matched
              {result.status === 'truncated' && ' (truncated - narrow the search to see the rest)'}
            </div>
            <table className="data-table" data-testid="journal-results">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Tags</th>
                  <th>Retrievals</th>
                  <th>Entry</th>
                </tr>
              </thead>
              <tbody>
                {result.entries.map((entry) => (
                  <tr key={entry.id}>
                    <td>{formatTime(entry.entered_at)}</td>
                    <td>
                      {(entry.tags || []).map((t) => (
                        <span className="journal-page__tag" key={t}>{t}</span>
                      ))}
                    </td>
                    <td>{entry.retrieval_count}</td>
                    <td className="journal-page__body">{entry.body}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )
      ) : null}
    </div>
  );
}

export default JournalPage;

// Path: src/components/jira/JiraSprintBoard.jsx
// File: JiraSprintBoard.jsx
// Created: 2026-05-27
// Purpose: Kanban-style board grouping Jira issues by status category
// Caller: pages/JiraIssuesPage.jsx
// Callees: None
// Data In: issues, baseUrl, onSelect, loading
// Data Out: Default export JiraSprintBoard component

const COLUMNS = [
  { key: 'To Do',       label: 'To Do' },
  { key: 'In Progress', label: 'In Progress' },
  { key: 'Done',        label: 'Done' },
];

function JiraSprintBoard({ issues, loading, baseUrl, onSelect }) {
  if (loading && issues.length === 0) {
    return <div className="empty-state">Loading sprint…</div>;
  }
  if (issues.length === 0) {
    return <div className="empty-state">No issues in the active sprint.</div>;
  }

  const byCategory = { 'To Do': [], 'In Progress': [], 'Done': [] };
  for (const issue of issues) {
    const cat = issue.status_category || 'To Do';
    if (byCategory[cat]) byCategory[cat].push(issue);
    else byCategory['To Do'].push(issue);
  }

  return (
    <div className="jira-board">
      {COLUMNS.map(({ key, label }) => (
        <div key={key} className="jira-board__col">
          <div className="jira-board__col-title">
            {label} <span className="jira-board__count">({byCategory[key].length})</span>
          </div>
          <div className="jira-board__cards">
            {byCategory[key].map((issue) => (
              <div
                key={issue.key}
                className="jira-card"
                onClick={() => onSelect(issue.key)}
              >
                <div className="jira-card__head">
                  <a
                    className="jira-card__key"
                    href={`${baseUrl}/browse/${issue.key}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                  >{issue.key}</a>
                  <span className="jira-card__type">{issue.issue_type}</span>
                </div>
                <div className="jira-card__title">{issue.summary}</div>
                <div className="jira-card__meta">
                  <span className="jira-card__assignee">{issue.assignee || 'Unassigned'}</span>
                  <span className={`jira-status jira-status--${(issue.status_category || 'unknown').toLowerCase().replace(/\s+/g, '-')}`}>
                    {issue.status || '—'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default JiraSprintBoard;

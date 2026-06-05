// Path: src/components/jira/JiraIssueList.jsx
// File: JiraIssueList.jsx
// Created: 2026-05-27
// Purpose: Table view of normalized Jira issues from the /api/jira/search endpoint
// Caller: pages/JiraIssuesPage.jsx
// Callees: None (presentational)
// Data In: issues (array of normalized issue dicts), baseUrl, selectedKey, onSelect, loading
// Data Out: Default export JiraIssueList component

function shortDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 10);
}

function JiraIssueList({ issues, loading, baseUrl, selectedKey, onSelect }) {
  if (loading && issues.length === 0) {
    return <div className="empty-state">Loading…</div>;
  }
  if (issues.length === 0) {
    return <div className="empty-state">No issues match this query.</div>;
  }
  return (
    <div className="jira-issue-list">
      <div className="jira-row jira-row--header">
        <span className="jira-row__key">Key</span>
        <span className="jira-row__type">Type</span>
        <span className="jira-row__parent">Parent</span>
        <span className="jira-row__title">Title</span>
        <span className="jira-row__status">Status</span>
        <span className="jira-row__assignee">Assignee</span>
        <span className="jira-row__updated">Updated</span>
      </div>
      {issues.map((issue) => (
        <div
          key={issue.key}
          className={`jira-row${selectedKey === issue.key ? ' jira-row--selected' : ''}`}
          onClick={() => onSelect(issue.key)}
        >
          <span className="jira-row__key">
            <a
              href={`${baseUrl}/browse/${issue.key}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
            >{issue.key}</a>
          </span>
          <span className="jira-row__type">{issue.issue_type || '—'}</span>
          <span className="jira-row__parent">{issue.parent_key || '—'}</span>
          <span className="jira-row__title">{issue.summary}</span>
          <span className="jira-row__status">
            <span className={`jira-status jira-status--${(issue.status_category || 'unknown').toLowerCase().replace(/\s+/g, '-')}`}>
              {issue.status || '—'}
            </span>
          </span>
          <span className="jira-row__assignee">{issue.assignee || 'Unassigned'}</span>
          <span className="jira-row__updated">{shortDate(issue.updated)}</span>
        </div>
      ))}
    </div>
  );
}

export default JiraIssueList;

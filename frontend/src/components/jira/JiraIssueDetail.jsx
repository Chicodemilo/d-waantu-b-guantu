// Path: src/components/jira/JiraIssueDetail.jsx
// File: JiraIssueDetail.jsx
// Created: 2026-05-27
// Purpose: Side panel rendering the selected Jira issue's metadata
// Caller: pages/JiraIssuesPage.jsx
// Callees: None
// Data In: issue (normalized dict), baseUrl, onClose
// Data Out: Default export JiraIssueDetail component

function fmtIso(iso) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

function JiraIssueDetail({ issue, baseUrl, onClose }) {
  if (!issue) return null;
  return (
    <aside className="jira-detail">
      <div className="jira-detail__head">
        <a
          className="jira-detail__key"
          href={`${baseUrl}/browse/${issue.key}`}
          target="_blank"
          rel="noopener noreferrer"
        >{issue.key} ↗</a>
        <button className="jira-detail__close" onClick={onClose} aria-label="Close detail">
          ×
        </button>
      </div>
      <div className="jira-detail__title">{issue.summary}</div>
      <dl className="jira-detail__list">
        <dt>Type</dt>      <dd>{issue.issue_type || '—'}</dd>
        <dt>Status</dt>    <dd>
          <span className={`jira-status jira-status--${(issue.status_category || 'unknown').toLowerCase().replace(/\s+/g, '-')}`}>
            {issue.status || '—'}
          </span>
        </dd>
        <dt>Assignee</dt>  <dd>{issue.assignee || 'Unassigned'}</dd>
        <dt>Priority</dt>  <dd>{issue.priority || '—'}</dd>
        <dt>Parent</dt>    <dd>{issue.parent_key ? `${issue.parent_key} (${issue.parent_type || 'unknown'})` : '—'}</dd>
        <dt>Created</dt>   <dd>{fmtIso(issue.created)}</dd>
        <dt>Updated</dt>   <dd>{fmtIso(issue.updated)}</dd>
      </dl>
    </aside>
  );
}

export default JiraIssueDetail;

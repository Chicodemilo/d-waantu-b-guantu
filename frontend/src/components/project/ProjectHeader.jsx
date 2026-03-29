import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import StatusBadge from '../common/StatusBadge';
import { getProjectTestRuns } from '../../api/testResults';

function TestStatusIcon({ projectId }) {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getProjectTestRuns(projectId)
      .then((runs) => {
        if (cancelled || runs.length === 0) return;
        const sorted = [...runs].sort(
          (a, b) => new Date(b.run_at || 0) - new Date(a.run_at || 0)
        );
        if (!cancelled) setStatus(sorted[0].status);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [projectId]);

  if (status === null) {
    return (
      <Link to={`/projects/${projectId}/tests`} className="test-status-icon test-status-icon--none" title="No test results">
        &mdash;
      </Link>
    );
  }

  if (status === 'passed') {
    return (
      <Link to={`/projects/${projectId}/tests`} className="test-status-icon test-status-icon--passed" title="Tests passing">
        {'\u2713'}
      </Link>
    );
  }

  return (
    <Link to={`/projects/${projectId}/tests`} className="test-status-icon test-status-icon--failed" title="Tests failing">
      {'\u2717'}
    </Link>
  );
}

function formatTime(seconds) {
  if (!seconds || seconds === 0) return '\u2014';
  if (seconds < 60) return '< 1m';
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`;
}

function formatTokens(tokens) {
  if (!tokens || tokens === 0) return '\u2014';
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return String(tokens);
}

function ProjectHeader({ project }) {
  const epics = useStore((s) => s.getEpicsByProject(project?.id));
  const tickets = useStore((s) => s.getTicketsByProject(project?.id));
  const activeEpic = epics.find((e) => e.status === 'active' || e.status === 'in_progress');
  const totalTime = tickets.reduce((sum, t) => sum + (t.time_spent_seconds || 0), 0);
  const totalTokens = tickets.reduce((sum, t) => sum + (t.tokens_used || 0), 0);

  if (!project) return null;

  return (
    <div className="project-header">
      <div className="project-header__line2">
        <span className="project-header__meta-label">status:</span>
        <StatusBadge status={project.status} />
        <span className="project-header__meta-label">created:</span>
        <span className="project-header__meta-value">
          {new Date(project.created_at).toLocaleDateString()}
        </span>
        <span className="project-header__meta-label">tokens:</span>
        <span className="project-header__meta-value">{formatTokens(totalTokens)}</span>
        <span className="project-header__meta-label">time:</span>
        <span className="project-header__meta-value">{formatTime(totalTime)}</span>
        <span className="project-header__meta-label">tests:</span>
        <TestStatusIcon projectId={project.id} />
        {activeEpic && (
          <span className="project-header__epic-group">
            <span className="project-header__meta-label">epic:</span>
            <Link to={`/projects/${project.id}/epics/${activeEpic.id}`} className="project-header__epic-link">
              {activeEpic.name}
            </Link>
          </span>
        )}
      </div>
      {project.repo_path && (
        <div className="project-header__repo">
          <span className="project-header__meta-label">path:</span> {project.repo_path}
        </div>
      )}
      {project.description && (
        <div className="project-header__desc">{project.description}</div>
      )}
      <hr className="section-divider" />
    </div>
  );
}

export default ProjectHeader;

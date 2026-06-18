// Path: src/components/project/ProjectHeader.jsx
// File: ProjectHeader.jsx
// Created: 2026-03-29
// Purpose: Renders project header with stacked info lines: status/created/tests, tokens/time, epic/sprint, session (IDEAS Tier 1 #3), path. Tracking summary subscribed via the shared cache hook so this row participates in dashboard-wide dedup.
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect), react-router-dom (Link), useStore, hooks/useTrackingSummary, hooks/useProjectSessions, utils/format, StatusBadge, SessionInfoLine, api/testResults (getProjectTestRuns)
// Data In: project prop (full project object)
// Data Out: default export ProjectHeader component
// Last Modified: 2026-06-12

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { useTrackingSummary } from '../../hooks/useTrackingSummary';
import { useCurrentSession } from '../../hooks/useProjectSessions';
import { formatTime, formatTokens } from '../../utils/format';
import StatusBadge from '../common/StatusBadge';
import SessionInfoLine from '../common/SessionInfoLine';
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

function ProjectHeader({ project }) {
  const epics = useStore((s) => s.getEpicsByProject(project?.id));
  const sprints = useStore((s) => s.getSprintsByProject(project?.id));
  const activeEpic = epics.find((e) => e.status === 'active' || e.status === 'in_progress');
  const activeSprint = sprints.find((s) => s.status === 'active' || s.status === 'in_progress');
  const summary = useTrackingSummary(project?.id);
  const currentSession = useCurrentSession(project?.id);

  const totalTokens = summary ? (summary.project_total.tokens || 0) : 0;
  const totalTime = summary ? (summary.project_total.time_seconds || 0) : 0;

  if (!project) return null;

  return (
    <div className="project-header">
      <div className="project-header__row">
        <span className="project-header__meta-label">status:</span>
        <StatusBadge status={project.status} />
        <span className="project-header__meta-label">created:</span>
        <span className="project-header__meta-value">
          {new Date(project.created_at).toLocaleDateString()}
        </span>
        <span className="project-header__meta-label">tests:</span>
        <TestStatusIcon projectId={project.id} />
      </div>
      <div className="project-header__row">
        <span className="project-header__meta-label">tokens:</span>
        <span className="project-header__meta-value">{formatTokens(totalTokens)}</span>
        <span className="project-header__meta-label">time:</span>
        <span className="project-header__meta-value">{formatTime(totalTime)}</span>
      </div>
      <div className="project-header__row">
        <span className="project-header__meta-label">epic:</span>
        {activeEpic ? (
          <Link to={`/projects/${project.id}/epics/${activeEpic.id}`} className="project-header__epic-link">
            {activeEpic.name}
          </Link>
        ) : (
          <span className="project-header__meta-value project-header__meta-value--dim">none</span>
        )}
        <span className="project-header__meta-label">sprint:</span>
        {activeSprint ? (
          <Link to={`/projects/${project.id}/sprints/${activeSprint.id}`} className="project-header__epic-link">
            S{activeSprint.sprint_number}: {activeSprint.name}
          </Link>
        ) : (
          <span className="project-header__meta-value project-header__meta-value--dim">none</span>
        )}
      </div>
      <div className="project-header__row">
        <SessionInfoLine session={currentSession} variant="header" projectId={project.id} />
      </div>
      {project.repo_path && (
        <div className="project-header__row">
          <span className="project-header__meta-label">path:</span>
          <span className="project-header__meta-value project-header__meta-value--dim">{project.repo_path}</span>
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

// Path: src/components/project/OverheadTracker.jsx
// File: OverheadTracker.jsx
// Created: 2026-03-29
// Purpose: Displays team lead and PM overhead tokens and time for a project
// Caller: ProjectPage.jsx
// Callees: common.css
// Data In: project prop (object with tl_overhead_tokens, tl_overhead_time_seconds, pm_overhead_tokens, pm_overhead_time_seconds)
// Data Out: default export OverheadTracker component
// Last Modified: 2026-03-29

import '../../styles/common.css';

function OverheadTracker({ project }) {
  if (!project) return null;

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    const remainMins = mins % 60;
    return `${hrs}h ${remainMins}m`;
  };

  return (
    <div className="overhead-tracker">
      <div className="overhead-tracker__item">
        <div className="overhead-tracker__label">Team Lead Overhead</div>
        <div className="overhead-tracker__tokens">
          {(project.tl_overhead_tokens / 1000).toFixed(1)}k tokens
        </div>
        <div className="overhead-tracker__time">
          {formatTime(project.tl_overhead_time_seconds)}
        </div>
      </div>
      <div className="overhead-tracker__item">
        <div className="overhead-tracker__label">PM Overhead</div>
        <div className="overhead-tracker__tokens">
          {(project.pm_overhead_tokens / 1000).toFixed(1)}k tokens
        </div>
        <div className="overhead-tracker__time">
          {formatTime(project.pm_overhead_time_seconds)}
        </div>
      </div>
    </div>
  );
}

export default OverheadTracker;

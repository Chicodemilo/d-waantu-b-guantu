import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useStore from '../store/useStore';
import CrossProjectSummary from '../components/dashboard/CrossProjectSummary';
import ProjectCard from '../components/dashboard/ProjectCard';
import TokenOverview from '../components/dashboard/TokenOverview';
import AlertBanner from '../components/common/AlertBanner';
import AgentList from '../components/agents/AgentList';
import TokenAudit from '../components/dashboard/TokenAudit';
import { dismissAllAlerts, getAlerts } from '../api/alerts';
import { createProjectFromRepo } from '../api/projects';
import '../styles/dashboard.css';

function DashboardPage() {
  const navigate = useNavigate();
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const openAlerts = useStore((s) => s.getOpenAlerts());
  const setAlerts = useStore((s) => s.setAlerts);
  const [dismissing, setDismissing] = useState(false);
  const [addExpanded, setAddExpanded] = useState(false);
  const [repoPath, setRepoPath] = useState('');
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState(null);

  const handleDismissAll = async () => {
    setDismissing(true);
    try {
      await dismissAllAlerts();
      const alerts = await getAlerts();
      setAlerts(alerts);
    } catch {
      // next poll will refresh
    } finally {
      setDismissing(false);
    }
  };

  return (
    <div className="dashboard">
      <div>
        <div className="dashboard__section-title">Summary</div>
        <CrossProjectSummary />
      </div>

      {openAlerts.length > 0 && (
        <div>
          <div className="dashboard__section-title">
            Open Alerts
            <span className="tooltip-trigger">?<span className="tooltip-content"><strong>Alerts</strong> are flags raised by agents that need human attention. Dismiss to acknowledge, or reply and ask questions in your CLI.<ul className="tooltip-list"><li><strong>Blue</strong> — info (heads up)</li><li><strong>Yellow</strong> — warning (needs attention)</li><li><strong>Red</strong> — critical (urgent action required)</li></ul></span></span>
            <button
              className="sync-btn"
              onClick={handleDismissAll}
              disabled={dismissing}
              style={{ marginLeft: '16px' }}
            >
              {dismissing ? '$ dismissing...' : '$ dismiss all'}
            </button>
          </div>
          <div className="alerts-container">
            {[...openAlerts].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)).map((alert) => (
              <AlertBanner key={alert.id} alert={alert} />
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="dashboard__section-title">
          Projects
          <button
            className="sync-btn"
            style={{ marginLeft: '16px' }}
            onClick={() => { setAddExpanded(!addExpanded); setAddError(null); }}
          >
            {addExpanded ? '$ cancel' : '$ add project'}
          </button>
        </div>
        {addExpanded && (
          <div className="add-project">
            <form
              className="add-project__form"
              onSubmit={async (e) => {
                e.preventDefault();
                if (!repoPath.trim()) return;
                setAdding(true);
                setAddError(null);
                try {
                  const project = await createProjectFromRepo(repoPath.trim());
                  setRepoPath('');
                  setAddExpanded(false);
                  navigate(`/projects/${project.id}`);
                } catch (err) {
                  setAddError(err.message || 'Failed to create project');
                } finally {
                  setAdding(false);
                }
              }}
            >
              <input
                className="add-project__input"
                type="text"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="/path/to/repo"
                autoFocus
              />
              <button
                className="sync-btn"
                type="submit"
                disabled={adding || !repoPath.trim()}
              >
                {adding ? '$ creating...' : '$ create'}
              </button>
            </form>
            {addError && <div className="add-project__error">{addError}</div>}
          </div>
        )}
        <div className="project-cards">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      </div>

      <div>
        <div className="dashboard__section-title">Token Usage</div>
        <TokenOverview />
        <TokenAudit />
      </div>

      <div>
        <div className="dashboard__section-title">Agents</div>
        <AgentList />
      </div>

    </div>
  );
}

export default DashboardPage;

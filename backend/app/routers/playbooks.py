# Path: app/routers/playbooks.py
# File: playbooks.py
# Created: 2026-03-29
# Purpose: Playbook listing and deployment (TL, PM, worker) to project repos
# Caller: app/main.py
# Callees: app/services/project.py, app/services/agent_memory.py, pathlib, shutil
# Data In: HTTP requests
# Data Out: JSON responses (playbook list, deploy status incl. scaffolded memory dirs)
# Last Modified: 2026-06-04

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.services import agent_memory, project as project_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["playbooks"])

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
DWB_REPO_ROOT = Path(__file__).resolve().parents[3]
DWB_AGENT_DEFS_DIR = DWB_REPO_ROOT / ".claude" / "agents"

PLAYBOOK_FILES = {
    "team_lead": "team_lead_playbook.md",
    "pm": "pm_playbook.md",
    "worker": "worker_playbook.md",
}

# Canonical role agent definitions deployed from DWB's `.claude/agents/` to
# every target project's `.claude/agents/`. CC auto-loads these when spawning
# the corresponding `@<role>` teammate. Overwritten on each deploy — same as
# playbook files. Project-specific agent defs (custom roles) live alongside
# but are NOT clobbered (file not in this list = preserved).
AGENT_DEF_FILES = [
    "worker.md",
    "team-lead.md",
    "pm.md",
    "backend-worker.md",
    "frontend-worker.md",
    "system-ops.md",
    "tester.md",
]


class PlaybookRead(BaseModel):
    name: str
    title: str
    content: str


class DeployedMemoryDir(BaseModel):
    """Per-agent scaffold result attached to a deploy-playbooks response."""

    agent_id: int
    agent_name: str
    memory_dir: str
    created: list[str] = []
    refreshed: list[str] = []
    preserved: list[str] = []
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None  # set when scaffold raised; deploy still 200s


class DeployResult(BaseModel):
    deployed: list[str]
    target_dir: str
    memory_dirs: list[DeployedMemoryDir] = []


@router.get("/playbooks", response_model=list[PlaybookRead])
def list_playbooks():
    results = []
    for key, filename in PLAYBOOK_FILES.items():
        path = DOCS_DIR / filename
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        # Extract title from first markdown heading
        title = key.replace("_", " ").title() + " Playbook"
        for line in content.splitlines():
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break
        results.append(PlaybookRead(name=key, title=title, content=content))
    return results


@router.post("/projects/{project_id}/deploy-playbooks", response_model=DeployResult)
def deploy_playbooks(project_id: int, db: Session = Depends(get_db)):
    project = project_svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.repo_path:
        raise HTTPException(400, "Project has no repo_path configured")

    repo = Path(project.repo_path)
    if not repo.is_dir():
        raise HTTPException(400, f"repo_path does not exist: {project.repo_path}")

    target_dir = repo / ".claude"
    target_dir.mkdir(parents=True, exist_ok=True)

    deployed = []
    for key, filename in PLAYBOOK_FILES.items():
        src = DOCS_DIR / filename
        if not src.is_file():
            continue
        dst = target_dir / filename
        shutil.copy2(src, dst)
        deployed.append(filename)

    if not deployed:
        raise HTTPException(500, "No playbook files found in docs/")

    # Create blank project rules files (never overwrite existing)
    PROJECT_RULES_FILES = {
        "project_rules_team_lead.md": "# Project Rules — Team Lead\n\n> Project-specific rules for the TL. This file is NOT overwritten by deploy.\n\n",
        "project_rules_pm.md": "# Project Rules — PM\n\n> Project-specific rules for the PM. This file is NOT overwritten by deploy.\n\n",
        "project_rules_worker.md": "# Project Rules — Workers\n\n> Project-specific rules for all workers. This file is NOT overwritten by deploy.\n\n",
    }

    for filename, default_content in PROJECT_RULES_FILES.items():
        dst = target_dir / filename
        if not dst.exists():
            dst.write_text(default_content, encoding="utf-8")
            deployed.append(f"{filename} (created)")

    # Deploy canonical role agent definitions to the target project's
    # `.claude/agents/`. Overwritten on each deploy. Project-specific defs
    # (custom roles not in AGENT_DEF_FILES) are preserved. Skipped when the
    # target is DWB itself (source == destination → shutil SameFileError).
    agents_target_dir = target_dir / "agents"
    agents_target_dir.mkdir(parents=True, exist_ok=True)
    if agents_target_dir.resolve() != DWB_AGENT_DEFS_DIR.resolve():
        for filename in AGENT_DEF_FILES:
            src = DWB_AGENT_DEFS_DIR / filename
            if not src.is_file():
                continue
            dst = agents_target_dir / filename
            shutil.copy2(src, dst)
            deployed.append(f"agents/{filename}")

    # DWB-298: Scaffold memory dirs for every active agent on the project.
    # Best-effort per agent — a single failure is captured as an `error`
    # entry on that agent's record and does not block the overall deploy.
    memory_dirs: list[DeployedMemoryDir] = []
    agents = db.scalars(
        select(Agent)
        .where(Agent.project_id == project.id, Agent.is_active.is_(True))
        .order_by(Agent.id)
    ).all()
    for agent in agents:
        try:
            res = agent_memory.scaffold_agent_dir(db, agent.id)
            memory_dirs.append(
                DeployedMemoryDir(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    memory_dir=res.memory_dir,
                    created=res.created,
                    refreshed=res.refreshed,
                    preserved=res.preserved,
                    skipped=res.skipped,
                    skip_reason=res.skip_reason,
                )
            )
        except agent_memory.ScaffoldError as e:
            logger.warning(
                "deploy-playbooks: scaffold_agent_dir failed for agent_id=%s "
                "on project %s: %s (%s)",
                agent.id, project.prefix, e.detail, e.code,
            )
            memory_dirs.append(
                DeployedMemoryDir(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    memory_dir="",
                    error=f"{e.code}: {e.detail}",
                )
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.exception(
                "deploy-playbooks: unexpected error scaffolding agent_id=%s", agent.id
            )
            memory_dirs.append(
                DeployedMemoryDir(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    memory_dir="",
                    error=f"unexpected: {e}",
                )
            )

    project.playbooks_deployed_at = datetime.now(timezone.utc)
    db.commit()

    return DeployResult(
        deployed=deployed,
        target_dir=str(target_dir),
        memory_dirs=memory_dirs,
    )

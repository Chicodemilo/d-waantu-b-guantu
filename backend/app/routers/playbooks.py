# Path: app/routers/playbooks.py
# File: playbooks.py
# Created: 2026-03-29
# Purpose: Playbook listing and deployment (TL, PM, worker) to project repos
# Caller: app/main.py
# Callees: app/services/project.py, pathlib, shutil
# Data In: HTTP requests
# Data Out: JSON responses (playbook list, deploy status)
# Last Modified: 2026-04-16

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import project as project_svc

router = APIRouter(prefix="/api", tags=["playbooks"])

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"

PLAYBOOK_FILES = {
    "team_lead": "team_lead_playbook.md",
    "pm": "pm_playbook.md",
    "worker": "worker_playbook.md",
}


class PlaybookRead(BaseModel):
    name: str
    title: str
    content: str


class DeployResult(BaseModel):
    deployed: list[str]
    target_dir: str


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

    project.playbooks_deployed_at = datetime.now(timezone.utc)
    db.commit()

    return DeployResult(deployed=deployed, target_dir=str(target_dir))

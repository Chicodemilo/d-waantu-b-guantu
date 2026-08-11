# Path: app/routers/playbooks.py
# File: playbooks.py
# Created: 2026-03-29
# Purpose: Playbook listing + manual deploy endpoint. Deploy logic lives in app/services/playbook_deploy.py (DWB-461) so creation and the manual endpoint share one implementation.
# Caller: app/main.py
# Callees: app/services/playbook_deploy.py, app/services/project.py
# Data In: HTTP requests
# Data Out: JSON responses (playbook list incl. the global coding-standards sheet, deploy status incl. scaffolded memory dirs)
# Last Modified: 2026-08-11 (DWB-027: surface coding-standards sheet in the listing)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import project as project_svc
from app.services.playbook_deploy import (
    DOCS_DIR,
    PLAYBOOK_FILES,
    DeployError,
    DeployedMemoryDir,
    DeployResult,
    deploy_bundle,
)

# DWB-027: the service owns reading + frontmatter-stripping the global sheet
# (body-or-None for the graceful skip) so the UI listing never drifts from what
# gets deployed (single source of truth, DWB-013) and the router stays thin.
from app.services.playbook_deploy import coding_standards_sheet_body

# DWB-461: re-exported so the existing test imports
# (`from app.routers.playbooks import _HOOKS_SETTINGS_BLOCK` / `DWB_COMMANDS_DIR`)
# keep resolving after the deploy logic moved to the service module. These
# names are the canonical drift-guarded definitions in playbook_deploy.
from app.services.playbook_deploy import (  # noqa: F401  (re-export for tests/back-compat)
    DWB_COMMANDS_DIR,
    _HOOKS_SETTINGS_BLOCK,
)

router = APIRouter(prefix="/api", tags=["playbooks"])

# Keep DeployedMemoryDir importable from this module for any back-compat callers.
__all__ = ["router", "DeployResult", "DeployedMemoryDir"]


class PlaybookRead(BaseModel):
    name: str
    title: str
    content: str


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

    # DWB-027: surface the global coding-standards sheet alongside the playbooks
    # so it renders wherever playbooks render (Instructions page). The service
    # returns the frontmatter-stripped body, or None to skip gracefully when the
    # sheet is absent.
    sheet_body = coding_standards_sheet_body()
    if sheet_body is not None:
        results.append(PlaybookRead(
            name="coding_standards",
            title="Coding Standards",
            content=sheet_body,
        ))

    return results


@router.post("/projects/{project_id}/deploy-playbooks", response_model=DeployResult)
def deploy_playbooks(project_id: int, db: Session = Depends(get_db)):
    project = project_svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        return deploy_bundle(db, project)
    except ValueError as e:
        # No repo_path / repo_path not a directory.
        raise HTTPException(400, str(e))
    except DeployError as e:
        # Server misconfiguration: no playbook files found in docs/.
        raise HTTPException(500, str(e))

# Path: app/routers/status.py
# File: status.py
# Created: 2026-03-29
# Purpose: System status, test coverage, code standards, system docs, and test runner endpoints
# Caller: app/main.py
# Callees: app/models (agent, alert, ticket), pathlib, subprocess
# Data In: HTTP requests
# Data Out: JSON responses (status dict, coverage report, header format)
# Last Modified: 2026-03-29

import json
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.models.alert import Alert, AlertStatus
from app.models.ticket import Ticket, TicketStatus

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = BACKEND_DIR / "scripts"


class StatusResponse(BaseModel):
    healthy: bool
    active_agents: int
    open_alerts: int
    in_progress_tickets: int


REPO_ROOT = BACKEND_DIR.parent

_SYSTEM_DOC_FILES = ["README.md", "QUICKSTART.md", "ARCHITECTURE.md"]

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)):
    active_agents = db.scalar(
        select(func.count()).select_from(Agent).where(Agent.is_active.is_(True))
    ) or 0
    open_alerts = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.open)
    ) or 0
    in_progress_tickets = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.status == TicketStatus.in_progress)
    ) or 0

    return StatusResponse(
        healthy=True,
        active_agents=active_agents,
        open_alerts=open_alerts,
        in_progress_tickets=in_progress_tickets,
    )


@router.get("/status/test-coverage")
def get_test_coverage():
    routers_dir = BACKEND_DIR / "app" / "routers"
    tests_dir = BACKEND_DIR / "tests"

    router_files = sorted(
        f.name for f in routers_dir.glob("*.py") if f.name != "__init__.py"
    )
    test_files = {f.name for f in tests_dir.glob("test_*.py")}

    coverage = []
    for router_name in router_files:
        stem = router_name.removesuffix(".py")
        expected_test = f"test_{stem}.py"
        covered = expected_test in test_files
        coverage.append({
            "router": router_name,
            "test_file": expected_test if covered else None,
            "covered": covered,
        })

    return coverage


_CODE_HEADER_FORMAT = {
    "fields": [
        {"name": "Path", "description": "Relative path to file", "example": "app/services/sprint.py"},
        {"name": "File", "description": "Filename", "example": "sprint.py"},
        {"name": "Created", "description": "Creation date", "example": "2026-03-28"},
        {"name": "Purpose", "description": "One sentence description", "example": "Sprint CRUD and lifecycle automation"},
        {"name": "Caller", "description": "What calls this", "example": "app/routers/sprints.py"},
        {"name": "Callees", "description": "What this calls", "example": "models.sprint, models.alert, models.ticket"},
        {"name": "Data In", "description": "Input params/types", "example": "db: Session, data: SprintCreate"},
        {"name": "Data Out", "description": "Return types", "example": "Sprint"},
        {"name": "Last Modified", "description": "Last modification date", "example": "2026-03-28"},
    ],
    "template": (
        "# Path: relative/path/to/file.py\n"
        "# File: filename.py\n"
        "# Created: YYYY-MM-DD\n"
        "# Purpose: One sentence description\n"
        "# Caller: What calls this\n"
        "# Callees: What this calls\n"
        "# Data In: Input params/types\n"
        "# Data Out: Return types\n"
        "# Last Modified: YYYY-MM-DD"
    ),
    "placement": "First comment block after imports",
}


@router.get("/status/code-standards")
def get_code_standards():
    return {"header_format": _CODE_HEADER_FORMAT}


@router.get("/system/docs")
def get_system_docs():
    """Return DWB system-level documentation files from the repo root."""
    docs = []
    for name in _SYSTEM_DOC_FILES:
        filepath = REPO_ROOT / name
        exists = filepath.is_file()
        content = None
        if exists:
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception:
                content = None
        docs.append({
            "name": name,
            "path": str(filepath),
            "exists": exists,
            "content": content,
        })
    return docs


@router.post("/system/run-tests")
def run_tests():
    """Trigger the backend test suite via run_tests.sh and return a summary."""
    script = SCRIPTS_DIR / "run_tests.sh"
    if not script.is_file():
        raise HTTPException(500, f"Test script not found at {script}")

    start = time.monotonic()
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(BACKEND_DIR),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Test run timed out after 300 seconds")
    except Exception as exc:
        raise HTTPException(500, f"Failed to run tests: {exc}")

    duration = round(time.monotonic() - start, 3)

    # Try to parse the JSON report for accurate counts
    report_path = Path("/tmp/lat_pytest_report.json")
    passed = 0
    failed = 0
    total = 0
    report_duration = duration

    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text())
            summary = report.get("summary", {})
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            total = summary.get("total", 0)
            report_duration = round(report.get("duration", duration), 3)
        except Exception:
            pass

    if total == 0:
        # Fallback: parse from stdout
        for line in result.stdout.splitlines():
            if "passed" in line or "failed" in line:
                pass  # JSON report is the authoritative source

    status = "passed" if result.returncode == 0 else "failed"

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "duration_seconds": report_duration,
        "status": status,
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-1000:],
    }

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
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models.agent import Agent
from app.models.alert import Alert, AlertCategory, AlertStatus
from app.models.ticket import Ticket, TicketStatus
from app.schemas.test_result import TestResultCreate
from app.services import test_result as test_result_svc

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = BACKEND_DIR / "scripts"


class InfraWarning(BaseModel):
    key: str
    severity: str  # info, warning, critical
    message: str


class StatusResponse(BaseModel):
    healthy: bool
    active_agents: int
    open_alerts: int
    in_progress_tickets: int
    infra_warnings: Optional[list[InfraWarning]] = None


REPO_ROOT = BACKEND_DIR.parent

_SYSTEM_DOC_FILES = ["README.md", "QUICKSTART.md", "ARCHITECTURE.md"]

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)):
    active_agents = db.scalar(
        select(func.count()).select_from(Agent).where(Agent.is_active.is_(True))
    ) or 0
    # DWB-462: count only categorized alerts (comms / scoring / actionable).
    # A defensive scope so the dashboard badge reflects real alerts; once
    # DWB-463 demotes peer-scoring / sprint-close / test-run to the activity
    # feed, those rows no longer exist as alerts and the count drops naturally.
    open_alerts = db.scalar(
        select(func.count())
        .select_from(Alert)
        .where(Alert.status == AlertStatus.open)
        .where(Alert.category.in_([
            AlertCategory.comms,
            AlertCategory.scoring,
            AlertCategory.actionable,
        ]))
    ) or 0
    in_progress_tickets = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.status == TicketStatus.in_progress)
    ) or 0

    # Infra checks
    warnings = []

    # DB connection pool health
    pool = engine.pool
    pool_size = pool.size()
    pool_checked_out = pool.checkedout()
    pool_overflow = pool.overflow()
    if pool_checked_out >= pool_size:
        warnings.append(InfraWarning(
            key="db_pool_exhausted",
            severity="critical",
            message=f"DB pool exhausted: {pool_checked_out}/{pool_size} connections in use, {pool_overflow} overflow",
        ))
    elif pool_checked_out >= pool_size * 0.7:
        warnings.append(InfraWarning(
            key="db_pool_high",
            severity="warning",
            message=f"DB pool high usage: {pool_checked_out}/{pool_size} connections in use",
        ))

    # Stale DB connections (queries running > 60s)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.processlist "
                "WHERE user != 'event_scheduler' AND command = 'Query' AND time > 60"
            ))
            stale = result.scalar() or 0
            if stale > 0:
                warnings.append(InfraWarning(
                    key="db_stale_connections",
                    severity="critical" if stale > 5 else "warning",
                    message=f"{stale} stale DB queries running > 60s — possible deadlock",
                ))
    except Exception:
        pass

    # Disk space (host)
    disk = shutil.disk_usage("/")
    free_gb = disk.free / (1024 ** 3)
    pct_used = (disk.used / disk.total) * 100
    if free_gb < 5:
        warnings.append(InfraWarning(
            key="disk_low",
            severity="critical",
            message=f"Host disk critically low: {free_gb:.1f} GB free ({pct_used:.0f}% used)",
        ))
    elif free_gb < 20:
        warnings.append(InfraWarning(
            key="disk_low",
            severity="warning",
            message=f"Host disk getting low: {free_gb:.1f} GB free ({pct_used:.0f}% used)",
        ))

    # Docker disk (check via subprocess if docker available)
    try:
        result = subprocess.run(
            ["docker", "system", "df", "--format", "{{.Size}}\t{{.Reclaimable}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 1 and "GB" in parts[0]:
                    size_str = parts[0].replace("GB", "").strip()
                    try:
                        size_gb = float(size_str)
                        if size_gb > 30:
                            warnings.append(InfraWarning(
                                key="docker_disk_high",
                                severity="warning",
                                message=f"Docker using {size_gb:.1f} GB — consider pruning",
                            ))
                            break
                    except ValueError:
                        pass
    except Exception:
        pass

    return StatusResponse(
        healthy=True,
        active_agents=active_agents,
        open_alerts=open_alerts,
        in_progress_tickets=in_progress_tickets,
        infra_warnings=warnings if warnings else None,
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
def run_tests(
    project_id: int = Query(1),
    db: Session = Depends(get_db),
):
    """Trigger the backend test suite via run_tests.sh, store and return a summary."""
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
    skipped = 0
    total = 0
    report_duration = duration
    test_details = []

    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text())
            summary = report.get("summary", {})
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            skipped = summary.get("skipped", 0)
            total = summary.get("total", 0)
            report_duration = round(report.get("duration", duration), 3)

            for t in report.get("tests", []):
                dur = sum(
                    t.get(phase, {}).get("duration", 0) or 0
                    for phase in ("setup", "call", "teardown")
                )
                test_details.append({
                    "nodeid": t.get("nodeid", ""),
                    "outcome": t.get("outcome", "unknown"),
                    "duration": round(dur, 4),
                })
        except Exception:
            pass

    status = "passed" if result.returncode == 0 else "failed"
    stdout_tail = (result.stdout or "")[-4000:]
    stderr_tail = (result.stderr or "")[-1000:]

    # Build details JSON matching run_tests.sh format
    details_obj = {
        "tests": test_details,
        "raw_output_tail": stdout_tail,
    }

    # Persist the test result record
    tr = test_result_svc.create_test_result(db, TestResultCreate(
        project_id=project_id,
        suite="backend",
        total_tests=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_seconds=report_duration,
        status=status,
        details=json.dumps(details_obj),
        triggered_by="system/run-tests",
    ))

    return {
        "test_result_id": tr.id,
        "passed": passed,
        "failed": failed,
        "total": total,
        "duration_seconds": report_duration,
        "status": status,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }

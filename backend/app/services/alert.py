# Path: app/services/alert.py
# File: alert.py
# Created: 2026-03-29
# Purpose: Alert CRUD, send-to-team, auto-unlink, dismiss-all
# Caller: app/routers/alerts.py
# Callees: app/models/alert.py, app/models/project.py
# Data In: db: Session, AlertCreate/Update
# Data Out: list[Alert], Alert, send-to-team dict
# Last Modified: 2026-04-17

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.project import Project
from app.schemas.alert import AlertCreate, AlertUpdate


def list_alerts(
    db: Session,
    project_id: int | None = None,
    severity: AlertSeverity | None = None,
    status: AlertStatus | None = None,
) -> list[Alert]:
    stmt = select(Alert)
    if project_id:
        stmt = stmt.where(Alert.project_id == project_id)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if status:
        stmt = stmt.where(Alert.status == status)
    stmt = stmt.order_by(Alert.created_at.desc())
    return list(db.scalars(stmt).all())


def get_alert(db: Session, alert_id: int) -> Alert | None:
    return db.get(Alert, alert_id)


def create_alert(db: Session, data: AlertCreate) -> Alert:
    alert = Alert(**data.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def dismiss_all(db: Session, project_id: int | None = None) -> int:
    """Set all open alerts to acknowledged with resolved_at=now. Returns count."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Alert)
        .where(Alert.status == AlertStatus.open)
        .values(status=AlertStatus.acknowledged, resolved_at=now)
    )
    if project_id is not None:
        stmt = stmt.where(Alert.project_id == project_id)
    result = db.execute(stmt)
    db.commit()

    # Auto-unlink: remove ALERTS_PENDING.md if no open alerts remain
    if project_id is not None:
        _auto_unlink_alerts_file(db, project_id)

    return result.rowcount


def update_alert(db: Session, alert: Alert, data: AlertUpdate) -> Alert:
    updates = data.model_dump(exclude_unset=True)
    # Auto-set resolved_at when status changes to resolved
    if updates.get("status") == AlertStatus.resolved and "resolved_at" not in updates:
        updates["resolved_at"] = datetime.now(timezone.utc)
    for key, value in updates.items():
        setattr(alert, key, value)
    db.commit()
    db.refresh(alert)

    # Auto-unlink: remove ALERTS_PENDING.md if no open alerts remain for this project
    if "status" in updates:
        _auto_unlink_alerts_file(db, alert.project_id)

    return alert


def send_to_team(db: Session, project: Project) -> dict:
    """Write open alerts to .claude/ALERTS_PENDING.md and tag each with user_sent_at."""
    alerts = list_alerts(db, project_id=project.id, status=AlertStatus.open)

    repo = Path(project.repo_path)
    target = repo / ".claude" / "ALERTS_PENDING.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# Pending Alerts — {project.name}\n\n"]
    for a in alerts:
        ticket_info = f" [{a.ticket.ticket_key}]" if a.ticket_id and a.ticket else ""
        lines.append(f"- **{a.severity.value.upper()}**{ticket_info}: {a.title}\n")

    target.write_text("".join(lines), encoding="utf-8")

    # Tag each alert with user_sent_at
    now = datetime.now(timezone.utc)
    for a in alerts:
        a.user_sent_at = now
    db.commit()

    return {"file_written": str(target), "alerts_count": len(alerts)}


def _auto_unlink_alerts_file(db: Session, project_id: int) -> None:
    """Delete ALERTS_PENDING.md if no open alerts remain for the project."""
    remaining = db.scalar(
        select(Alert.id)
        .where(Alert.project_id == project_id)
        .where(Alert.status == AlertStatus.open)
        .limit(1)
    )
    if remaining is not None:
        return

    project = db.get(Project, project_id)
    if not project or not project.repo_path:
        return

    target = Path(project.repo_path) / ".claude" / "ALERTS_PENDING.md"
    if target.exists():
        target.unlink()

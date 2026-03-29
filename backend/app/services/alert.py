# Path: app/services/alert.py
# File: alert.py
# Created: 2026-03-29
# Purpose: Alert CRUD with auto-resolved_at on status change
# Caller: app/routers/alerts.py
# Callees: app/models/alert.py
# Data In: db: Session, AlertCreate/Update
# Data Out: list[Alert], Alert
# Last Modified: 2026-03-29

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertSeverity, AlertStatus
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
    return alert

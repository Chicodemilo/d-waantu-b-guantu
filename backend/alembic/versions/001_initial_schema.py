"""Initial schema - all 10 tables

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- projects ---
    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("prefix", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "paused", "completed", "archived", name="projectstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("tl_overhead_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("pm_overhead_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("tl_overhead_time_seconds", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("pm_overhead_time_seconds", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # --- sprints ---
    op.create_table(
        "sprints",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("goal", sa.Text, nullable=True),
        sa.Column("sprint_number", sa.Integer, nullable=False),
        sa.Column(
            "status",
            sa.Enum("planned", "active", "completed", name="sprintstatus"),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sprints_project_id", "sprints", ["project_id"])

    # --- epics ---
    op.create_table(
        "epics",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "in_progress", "completed", name="epicstatus"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_epics_project_id", "epics", ["project_id"])

    # --- agents ---
    op.create_table(
        "agents",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "role",
            sa.Enum("team_lead", "pm", "developer", "reviewer", "specialist", name="agentrole"),
            nullable=False,
        ),
        sa.Column("api_key", sa.String(255), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # --- project_agents ---
    op.create_table(
        "project_agents",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.BigInteger, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "agent_id", name="uq_project_agent"),
    )
    op.create_index("ix_project_agents_project_id", "project_agents", ["project_id"])
    op.create_index("ix_project_agents_agent_id", "project_agents", ["agent_id"])

    # --- tickets ---
    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("epic_id", sa.BigInteger, sa.ForeignKey("epics.id"), nullable=True),
        sa.Column("sprint_id", sa.BigInteger, sa.ForeignKey("sprints.id"), nullable=True),
        sa.Column("assigned_agent_id", sa.BigInteger, sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("ticket_number", sa.Integer, nullable=False),
        sa.Column("ticket_key", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "ticket_type",
            sa.Enum("task", "bug", "story", name="tickettype"),
            nullable=False,
            server_default="task",
        ),
        sa.Column(
            "status",
            sa.Enum("backlog", "todo", "in_progress", "in_review", "done", name="ticketstatus"),
            nullable=False,
            server_default="backlog",
        ),
        sa.Column("tokens_used", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("time_spent_seconds", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_tickets_project_id", "tickets", ["project_id"])
    op.create_index("ix_tickets_epic_id", "tickets", ["epic_id"])
    op.create_index("ix_tickets_sprint_id", "tickets", ["sprint_id"])
    op.create_index("ix_tickets_assigned_agent_id", "tickets", ["assigned_agent_id"])

    # --- comments ---
    op.create_table(
        "comments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.BigInteger, sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("author_agent_id", sa.BigInteger, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_comments_ticket_id", "comments", ["ticket_id"])
    op.create_index("ix_comments_author_agent_id", "comments", ["author_agent_id"])

    # --- alerts ---
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("raised_by_agent_id", sa.BigInteger, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("ticket_id", sa.BigInteger, sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "critical", name="alertseverity"),
            nullable=False,
            server_default="info",
        ),
        sa.Column(
            "status",
            sa.Enum("open", "acknowledged", "resolved", name="alertstatus"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_alerts_project_id", "alerts", ["project_id"])
    op.create_index("ix_alerts_raised_by_agent_id", "alerts", ["raised_by_agent_id"])
    op.create_index("ix_alerts_ticket_id", "alerts", ["ticket_id"])

    # --- instructions ---
    op.create_table(
        "instructions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "scope",
            sa.Enum("global", "project", "agent", name="instructionscope"),
            nullable=False,
        ),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("agent_id", sa.BigInteger, sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_instructions_project_id", "instructions", ["project_id"])
    op.create_index("ix_instructions_agent_id", "instructions", ["agent_id"])

    # --- activity_log ---
    op.create_table(
        "activity_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.BigInteger, sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_activity_log_project_id", "activity_log", ["project_id"])
    op.create_index("ix_activity_log_agent_id", "activity_log", ["agent_id"])


def downgrade() -> None:
    op.drop_table("activity_log")
    op.drop_table("instructions")
    op.drop_table("alerts")
    op.drop_table("comments")
    op.drop_table("tickets")
    op.drop_table("project_agents")
    op.drop_table("agents")
    op.drop_table("epics")
    op.drop_table("sprints")
    op.drop_table("projects")

    # Drop enum types for MySQL (no-op on MySQL but good practice)
    op.execute("DROP TYPE IF EXISTS projectstatus")
    op.execute("DROP TYPE IF EXISTS sprintstatus")
    op.execute("DROP TYPE IF EXISTS epicstatus")
    op.execute("DROP TYPE IF EXISTS agentrole")
    op.execute("DROP TYPE IF EXISTS tickettype")
    op.execute("DROP TYPE IF EXISTS ticketstatus")
    op.execute("DROP TYPE IF EXISTS alertseverity")
    op.execute("DROP TYPE IF EXISTS alertstatus")
    op.execute("DROP TYPE IF EXISTS instructionscope")

# Path: app/routers/playbooks.py
# File: playbooks.py
# Created: 2026-03-29
# Purpose: Playbook listing and deployment (TL, PM, worker) to project repos, with Jira-awareness (DWB-332) + hooks settings.json deploy (DWB-390)
# Caller: app/main.py
# Callees: app/services/project.py, app/services/agent_memory.py, pathlib, shutil, re, json
# Data In: HTTP requests
# Data Out: JSON responses (playbook list, deploy status incl. scaffolded memory dirs)
# Last Modified: 2026-06-12

import json
import logging
import re
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

# DWB-368: auxiliary docs cross-referenced by the playbook prose. Deployed
# verbatim (no Jira-variant scrub) to each project's `.claude/` so refs like
# `.claude/session_lifecycle.md` and `.claude/rules/global/code-header-format.md`
# resolve on consumer projects, not just on DWB. Path inside the source repo
# is mirrored under `.claude/`: docs/session_lifecycle.md -> .claude/session_lifecycle.md;
# docs/rules/global/code-header-format.md -> .claude/rules/global/code-header-format.md.
AUX_DOCS = [
    "session_lifecycle.md",
    "rules/global/code-header-format.md",
]


# DWB-332: scrub markers for variant-aware deploy. Playbook source carries
# both Jira-flavored and non-Jira blocks side-by-side; on deploy we keep one
# and drop the other based on the target project's jira_base_url.
#
#   <!-- jira-only:start --> ... <!-- jira-only:end -->
#       Kept on Jira-enabled projects, stripped on non-Jira projects.
#
#   <!-- non-jira-only:start --> ... <!-- non-jira-only:end -->
#       Inverse — stripped on Jira, kept on non-Jira.
#
# Picked scrub-on-write over variant-templates (separate Jira / non-Jira
# files) because the alternative would double the maintenance surface: every
# edit to the playbook would have to land in both copies, and drift between
# them is invisible until an agent reads the wrong one. Markers keep one
# canonical source with the variant decisions explicit and grep-able.
_JIRA_ONLY_BLOCK_RE = re.compile(
    r"<!--\s*jira-only:start\s*-->.*?<!--\s*jira-only:end\s*-->\s*\n?",
    re.DOTALL,
)
_NON_JIRA_ONLY_BLOCK_RE = re.compile(
    r"<!--\s*non-jira-only:start\s*-->.*?<!--\s*non-jira-only:end\s*-->\s*\n?",
    re.DOTALL,
)


def _scrub_for_jira_target(text: str, *, jira_enabled: bool) -> str:
    """Apply the variant rule: drop the inverse block, keep the matching one.

    Jira-enabled deploy: keep jira-only blocks, strip non-jira-only blocks.
    Non-Jira deploy: strip jira-only blocks, keep non-jira-only blocks.

    Marker-tags themselves are left in place on the kept side (HTML comments
    don't render in markdown viewers and are useful when an agent grep's the
    deployed file for context). Tests assert presence/absence by content
    inside the blocks, not by marker presence.
    """
    if jira_enabled:
        return _NON_JIRA_ONLY_BLOCK_RE.sub("", text)
    return _JIRA_ONLY_BLOCK_RE.sub("", text)


_NON_JIRA_BANNER = (
    "> THIS PROJECT IS NOT LINKED TO JIRA.\n"
    "> Do not invoke `dwb2jira` tools or reference Jira issue keys.\n"
    "> All ticket transitions go through the DWB API directly: "
    "`PATCH /api/tickets/{id}` with `{\"status\": \"...\"}` and the "
    "`X-Agent-ID` header.\n\n"
)


def _prepend_banner_if_needed(content: str, *, jira_enabled: bool) -> str:
    """Prepend the non-Jira banner so the agent sees it at the top of the
    file. No-op on Jira-enabled projects.

    Idempotent — if the banner is already present (e.g. file was generated
    with one before), don't double-stack it.
    """
    if jira_enabled:
        return content
    if "THIS PROJECT IS NOT LINKED TO JIRA" in content:
        return content
    return _NON_JIRA_BANNER + content


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
    root_docs: list[str] = []  # DWB-366: skeletons created at repo root
    hooks_settings: str | None = None  # DWB-390: 'created'|'merged'|'unchanged'|None


# DWB-390: hooks block written into each project's `.claude/settings.json`
# so SessionStart / SessionEnd / Stop / SubagentStop / UserPromptSubmit /
# PostToolUse / Notification / PreCompact (DWB-417/421) fire in sibling repos
# the same way they do in DWB. Without this, projects
# 2/4/5/7/8/11 (and any new project) silently log zero token data because
# their `.claude/` has no hooks configured at all. The hook command shape
# matches DWB's own settings.json: curl POST the JSON payload to localhost
# (`$(cat)` re-emits stdin, which is what CC pipes the hook payload through).
# Deploy is idempotent: existing top-level keys in settings.json are
# preserved; only the `hooks` key is replaced. A missing settings.json is
# created fresh.
_HOOKS_SETTINGS_BLOCK: dict = {
    "SessionStart": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/session-start "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 5,
        }],
    }],
    "UserPromptSubmit": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/user-prompt "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 5,
        }],
    }],
    "SessionEnd": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/session-end "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 30,
        }],
    }],
    "Stop": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/session-end "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 30,
        }],
    }],
    "SubagentStop": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/session-end "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 30,
        }],
    }],
    # DWB-417/421: deterministic action capture + lifecycle events. PostToolUse
    # is matcher-scoped to the tools the scoring/capture layer classifies;
    # Notification + PreCompact POST to the lifecycle-event endpoint. Mirrors
    # DWB's own .claude/settings.json exactly so deploy reports "unchanged".
    "PostToolUse": [{
        "matcher": "Write|Edit|MultiEdit|NotebookEdit|Task|SendMessage",
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/tool-use "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 5,
        }],
    }],
    "Notification": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/lifecycle-event "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 5,
        }],
    }],
    "PreCompact": [{
        "hooks": [{
            "type": "command",
            "command": (
                "curl -sf -X POST http://localhost:8000/api/hooks/lifecycle-event "
                "-H 'Content-Type: application/json' -d \"$(cat)\""
            ),
            "timeout": 5,
        }],
    }],
}


def _deploy_hooks_settings(target_dir: Path) -> str | None:
    """Write the DWB hooks block into <target_dir>/settings.json.

    Returns:
      - "created": settings.json did not exist; we wrote a fresh file
        containing only the hooks block.
      - "merged": settings.json existed; we replaced its top-level "hooks"
        key with the DWB block and preserved every other top-level key.
      - "unchanged": settings.json's existing "hooks" key already matches
        the DWB block byte-for-byte; no write performed.
      - None: settings.json existed but was unparseable JSON (e.g. user-
        edited and broken). We do NOT overwrite a broken file — that would
        clobber the user's in-flight edit. Caller may log/warn.

    Path is <target_dir>/settings.json. The file is the project-shared
    settings file (not settings.local.json which is user-local).
    """
    settings_path = target_dir / "settings.json"

    if not settings_path.exists():
        settings_path.write_text(
            json.dumps({"hooks": _HOOKS_SETTINGS_BLOCK}, indent=2) + "\n",
            encoding="utf-8",
        )
        return "created"

    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning(
            "deploy-playbooks: settings.json at %s is unparseable; "
            "refusing to overwrite to preserve user edits",
            settings_path,
        )
        return None

    if not isinstance(existing, dict):
        # JSON valid but not an object — same caution: don't clobber.
        logger.warning(
            "deploy-playbooks: settings.json at %s is not a JSON object; "
            "refusing to overwrite",
            settings_path,
        )
        return None

    if existing.get("hooks") == _HOOKS_SETTINGS_BLOCK:
        return "unchanged"

    existing["hooks"] = _HOOKS_SETTINGS_BLOCK
    settings_path.write_text(
        json.dumps(existing, indent=2) + "\n", encoding="utf-8"
    )
    return "merged"


# DWB-366: minimal H1 + one-line stub for each root doc. Scaffolded when
# missing on deploy-playbooks. Existing files are never overwritten - human
# or TL prose stays intact. Non-Jira projects get the banner prepended.
_ROOT_DOC_STUBS = {
    "INITIAL.md": (
        "# Initial\n\n"
        "> Project initial state - requirements, phases, design decisions, "
        "constraints, success criteria.\n"
    ),
    "ARCHITECTURE.md": (
        "# Architecture\n\n"
        "> System design and data model.\n"
    ),
    "HANDOFF.md": (
        "# Handoff\n\n"
        "> Session-to-session continuity. Read at session start, "
        "update at end.\n"
    ),
}


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

    # DWB-332: variant deploy. Strip the wrong-side variant blocks and
    # prepend a banner for non-Jira targets. shutil.copy2 is bypassed for
    # playbooks because the content needs transformation; copy2's mtime
    # preservation isn't useful when we're rewriting bytes anyway.
    jira_enabled = bool(project.jira_base_url)

    deployed = []
    for key, filename in PLAYBOOK_FILES.items():
        src = DOCS_DIR / filename
        if not src.is_file():
            continue
        src_text = src.read_text(encoding="utf-8")
        out_text = _scrub_for_jira_target(src_text, jira_enabled=jira_enabled)
        out_text = _prepend_banner_if_needed(out_text, jira_enabled=jira_enabled)
        dst = target_dir / filename
        dst.write_text(out_text, encoding="utf-8")
        deployed.append(filename)

    if not deployed:
        raise HTTPException(500, "No playbook files found in docs/")

    # Create blank project rules files (never overwrite existing).
    # DWB-332: non-Jira projects get the banner inserted at file creation
    # time. Existing files are still preserved untouched.
    PROJECT_RULES_FILES = {
        "project_rules_team_lead.md": "# Project Rules — Team Lead\n\n> Project-specific rules for the TL. This file is NOT overwritten by deploy.\n\n",
        "project_rules_pm.md": "# Project Rules — PM\n\n> Project-specific rules for the PM. This file is NOT overwritten by deploy.\n\n",
        "project_rules_worker.md": "# Project Rules — Workers\n\n> Project-specific rules for all workers. This file is NOT overwritten by deploy.\n\n",
    }

    for filename, default_content in PROJECT_RULES_FILES.items():
        dst = target_dir / filename
        if not dst.exists():
            content = _prepend_banner_if_needed(
                default_content, jira_enabled=jira_enabled
            )
            dst.write_text(content, encoding="utf-8")
            deployed.append(f"{filename} (created)")

    # DWB-366: scaffold root doc skeletons (INITIAL.md, ARCHITECTURE.md,
    # HANDOFF.md) at the repo root when missing. Never mutates an existing
    # file - human or TL prose stays intact. Non-Jira projects get the
    # banner prepended so the agent's first read of any of these files
    # gets the visibility signal.
    #
    # These paths live at <repo>/<name>.md (matching the force_*_md gates'
    # expectation), NOT under .claude/. Surfaced via the response's
    # root_docs[] field so existing deployed[] consumers (which assume
    # every entry resolves under .claude/) don't trip.
    root_docs: list[str] = []
    for filename, stub in _ROOT_DOC_STUBS.items():
        path = repo / filename
        if path.exists():
            continue
        content = stub
        if not jira_enabled:
            content = _NON_JIRA_BANNER + content
        path.write_text(content, encoding="utf-8")
        root_docs.append(filename)
        logger.info(
            "deploy-playbooks: scaffolded %s at %s", filename, path
        )

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

    # DWB-368: deploy auxiliary docs (session_lifecycle, code-header-format).
    # These are cross-referenced by the playbook prose; without this copy the
    # refs break on consumer projects. Verbatim copy, no variant scrub.
    if target_dir.resolve() != (DWB_REPO_ROOT / ".claude").resolve():
        for rel_path in AUX_DOCS:
            src = DOCS_DIR / rel_path
            if not src.is_file():
                continue
            dst = target_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            deployed.append(rel_path)

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

    # DWB-390: write the hooks block into <repo>/.claude/settings.json so
    # SessionStart / SessionEnd / SubagentStop / UserPromptSubmit fire on
    # this project's CC instance and POST to /api/hooks/* on localhost.
    # Skipped when the target is DWB itself (we are the source of truth -
    # source==destination would still no-op via the unchanged path, but the
    # explicit skip avoids needlessly re-reading our own settings.json).
    hooks_settings: str | None = None
    if target_dir.resolve() != (DWB_REPO_ROOT / ".claude").resolve():
        hooks_settings = _deploy_hooks_settings(target_dir)

    project.playbooks_deployed_at = datetime.now(timezone.utc)
    db.commit()

    return DeployResult(
        deployed=deployed,
        target_dir=str(target_dir),
        memory_dirs=memory_dirs,
        root_docs=root_docs,
        hooks_settings=hooks_settings,
    )

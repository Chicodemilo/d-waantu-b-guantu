# Path: app/services/playbook_deploy.py
# File: playbook_deploy.py
# Created: 2026-06-24 (DWB-461)
# Purpose: Shared .claude/ bundle deploy logic (playbooks, project rules, root-doc stubs, agent defs, aux docs, slash commands, hooks, memory scaffold). One implementation used by the manual deploy-playbooks endpoint AND project creation.
# Caller: app/routers/playbooks.py (manual deploy), app/routers/projects.py (deploy-on-create)
# Callees: app/services/agent_memory.py, app/models/agent.py, pathlib, shutil, re, json
# Data In: db: Session, project: Project
# Data Out: DeployResult
# Last Modified: 2026-06-24 (DWB-461)

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.services import agent_memory

logger = logging.getLogger(__name__)

# app/services/playbook_deploy.py -> services -> app -> backend -> repo root.
# Same depth as app/routers/playbooks.py, so parents[3] is still the repo root.
DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
DWB_REPO_ROOT = Path(__file__).resolve().parents[3]
DWB_AGENT_DEFS_DIR = DWB_REPO_ROOT / ".claude" / "agents"
# DWB-459: cross-project slash commands (carrot, stick, score, leaderboard,
# tl, dwb-open, dwb-close) live in DWB's `.claude/commands/`. CC only loads
# commands from the cwd repo or user-level, so sibling-repo Archies need their
# own copy. Mirrored to each target's `.claude/commands/` on deploy.
DWB_COMMANDS_DIR = DWB_REPO_ROOT / ".claude" / "commands"

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


class DeployError(Exception):
    """Deploy could not proceed for a domain reason (e.g. no playbook files
    found in docs/). The manual endpoint maps this to HTTP 500; project
    creation captures it as a best-effort warning."""


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
    # Stop fires when the main agent finishes a turn. Two commands run with the
    # same payload on stdin: (1) the session-end token POST, body discarded
    # (-o /dev/null) so only (2) the DWB-443 channel-poke speaks - its stdout
    # JSON is the Stop decision ({"decision":"block",...} when a team-lead has
    # unread Archie Channel messages, else {}).
    "Stop": [{
        "hooks": [
            {
                "type": "command",
                "command": (
                    "curl -sf -o /dev/null -X POST http://localhost:8000/api/hooks/session-end "
                    "-H 'Content-Type: application/json' -d \"$(cat)\""
                ),
                "timeout": 30,
            },
            {
                "type": "command",
                "command": (
                    "curl -sf -X POST http://localhost:8000/api/hooks/channel-poke "
                    "-H 'Content-Type: application/json' -d \"$(cat)\""
                ),
                "timeout": 5,
            },
        ],
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
    "PostToolUse": [
        {
            "matcher": "Write|Edit|MultiEdit|NotebookEdit|Task|SendMessage",
            "hooks": [{
                "type": "command",
                "command": (
                    "curl -sf -X POST http://localhost:8000/api/hooks/tool-use "
                    "-H 'Content-Type: application/json' -d \"$(cat)\""
                ),
                "timeout": 5,
            }],
        },
        # DWB-450: SendMessage body capture into inter_agent_messages. Separate
        # matcher-group (SendMessage only) so it never fires on Write/Edit/Task.
        # The agent-message endpoint takes a remapped body, not the raw hook
        # payload, so a python3 stdlib one-liner pulls tool_input.{to,message,
        # summary} + the top-level session_id and pipes the JSON to curl
        # (-d @-). Best-effort/fire-and-forget like every other hook here: a
        # missing python3 / bad stdin just yields no capture, never an error.
        {
            "matcher": "SendMessage",
            "hooks": [{
                "type": "command",
                "command": (
                    "python3 -c \"import sys,json; d=json.load(sys.stdin); "
                    "ti=d.get('tool_input') or {}; "
                    "print(json.dumps({'to':ti.get('to'),'message':ti.get('message'),"
                    "'summary':ti.get('summary'),'session_id':d.get('session_id')}))\" "
                    "| curl -sf -X POST http://localhost:8000/api/hooks/agent-message "
                    "-H 'Content-Type: application/json' -d @-"
                ),
                "timeout": 5,
            }],
        },
    ],
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


def deploy_bundle(db: Session, project) -> DeployResult:
    """Deploy the full `.claude/` bundle into ``project``'s repo and return a
    DeployResult. Shared by the manual deploy-playbooks endpoint and the
    deploy-on-create hook (DWB-461) so there is exactly one implementation.

    Writes: playbooks (Jira-variant-scrubbed), project-rules skeletons (never
    overwritten), root-doc stubs (never overwritten), canonical agent defs,
    auxiliary docs, the cross-project slash commands (DWB-459), the hooks block
    in settings.json, and per-agent memory dirs. Stamps
    ``project.playbooks_deployed_at`` and commits.

    Raises:
      - ValueError: project has no repo_path, or repo_path is not a directory.
        (Caller decides whether that is a 400 or a best-effort warning.)
      - DeployError: no playbook files found in docs/ (misconfigured server).
    """
    if not project.repo_path:
        raise ValueError("Project has no repo_path configured")

    repo = Path(project.repo_path)
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {project.repo_path}")

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
        raise DeployError("No playbook files found in docs/")

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

    # DWB-459: mirror the cross-project slash commands (.claude/commands/*.md)
    # into each target repo's `.claude/commands/`. CC only loads commands from
    # the cwd repo or user-level (~/.claude), so without this copy the
    # carrot/stick/score/leaderboard/tl/dwb-open/dwb-close commands are missing
    # for Archies in sibling repos (CI/RVP/D2J). Same self-contained per-repo
    # pattern as the agent defs + hooks; create the dir if missing; report each
    # file as copied/unchanged in deployed[]. Skipped when the target is DWB
    # itself (source == destination).
    commands_target_dir = target_dir / "commands"
    if (
        DWB_COMMANDS_DIR.is_dir()
        and commands_target_dir.resolve() != DWB_COMMANDS_DIR.resolve()
    ):
        commands_target_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(DWB_COMMANDS_DIR.glob("*.md")):
            src_text = src.read_text(encoding="utf-8")
            dst = commands_target_dir / src.name
            if dst.is_file() and dst.read_text(encoding="utf-8") == src_text:
                deployed.append(f"commands/{src.name} (unchanged)")
                continue
            shutil.copy2(src, dst)
            deployed.append(f"commands/{src.name} (copied)")

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

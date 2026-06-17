# Path: app/services/agent.py
# File: agent.py
# Created: 2026-03-29
# Purpose: Agent CRUD operations + identity lookup (DWB-289) + memory append (DWB-358) + project_agents bridge invariant (DWB-365)
# Caller: app/routers/agents.py
# Callees: app/models/agent.py, app/models/project.py, app/models/instruction.py, app/models/project_agent.py
# Data In: db: Session, AgentCreate/Update, identify params
# Data Out: list[Agent], Agent, identify payload
# Last Modified: 2026-06-10

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config.memory_rules import MEMORY_USAGE_RULES
from app.config.token_budget import ceiling_for_file, estimate_tokens
from app.models.agent import Agent
from app.models.instruction import Instruction, InstructionScope
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.schemas.agent import AgentCreate, AgentUpdate


def list_agents(
    db: Session,
    role: str | None = None,
    is_active: bool | None = None,
) -> list[Agent]:
    stmt = select(Agent)
    if role:
        stmt = stmt.where(Agent.role == role)
    if is_active is not None:
        stmt = stmt.where(Agent.is_active == is_active)
    stmt = stmt.order_by(Agent.created_at.desc())
    return list(db.scalars(stmt).all())


def get_agent(db: Session, agent_id: int) -> Agent | None:
    return db.get(Agent, agent_id)


def create_agent(db: Session, data: AgentCreate) -> Agent:
    agent = Agent(**data.model_dump())
    db.add(agent)
    db.flush()  # assign agent.id without committing

    # DWB-365: invariant - any agent with a project_id MUST have a matching
    # project_agents bridge row, inserted in the same transaction. FRAUDI
    # hit a case where 3 agents had agents.project_id set but no bridge
    # rows, so GET /api/projects/{id}/team returned empty. Bridging at
    # create-time means the team listing is consistent the moment the
    # agent row exists.
    if agent.project_id is not None:
        db.add(ProjectAgent(project_id=agent.project_id, agent_id=agent.id))

    db.commit()
    db.refresh(agent)
    # Best-effort scaffold of memory dir + identity.md (DWB-293).
    # Imported here to avoid a circular import with app.services.agent_memory.
    from app.services import agent_memory
    try:
        agent_memory.scaffold_agent_dir(db, agent.id)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "scaffold_agent_dir failed for agent_id=%s: %s", agent.id, e
        )
    return agent


def update_agent(db: Session, agent: Agent, data: AgentUpdate) -> Agent:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(db: Session, agent: Agent) -> None:
    # DWB-365: clear bridge rows first. The FK has no ON DELETE CASCADE and
    # the ORM relationship doesn't cascade either, so the default behavior
    # (NULL the FK) violates project_agents.agent_id NOT NULL.
    db.execute(delete(ProjectAgent).where(ProjectAgent.agent_id == agent.id))
    db.delete(agent)
    db.commit()


# --- /identify ---------------------------------------------------------------

_SCRATCHPAD_EXCERPT_BYTES = 2000


class IdentifyError(Exception):
    """Carries an explicit code so the router can map to a clean HTTP status."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def identify_agent(
    db: Session,
    *,
    role: str,
    name: str,
    project_prefix: str,
) -> dict:
    """Resolve an agent identity from (role, name, project_prefix).

    Raises IdentifyError with code in {"project_not_found", "agent_not_found",
    "ambiguous"} so the caller can produce 404/409. Role mismatch is non-fatal:
    the agent is returned and the role check is left to higher layers.
    """
    project = db.scalar(select(Project).where(Project.prefix == project_prefix))
    if project is None:
        raise IdentifyError("project_not_found", f"project prefix '{project_prefix}' not found")

    # DWB-315: agents.name is globally unique and fixed-role agents are now
    # suffixed with `_<PROJECT_PREFIX>` in storage (Archie_DWB, Pam_DWB).
    # Callers still pass the short name in the spawn brief — accept either
    # form to preserve back-compat.
    suffixed_name = f"{name}_{project.prefix}"
    matches = db.scalars(
        select(Agent).where(
            Agent.project_id == project.id,
            or_(Agent.name == name, Agent.name == suffixed_name),
        )
    ).all()
    if not matches:
        raise IdentifyError(
            "agent_not_found",
            f"no agent named '{name}' on project '{project_prefix}'",
        )
    if len(matches) > 1:
        # Should be unreachable post-DWB-315 UNIQUE(name), but the OR-match
        # could theoretically hit both `name` and `<name>_<prefix>` rows on a
        # mid-migration database. Keep the defensive raise.
        raise IdentifyError("ambiguous", "ambiguous, multiple matches")

    agent = matches[0]

    memory_dir = _memory_dir(project, agent)
    # Lazy self-heal: agents created before DWB-293 (or via any path that
    # bypassed the auto-scaffolder) get their memory_dir + identity.md on
    # first identify. Idempotent — scaffold preserves scratchpad/lessons.
    # Use identity.md as the marker (not the dir): session-complete creates
    # the dir without identity.md, and we want to backfill identity.md there.
    if project.repo_path and not (Path(memory_dir) / "identity.md").is_file():
        from app.services import agent_memory  # local import avoids circularity
        try:
            agent_memory.scaffold_agent_dir(db, agent.id)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "lazy scaffold from identify_agent failed for agent_id=%s: %s",
                agent.id, e,
            )
    scratchpad_excerpt = _read_scratchpad(memory_dir)
    instructions = _agent_visible_instructions(db, project.id, agent.id)

    return {
        "agent_id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "project_id": project.id,
        "project_prefix": project.prefix,
        # DWB-332: explicit jira_enabled flag so agents don't have to peek
        # at project.jira_base_url themselves.
        "jira_enabled": bool(project.jira_base_url),
        "memory_dir": memory_dir,
        "scratchpad_excerpt": scratchpad_excerpt,
        "instructions": instructions,
        # DWB-352: condensed memory-usage rules inline. Same constant the
        # spawn-prepare endpoint surfaces (single source of truth).
        "memory_usage_rules": MEMORY_USAGE_RULES,
    }


def _memory_dir(project: Project, agent: Agent) -> str:
    """Compute the canonical memory dir for an agent.

    Falls back to a `./` relative path when project.repo_path is unset so the
    response stays well-formed; DWB-293 will create the actual directory.
    """
    base = project.repo_path or "."
    return f"{base.rstrip('/')}/.claude/agents/memory/{project.prefix}/{agent.name}/"


def _read_scratchpad(memory_dir: str) -> str:
    path = Path(memory_dir) / "scratchpad.md"
    try:
        if path.is_file():
            data = path.read_text(encoding="utf-8", errors="replace")
            return data[-_SCRATCHPAD_EXCERPT_BYTES:]
    except OSError:
        # Unreadable file — surface an empty excerpt rather than 500. The
        # failed_hooks-style telemetry for filesystem issues is out of scope.
        pass
    return ""


def _agent_visible_instructions(
    db: Session, project_id: int, agent_id: int
) -> list[Instruction]:
    """All instructions an agent should see: global + their project + themselves."""
    stmt = (
        select(Instruction)
        .where(
            or_(
                Instruction.scope == InstructionScope.global_,
                (Instruction.scope == InstructionScope.project)
                & (Instruction.project_id == project_id),
                (Instruction.scope == InstructionScope.agent)
                & (Instruction.agent_id == agent_id),
            )
        )
        .order_by(Instruction.created_at.asc())
    )
    return list(db.scalars(stmt).all())


# --- /spawn-prepare ----------------------------------------------------------


def _boundary_instructions(
    db: Session, project_id: int, agent_id: int
) -> list[Instruction]:
    """Instructions an agent should treat as boundary rules.

    Matches identify's scope filter (global + project + agent) so identify and
    spawn-prepare stay consistent. Project rules are load-bearing here too —
    excluding them would create two surface areas with different filtering.
    """
    stmt = (
        select(Instruction)
        .where(
            or_(
                Instruction.scope == InstructionScope.global_,
                (Instruction.scope == InstructionScope.project)
                & (Instruction.project_id == project_id),
                (Instruction.scope == InstructionScope.agent)
                & (Instruction.agent_id == agent_id),
            )
        )
        .order_by(Instruction.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def spawn_prepare_payload(
    db: Session,
    *,
    role: str,
    name: str,
    project_prefix: str,
) -> dict:
    """Resolve identity + assemble the markdown prompt sections for spawning.

    Raises the same IdentifyError codes as identify_agent — the router maps
    them to 404/409 the same way.
    """
    project = db.scalar(select(Project).where(Project.prefix == project_prefix))
    if project is None:
        raise IdentifyError("project_not_found", f"project prefix '{project_prefix}' not found")

    # DWB-315: accept short name OR suffixed name (see identify_agent above).
    suffixed_name = f"{name}_{project.prefix}"
    matches = db.scalars(
        select(Agent).where(
            Agent.project_id == project.id,
            or_(Agent.name == name, Agent.name == suffixed_name),
        )
    ).all()
    if not matches:
        raise IdentifyError(
            "agent_not_found",
            f"no agent named '{name}' on project '{project_prefix}'",
        )
    if len(matches) > 1:
        raise IdentifyError("ambiguous", "ambiguous, multiple matches")

    agent = matches[0]

    # DWB-341: spawn-prepare hard-requires repo_path. The whole point of the
    # endpoint is to hand the TL a ready-to-spawn identity bundle, which
    # presumes the agent has a memory_dir on disk to read. Bailing here with
    # a clean 400 is better than the agent spawning into a void.
    if not project.repo_path:
        raise IdentifyError(
            "repo_path_missing",
            f"project '{project.prefix}' has no repo_path - cannot scaffold "
            f"memory dir for spawn (set project.repo_path first)",
        )

    # DWB-341: always scaffold on spawn-prepare. Idempotent by design -
    # identity.md is refreshed with current metadata; scratchpad/lessons/
    # recent_sessions are preserved byte-for-byte when present, created
    # empty when missing. Same dir path as identify_agent (keyed strictly
    # on agent.name; never suffixed with _v2/_1/etc).
    from app.services import agent_memory  # local import avoids circularity
    try:
        agent_memory.scaffold_agent_dir(db, agent.id)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "spawn-prepare scaffold failed for agent_id=%s: %s", agent.id, e
        )

    memory_dir = _memory_dir(project, agent)

    identity_prompt = (
        "## Identity\n"
        f"- agent_id: {agent.id}\n"
        f"- name: {agent.name}\n"
        f"- role: {agent.role}\n"
        f"- project: {project.prefix} ({project.name})\n"
        f"- memory_dir: {memory_dir}\n"
    )

    scratchpad_raw = _read_scratchpad(memory_dir)
    scratchpad_section = (
        "## Recent Scratchpad\n"
        + (scratchpad_raw if scratchpad_raw else "(no entries yet)\n")
    )

    rules = _boundary_instructions(db, project.id, agent.id)
    if rules:
        rule_lines = "\n".join(
            f"- **{r.title}** (scope: {r.scope.value}): {r.body}" for r in rules
        )
    else:
        rule_lines = "(no boundary rules)"
    boundary_section = f"## Boundary Rules\n{rule_lines}\n"

    return {
        "agent_id": agent.id,
        "identity_prompt": identity_prompt,
        "scratchpad_excerpt": scratchpad_section,
        "boundary_rules": boundary_section,
        # DWB-341: absolute memory_dir path so callers can reason about
        # where the agent's files live without having to rebuild it.
        "memory_dir": memory_dir,
        # DWB-352: condensed memory-usage rules inline (same single source
        # of truth that identify surfaces).
        "memory_usage_rules": MEMORY_USAGE_RULES,
    }


# --- /{id}/session-complete --------------------------------------------------


class SessionCompleteError(Exception):
    """Raised when session-complete can't resolve or write."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def record_session_complete(
    db: Session,
    *,
    agent_id: int,
    session_id: str,
    summary: str,
    lessons: list[str] | None = None,
    tokens_used: int | None = None,
) -> dict:
    """Append an ISO 8601 timestamped entry to the agent's scratchpad + recent_sessions.

    Creates the memory dir if missing (a thin precursor to DWB-293's full
    scaffolder — keeps this endpoint usable on a fresh agent).
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise SessionCompleteError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise SessionCompleteError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id — cannot resolve memory_dir",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise SessionCompleteError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )

    memory_dir = Path(_memory_dir(project, agent))
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SessionCompleteError(
            "memory_dir_unwritable",
            f"could not create memory dir {memory_dir}: {e}",
        )

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Always-written files
    writes: list[tuple[Path, str]] = [
        (
            memory_dir / "scratchpad.md",
            _format_scratchpad_block(
                timestamp=timestamp,
                session_id=session_id,
                summary=summary,
                lessons=lessons,
                tokens_used=tokens_used,
            ),
        ),
        (
            memory_dir / "recent_sessions.md",
            _format_recent_session_line(
                timestamp=timestamp,
                session_id=session_id,
                summary=summary,
                tokens_used=tokens_used,
            ),
        ),
    ]
    # lessons.md is only touched when lessons[] is present.
    if lessons:
        writes.append(
            (
                memory_dir / "lessons.md",
                _format_lessons_block(
                    timestamp=timestamp,
                    session_id=session_id,
                    lessons=lessons,
                ),
            )
        )

    paths_written: list[str] = []
    bytes_written = 0
    try:
        for path, payload in writes:
            with path.open("a", encoding="utf-8") as f:
                f.write(payload)
            paths_written.append(str(path))
            bytes_written += len(payload.encode("utf-8"))
    except OSError as e:
        raise SessionCompleteError(
            "memory_dir_unwritable",
            f"could not append to memory files in {memory_dir}: {e}",
        )

    return {
        "agent_id": agent.id,
        "session_id": session_id,
        "timestamp": timestamp,
        "paths_written": paths_written,
        "bytes_written": bytes_written,
    }


def _format_scratchpad_block(
    *,
    timestamp: str,
    session_id: str,
    summary: str,
    lessons: list[str] | None,
    tokens_used: int | None,
) -> str:
    lines = [
        f"\n## {timestamp} — session {session_id}\n",
        f"- summary: {summary}\n",
    ]
    if tokens_used is not None:
        lines.append(f"- tokens_used: {tokens_used}\n")
    if lessons:
        lines.append("- lessons:\n")
        for item in lessons:
            lines.append(f"  - {item}\n")
    return "".join(lines)


def _format_recent_session_line(
    *,
    timestamp: str,
    session_id: str,
    summary: str,
    tokens_used: int | None,
) -> str:
    tok = f" ({tokens_used} tok)" if tokens_used is not None else ""
    summary_oneline = summary.replace("\n", " ").strip()
    return f"- {timestamp} `{session_id}`{tok}: {summary_oneline}\n"


def _format_lessons_block(
    *,
    timestamp: str,
    session_id: str,
    lessons: list[str],
) -> str:
    """Lessons.md entry per session — one block, one bullet per lesson."""
    lines = [f"\n## {timestamp} — session {session_id}\n"]
    for item in lessons:
        lines.append(f"- {item}\n")
    return "".join(lines)


# --- /{id}/memory/append (DWB-358) -------------------------------------------


# Filenames the memory-append endpoint will write to. identity.md is
# intentionally absent - it is system-generated by the scaffolder and
# must not be touched by an in-flight append. The three allowed
# basenames match the agent-owned files scaffold_agent_dir creates
# alongside identity.md (see app.services.agent_memory._AGENT_OWNED_FILES).
_APPENDABLE_FILES = {"scratchpad", "lessons", "recent_sessions"}
_PROTECTED_FILES = {"identity"}


class MemoryAppendError(Exception):
    """Raised when the memory-append endpoint cannot resolve, validate, or write.

    code is one of:
      - agent_not_found
      - agent_unscoped       (agent has no project_id - legacy / soft-deactivated row)
      - project_not_found
      - repo_path_missing    (project.repo_path is null)
      - invalid_file         (file name not in the whitelist)
      - file_protected       (caller targeted identity.md)
      - empty_content        (content empty or whitespace-only)
      - memory_dir_unwritable
      - memory_file_unwritable
    """

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _format_memory_append_block(
    *,
    timestamp: str,
    content: str,
    session_id: str | None,
) -> str:
    """Build the block appended to a memory file.

    Heading mirrors record_session_complete's format ('## ISO8601' optionally
    followed by ' - session <id>') so a human reading scratchpad.md after
    both endpoints have written can't tell them apart by formatting. A
    leading newline ensures the block is visually separated from whatever
    was already in the file; a trailing newline guarantees the next
    append starts on its own line.
    """
    if session_id and session_id.strip():
        heading = f"\n## {timestamp} - session {session_id.strip()}\n"
    else:
        heading = f"\n## {timestamp}\n"
    body = content.rstrip("\n") + "\n"
    return heading + body


def append_memory(
    db: Session,
    *,
    agent_id: int,
    file: str,
    content: str,
    session_id: str | None = None,
) -> dict:
    """Server-side append to the agent's scratchpad / lessons / recent_sessions
    memory file (DWB-358).

    The Claude Code subagent ink renderer crashes on permission prompts for
    edits under .claude/, which means agents cannot Edit/Write their own
    memory files mid-session. This endpoint runs in the FastAPI process
    (no permission prompt) and performs the append on the agent's behalf.

    Idempotent with DWB-341 scaffold: if the memory dir or target file is
    missing (e.g. on a freshly cloned repo) the directory + empty file are
    created before the append.

    Refuses identity.md (the scaffolder regenerates it; an arbitrary
    append would be reverted on the next spawn-prepare). Empty content is
    refused so a stray POST cannot pollute the file with bare timestamp
    headings.

    Raises MemoryAppendError with a code the router maps to 400 / 404 /
    500. Returns a small dict with the resolved path and bytes_written
    for telemetry.
    """
    if file in _PROTECTED_FILES:
        raise MemoryAppendError(
            "file_protected",
            f"file '{file}.md' is system-generated and cannot be appended to "
            f"(scaffold regenerates it; use scratchpad/lessons/recent_sessions instead)",
        )
    if file not in _APPENDABLE_FILES:
        raise MemoryAppendError(
            "invalid_file",
            f"file '{file}' is not appendable; "
            f"allowed: {sorted(_APPENDABLE_FILES)}",
        )
    if not content or not content.strip():
        raise MemoryAppendError(
            "empty_content",
            "content is empty or whitespace-only; refusing to write a "
            "bare timestamp heading",
        )

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise MemoryAppendError(
            "agent_not_found", f"agent id {agent_id} not found"
        )
    if agent.project_id is None:
        raise MemoryAppendError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id - cannot resolve memory_dir",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise MemoryAppendError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )
    if not project.repo_path:
        raise MemoryAppendError(
            "repo_path_missing",
            f"project '{project.prefix}' has no repo_path - "
            f"cannot resolve memory_dir for append",
        )

    memory_dir = Path(_memory_dir(project, agent))
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MemoryAppendError(
            "memory_dir_unwritable",
            f"could not create memory dir {memory_dir}: {e}",
        )

    target = memory_dir / f"{file}.md"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    block = _format_memory_append_block(
        timestamp=timestamp,
        content=content,
        session_id=session_id,
    )

    try:
        with target.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        raise MemoryAppendError(
            "memory_file_unwritable",
            f"could not append to {target}: {e}",
        )

    return {
        "agent_id": agent.id,
        "file": file,
        "path": str(target),
        "timestamp": timestamp,
        "bytes_written": len(block.encode("utf-8")),
    }


class MemoryCompactError(Exception):
    """Raised when the memory-compact (replace) endpoint cannot validate or write.

    code is one of:
      - agent_not_found / agent_unscoped / project_not_found / repo_path_missing
      - invalid_file / file_protected / empty_content
      - still_over_ceiling   (compacted content still exceeds the file's ceiling)
      - memory_dir_unwritable / memory_file_unwritable
    """

    def __init__(self, code: str, detail: str, *, tokens: int | None = None,
                 ceiling: int | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.tokens = tokens
        self.ceiling = ceiling


def compact_memory(
    db: Session,
    *,
    agent_id: int,
    file: str,
    content: str,
) -> dict:
    """Replace (compact) one of the agent's memory files with a leaner version.

    The memory-append endpoint is append-only by design; compaction is a
    *rewrite*, so this is its own endpoint. The agent reads its bloated file,
    produces a compacted full-file replacement, and submits it here. The
    server overwrites the file on the agent's behalf (same .claude/-write
    workaround as append_memory) — but ONLY if the compacted content is within
    the file's token ceiling. If it is still over, the write is refused with
    ``still_over_ceiling`` so the gate cannot be satisfied by a no-op; the
    agent must trim further and resubmit. This refusal is the hard gate.

    identity.md is protected (scaffold owns it). Empty content is refused so a
    file cannot be blanked to pass the ceiling.
    """
    if file in _PROTECTED_FILES:
        raise MemoryCompactError(
            "file_protected",
            f"file '{file}.md' is system-generated and cannot be compacted "
            f"(scaffold regenerates it)",
        )
    if file not in _APPENDABLE_FILES:
        raise MemoryCompactError(
            "invalid_file",
            f"file '{file}' is not a compactable memory file; "
            f"allowed: {sorted(_APPENDABLE_FILES)}",
        )
    if not content or not content.strip():
        raise MemoryCompactError(
            "empty_content",
            "content is empty or whitespace-only; refusing to blank the file "
            "to pass the ceiling — compaction must preserve real content",
        )

    fname = f"{file}.md"
    tokens = estimate_tokens(content)
    ceiling = ceiling_for_file(fname)
    if tokens > ceiling:
        raise MemoryCompactError(
            "still_over_ceiling",
            f"compacted {fname} is ~{tokens} tokens but the ceiling is "
            f"{ceiling}; trim further (dedupe, drop superseded entries, "
            f"summarise) and resubmit",
            tokens=tokens,
            ceiling=ceiling,
        )

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise MemoryCompactError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise MemoryCompactError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id - cannot resolve memory_dir",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise MemoryCompactError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )
    if not project.repo_path:
        raise MemoryCompactError(
            "repo_path_missing",
            f"project '{project.prefix}' has no repo_path - cannot resolve memory_dir",
        )

    memory_dir = Path(_memory_dir(project, agent))
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MemoryCompactError(
            "memory_dir_unwritable",
            f"could not create memory dir {memory_dir}: {e}",
        )

    target = memory_dir / fname
    normalized = content.rstrip("\n") + "\n"
    try:
        target.write_text(normalized, encoding="utf-8")
    except OSError as e:
        raise MemoryCompactError(
            "memory_file_unwritable", f"could not write {target}: {e}"
        )

    return {
        "agent_id": agent.id,
        "file": file,
        "path": str(target),
        "tokens": tokens,
        "ceiling": ceiling,
        "bytes_written": len(normalized.encode("utf-8")),
    }


# --- /{id}/marker ------------------------------------------------------------


class MarkerError(Exception):
    """Raised when the marker endpoint cannot resolve or write."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def write_session_marker(
    db: Session,
    *,
    agent_id: int,
    session_id: str,
) -> dict:
    """Write the session marker file the hook resolver reads (DWB-307).

    The marker lives at:
        <project.repo_path>/.claude/agents/active/<session_id>

    Body is a JSON dict matching what `resolve_agent_from_marker` accepts:
        {"agent_id": N, "agent_name": "...", "role": "...", "project_prefix": "..."}

    Centralising the write here means TLs no longer hand-roll JSON (and
    no longer trip the "single-line int" doc trap — see DWB-307 description).
    """
    if not session_id or not session_id.strip():
        raise MarkerError("session_id_required", "session_id is required")

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise MarkerError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise MarkerError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id — cannot resolve repo_path",
        )

    project = db.get(Project, agent.project_id)
    if project is None:
        raise MarkerError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )
    if not project.repo_path:
        raise MarkerError(
            "repo_path_missing",
            f"project {project.prefix} has no repo_path — set it before writing markers",
        )

    marker_dir = Path(project.repo_path) / ".claude" / "agents" / "active"
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MarkerError(
            "marker_dir_unwritable",
            f"could not create marker dir {marker_dir}: {e}",
        )

    marker_path = marker_dir / session_id
    payload = json.dumps(
        {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "role": agent.role,
            "project_prefix": project.prefix,
        }
    )
    try:
        marker_path.write_text(payload, encoding="utf-8")
    except OSError as e:
        raise MarkerError(
            "marker_unwritable",
            f"could not write marker to {marker_path}: {e}",
        )

    return {
        "agent_id": agent.id,
        "session_id": session_id,
        "marker_path": str(marker_path),
        "bytes_written": len(payload.encode("utf-8")),
    }

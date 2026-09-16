# Path: app/services/agent.py
# File: agent.py
# Created: 2026-03-29
# Purpose: Agent CRUD operations + identity lookup (DWB-289) + memory append/compact/condense (DWB-358/518) + full-memory read for spawn/hook injection (DWB-517) + project_agents bridge invariant (DWB-365)
# Caller: app/routers/agents.py
# Callees: app/models/agent.py, app/models/project.py, app/models/instruction.py, app/models/project_agent.py
# Data In: db: Session, AgentCreate/Update, identify params
# Data Out: list[Agent], Agent, identify payload
# Last Modified: 2026-09-15 (DWB-560: session-complete writes durable lessons only, never narration)

import json
import logging
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

logger = logging.getLogger(__name__)


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
    # DWB-401: memory relocated out of the protected .claude/ tree into .dwb/
    # (subagent writes under .claude/ crash the CC renderer; .dwb is writable).
    return f"{base.rstrip('/')}/.dwb/memory/{project.prefix}/{agent.name}/"


def _read_scratchpad(memory_dir: str) -> str:
    # DWB-401: the single free-form file is now memory.md (scratchpad + lessons
    # merged; recent_sessions dropped). Key name kept as scratchpad_excerpt for
    # API stability; it now surfaces memory.md.
    path = Path(memory_dir) / "memory.md"
    try:
        if path.is_file():
            data = path.read_text(encoding="utf-8", errors="replace")
            return data[-_SCRATCHPAD_EXCERPT_BYTES:]
    except OSError:
        # Unreadable file — surface an empty excerpt rather than 500. The
        # failed_hooks-style telemetry for filesystem issues is out of scope.
        pass
    return ""


def _read_memory_full(memory_dir: str) -> str:
    """DWB-517: the agent's FULL memory.md, verbatim (no truncation).

    Powers passive memory injection - spawn-prepare hands the TL the whole
    file to paste into the spawn prompt, and the SessionStart hook injects a
    TL's own memory into context. Degrades to an empty string when the file is
    missing or unreadable; never raises (the callers are a spawn helper and a
    fire-and-forget hook, neither of which may 500 on a filesystem hiccup)."""
    path = Path(memory_dir) / "memory.md"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def tl_memory_for_project(db: Session, project_id: int) -> str:
    """DWB-517: full memory.md of a project's team-lead, or "" when there is no
    TL, no repo_path, or no memory yet.

    Used by the SessionStart hook lane so an archie's own memory lands in
    context at session start with zero action. Best-effort and non-raising:
    the hook endpoint must never 5xx, so any resolution/read miss degrades to
    an empty string (which the caller treats as "inject nothing")."""
    project = db.get(Project, project_id)
    if project is None or not project.repo_path:
        return ""
    tl = db.scalar(
        select(Agent)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == "team-lead")
        .limit(1)
    )
    if tl is None:
        return ""
    return _read_memory_full(_memory_dir(project, tl))


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
    # DWB-517: the FULL memory.md, verbatim, so the TL injects it into the spawn
    # prompt without the agent having to read it. Empty string when none yet.
    memory_full = _read_memory_full(memory_dir)

    rules = _boundary_instructions(db, project.id, agent.id)
    if rules:
        rule_lines = "\n".join(
            f"- **{r.title}** (scope: {r.scope.value}): {r.body}" for r in rules
        )
    else:
        rule_lines = "(no boundary rules)"
    boundary_section = f"## Boundary Rules\n{rule_lines}\n"

    # DWB-524: retrieval into work. Match the agent's assigned/queued ticket text
    # against the node graph and surface memory-domain lessons from OTHER agents
    # (pointers only; the TL pastes these alongside memory_full). Best-effort - a
    # retrieval failure or empty corpus degrades to an empty list, never blocks
    # the spawn bundle.
    from app.services import node_retrieval
    try:
        lessons = node_retrieval.relevant_lessons(db, project, agent)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "spawn-prepare relevant_lessons failed for agent_id=%s", agent.id,
            exc_info=True,
        )
        lessons = []

    return {
        "agent_id": agent.id,
        "identity_prompt": identity_prompt,
        "scratchpad_excerpt": scratchpad_section,
        # DWB-517: full memory.md verbatim (kept alongside the excerpt for
        # compat) so the TL can inject the whole file into the spawn prompt.
        "memory_full": memory_full,
        # DWB-524: pointer-only relevant lessons from other agents' memories.
        "relevant_lessons": lessons,
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
    """Raised when session-complete can't resolve or write.

    DWB-518: adds the ``over_ceiling`` code (the wrap-up block would push
    memory.md past its token ceiling) carrying tokens + ceiling for the
    actionable refusal message.
    """

    def __init__(self, code: str, detail: str, *, tokens: int | None = None,
                 ceiling: int | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.tokens = tokens
        self.ceiling = ceiling


# DWB-518: the memory ceiling is a HARD gate now, not a silent trim. When a
# write would exceed it the server refuses and tells the agent to condense
# first and retry - refusal is the signal, never "wait".
def _memory_over_ceiling_detail(agent_id: int, tokens: int, ceiling: int) -> str:
    return (
        f"memory.md would be ~{tokens} tokens, over its {ceiling}-token ceiling. "
        f"The write was refused: nothing was dropped. Condense first, then retry - "
        f"POST /api/agents/{agent_id}/memory/condense with a rewritten memory.md "
        f"under {ceiling} tokens (the server stamps a condensed-at heading and "
        f"replaces the file). Do not wait; condense and resend."
    )


def record_session_complete(
    db: Session,
    *,
    agent_id: int,
    session_id: str,
    summary: str,
    lessons: list[str] | None = None,
    tokens_used: int | None = None,
) -> dict:
    """Record a session wrap-up. DWB-560: memory.md gets LESSONS ONLY.

    The summary and token count are part of the endpoint contract and reach the
    caller (and the database's own session record), but they are no longer
    written into memory.md: the dwb_sessions row with its headline, summary and
    keyword tags already IS the session record, and duplicating it there ate the
    memory ceiling. The ISO heading is still written every time, with or without
    lessons, because the DWB-519 write-on-close gate reads those headings to
    decide who participated in a sprint; an agent whose only memory activity was
    a session-complete must still pass it.

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

    # DWB-401: single free-form memory.md.
    # DWB-560: the block is LESSONS ONLY - no summary, no token count, no
    # status narration - but the ISO heading always lands so the DWB-519
    # write-on-close gate still sees the participation it reads memory for.
    target = memory_dir / "memory.md"
    payload = _format_scratchpad_block(
        timestamp=timestamp,
        session_id=session_id,
        summary=summary,
        lessons=lessons,
        tokens_used=tokens_used,
    )

    paths_written: list[str] = []
    bytes_written = 0

    if payload:
        # DWB-518: no silent trim. Refuse if the wrap-up block would push
        # memory.md over its ceiling; the agent condenses first, then re-calls.
        ceiling = ceiling_for_file("memory.md")
        projected = estimate_tokens(_read_text_safe(target) + payload)
        if projected > ceiling:
            raise SessionCompleteError(
                "over_ceiling",
                _memory_over_ceiling_detail(agent.id, projected, ceiling),
                tokens=projected,
                ceiling=ceiling,
            )

        try:
            with target.open("a", encoding="utf-8") as f:
                f.write(payload)
            paths_written.append(str(target))
            bytes_written += len(payload.encode("utf-8"))
        except OSError as e:
            raise SessionCompleteError(
                "memory_dir_unwritable",
                f"could not append to memory files in {memory_dir}: {e}",
            )

        _touch_memory_nodes(db, project, target)

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
    """DWB-560: memory.md holds DURABLE LESSONS ONLY.

    Miles ruling: boring "I did 50 tickets, their names were, their ids are,
    the time completed was" is noise. The dwb_sessions row, with its generated
    headline, summary and keyword tags, IS the session record; duplicating it
    in memory burned the 4500-token ceiling and forced condense rewrites that
    can summarise a real lesson away (eight condenses across five agents in one
    night). So the summary and the token count no longer reach the file: they
    still travel to the caller and the database.

    The ISO heading is ALWAYS written, lessons or not. It is structural, not
    narration (every memory write stamps one), and it is precisely what the
    DWB-519 write-on-close gate reads as the participation trace
    (services/memory_trace.py::latest_memory_write_at). Dropping it for a
    lessons-free wrap-up would silently fail the gate for an agent who did
    everything right and simply had no durable lesson that sprint, and it would
    present as a missing acknowledgement rather than as this side effect. Two
    lines of heading is a cheap price for a gate that cannot lie.

    `summary` and `tokens_used` stay in the signature because the endpoint
    contract still accepts them; they are deliberately unused here.
    """
    lines = [f"\n## {timestamp} — session {session_id}\n"]
    if lessons:
        lines.append("- lessons:\n")
        for item in lessons:
            lines.append(f"  - {item}\n")
    return "".join(lines)


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# DWB-518: the passive oldest-entry trim (_passive_trim_memory) was removed.
# Per the Miles ruling there is no silent eviction: an over-ceiling write is
# refused (append / session-complete -> 400) and the agent condenses via the
# condense endpoint. No code path drops memory entries anymore.


# --- /{id}/memory/append (DWB-358) -------------------------------------------


# Filenames the memory-append endpoint will write to. identity.md is
# intentionally absent - it is system-generated by the scaffolder and
# must not be touched by an in-flight append. The three allowed
# basenames match the agent-owned files scaffold_agent_dir creates
# alongside identity.md (see app.services.agent_memory._AGENT_OWNED_FILES).
# DWB-401: collapsed to the single free-form memory.md. identity.md remains
# system-generated and protected.
_APPENDABLE_FILES = {"memory"}
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
      - over_ceiling         (DWB-518: the append would exceed memory.md's ceiling)
      - memory_dir_unwritable
      - memory_file_unwritable
    """

    def __init__(self, code: str, detail: str, *, tokens: int | None = None,
                 ceiling: int | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.tokens = tokens
        self.ceiling = ceiling


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


def _touch_memory_nodes(db: Session, project: Project, target: Path) -> None:
    """DWB-527: re-ground the memory-domain node pointers for this memory.md
    after a successful write. Best-effort - a node failure must never break the
    memory write, so all errors are swallowed here + inside touch_memory."""
    try:
        from app.services import node_touch  # local: avoid import cycle
        node_touch.touch_memory(
            db,
            project_id=project.id,
            repo_path=project.repo_path,
            memory_file=target,
        )
    except Exception:
        logger.warning(
            "node touch failed for memory %s; skipping", target, exc_info=True
        )


def _evaluate_redemption_safe(
    db: Session, *, agent: Agent, project: Project,
    caller_agent_id: int | None, content: str,
) -> dict:
    """DWB-537: run the stick-redemption check AFTER a successful append.
    Best-effort: the append has already landed and must return 201, so any
    unexpected failure here becomes a not-granted verdict, never a 500."""
    try:
        from app.services import stick_redemption  # local: avoid import cycle
        return stick_redemption.evaluate_redemption(
            db, agent=agent, project=project,
            caller_agent_id=caller_agent_id, content=content,
        )
    except Exception:
        logger.warning(
            "redemption check failed for agent %s; append kept", agent.id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return {"granted": False, "reason": "redemption check failed; append kept"}


def append_memory(
    db: Session,
    *,
    agent_id: int,
    file: str,
    content: str,
    session_id: str | None = None,
    caller_agent_id: int | None = None,
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

    DWB-537: after the write succeeds the body is scanned for a
    ``redeem:<score_event_id>`` token and the stick-redemption chain runs
    (services/stick_redemption.py). ``caller_agent_id`` is the X-Agent-ID
    header; it must equal ``agent_id`` for a grant. The verdict is returned
    under ``redemption`` and never affects the append's success.

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

    # DWB-518: no silent trim. If appending this block would push memory.md over
    # its ceiling, refuse (nothing is dropped); the agent condenses first, then
    # retries. Refusal is the signal.
    ceiling = ceiling_for_file(f"{file}.md")
    projected = estimate_tokens(_read_text_safe(target) + block)
    if projected > ceiling:
        raise MemoryAppendError(
            "over_ceiling",
            _memory_over_ceiling_detail(agent.id, projected, ceiling),
            tokens=projected,
            ceiling=ceiling,
        )

    try:
        with target.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        raise MemoryAppendError(
            "memory_file_unwritable",
            f"could not append to {target}: {e}",
        )

    _touch_memory_nodes(db, project, target)

    redemption = _evaluate_redemption_safe(
        db, agent=agent, project=project,
        caller_agent_id=caller_agent_id, content=content,
    )

    return {
        "agent_id": agent.id,
        "file": file,
        "path": str(target),
        "timestamp": timestamp,
        "bytes_written": len(block.encode("utf-8")),
        "redemption": redemption,
    }


# --- GET /{id}/memory (DWB-532) ----------------------------------------------


class MemoryReadError(Exception):
    """Raised when GET /api/agents/{id}/memory cannot resolve the file.

    code is one of:
      - agent_not_found / agent_unscoped / project_not_found / repo_path_missing
      - memory_missing        (memory.md does not exist for this agent)
      - memory_unreadable     (exists but could not be read)
    """

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def read_memory(db: Session, *, agent_id: int) -> dict:
    """DWB-532: the agent's memory.md verbatim plus the SERVER's token estimate.

    The 4500-token ceiling that append / session-complete / condense enforce
    is measured with config.token_budget.estimate_tokens; until now an agent
    condensing against it could only guess the count. This returns the same
    estimator's number for the file as it stands, the ceiling, and the
    headroom (ceiling - est_tokens, negative when already over), so a condense
    can be sized in one shot and a mid-session refresh after context
    compaction can re-read memory through the API instead of raw disk.
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise MemoryReadError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise MemoryReadError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id - cannot resolve memory_dir",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise MemoryReadError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )
    if not project.repo_path:
        raise MemoryReadError(
            "repo_path_missing",
            f"project '{project.prefix}' has no repo_path - cannot resolve memory_dir",
        )

    path = Path(_memory_dir(project, agent)) / "memory.md"
    if not path.is_file():
        raise MemoryReadError(
            "memory_missing",
            f"agent {agent.name} (id {agent.id}) has no memory.md at {path}",
        )
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise MemoryReadError("memory_unreadable", f"could not read {path}: {e}")

    ceiling = ceiling_for_file("memory.md")
    est = estimate_tokens(content)
    return {
        "content": content,
        "est_tokens": est,
        "ceiling": ceiling,
        "headroom": ceiling - est,
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


class MemoryCondenseError(Exception):
    """Raised when the memory-condense (DWB-518) endpoint cannot validate or write.

    Same code set as MemoryCompactError; ``still_over_ceiling`` carries the
    submitted content's tokens + the ceiling for the actionable refusal.
    """

    def __init__(self, code: str, detail: str, *, tokens: int | None = None,
                 ceiling: int | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.tokens = tokens
        self.ceiling = ceiling


def _replace_memory(
    db: Session,
    *,
    agent_id: int,
    file: str,
    content: str,
    heading: str | None,
    err_cls: type,
) -> dict:
    """Shared full-file REPLACE for the compact + condense endpoints.

    DWB-518: the memory ceiling is a HARD gate, not a silent trim. The final
    text (optional ``heading`` prepended + the submitted body) is measured; if
    it exceeds the file's ceiling the write is REFUSED with ``still_over_ceiling``
    and nothing is written - the agent must trim further and resubmit. identity.md
    is protected; empty content is refused so the file cannot be blanked to pass.
    ``err_cls`` is the exception type the caller wants raised (MemoryCompactError
    or MemoryCondenseError) so each endpoint keeps its own typed errors.
    """
    if file in _PROTECTED_FILES:
        raise err_cls(
            "file_protected",
            f"file '{file}.md' is system-generated and cannot be replaced "
            f"(scaffold regenerates it)",
        )
    if file not in _APPENDABLE_FILES:
        raise err_cls(
            "invalid_file",
            f"file '{file}' is not a rewritable memory file; "
            f"allowed: {sorted(_APPENDABLE_FILES)}",
        )
    if not content or not content.strip():
        raise err_cls(
            "empty_content",
            "content is empty or whitespace-only; refusing to blank the file "
            "to pass the ceiling — the rewrite must preserve real content",
        )

    fname = f"{file}.md"
    ceiling = ceiling_for_file(fname)

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise err_cls("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise err_cls(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id - cannot resolve memory_dir",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise err_cls(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )
    if not project.repo_path:
        raise err_cls(
            "repo_path_missing",
            f"project '{project.prefix}' has no repo_path - cannot resolve memory_dir",
        )

    body = content.rstrip("\n") + "\n"
    final_text = (heading + body) if heading else body

    # DWB-518: hard ceiling. A rewrite that is still over is refused, not trimmed.
    tokens = estimate_tokens(final_text)
    if tokens > ceiling:
        raise err_cls(
            "still_over_ceiling",
            f"the rewritten memory.md is still ~{tokens} tokens, over its "
            f"{ceiling}-token ceiling. Nothing was written. Trim further and "
            f"resubmit under {ceiling} tokens.",
            tokens=tokens,
            ceiling=ceiling,
        )

    memory_dir = Path(_memory_dir(project, agent))
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise err_cls(
            "memory_dir_unwritable",
            f"could not create memory dir {memory_dir}: {e}",
        )

    target = memory_dir / fname
    try:
        target.write_text(final_text, encoding="utf-8")
    except OSError as e:
        raise err_cls("memory_file_unwritable", f"could not write {target}: {e}")

    _touch_memory_nodes(db, project, target)

    return {
        "agent_id": agent.id,
        "file": file,
        "path": str(target),
        "tokens": tokens,
        "ceiling": ceiling,
        "bytes_written": len(final_text.encode("utf-8")),
    }


def compact_memory(
    db: Session,
    *,
    agent_id: int,
    file: str,
    content: str,
) -> dict:
    """Replace (compact) the agent's memory.md with a leaner version, verbatim.

    Full-file REPLACE (not append): the agent submits the rewritten content and
    the server overwrites the file (same .claude/-write workaround as append) -
    ONLY if it is within the token ceiling. DWB-518: over-ceiling is REFUSED with
    ``still_over_ceiling`` (was a silent trim under DWB-401); nothing is dropped.
    identity.md is protected; empty content is refused. No heading is stamped
    (the agent's content is written as-is); the condense endpoint is the
    heading-stamped sibling.

    DWB-564: because no heading is stamped, a compact leaves NOTHING in
    memory.md that memory_trace.agent_wrote_since can match. An agent whose
    only memory activity in a window is a compact reads as a non-writer at
    sprint/session close regardless of when the compact happened. This is a
    sharper version of the same coupling condense_memory's docstring
    describes — see that note before changing either function's heading
    behavior.
    """
    return _replace_memory(
        db, agent_id=agent_id, file=file, content=content,
        heading=None, err_cls=MemoryCompactError,
    )


def condense_memory(
    db: Session,
    *,
    agent_id: int,
    file: str,
    content: str,
) -> dict:
    """DWB-518: the sanctioned memory rewrite. Full-file REPLACE of memory.md
    with a server-stamped ISO condensed-at heading, validated under the ceiling.

    This is the path the over-ceiling append/session-complete refusal points at:
    the agent reads its full memory (now force-injected at spawn, DWB-517),
    rewrites it leaner, and submits here. The server prepends
    ``## <ISO8601> - condensed`` so the provenance of the rewrite is on the
    record, then replaces the file. Refused with ``still_over_ceiling`` if the
    submission is itself over ceiling (trim more and resubmit); identity.md is
    protected; empty content is refused.

    DWB-564: this stamped heading is LOAD-BEARING for the DWB-519 write-on-close
    gate (services/memory_trace.py::agent_wrote_since), not just provenance. A
    condense legitimately replaces every dated heading in memory.md with topic
    headings ("Epic routing", "Memory mechanics", ...) that the gate's regex does
    not match — DWB-560 actively encourages exactly that shape. The ONLY reason
    a condensing agent still passes the gate today is that this heading happens
    to satisfy memory_trace._HEADING_RE. If this stamp's shape changes, or a
    caller reaches for compact_memory instead (which stamps no heading at all —
    see its docstring), a condensing agent who did everything right fails the
    gate as a silent non-writer. Pinned by
    test_condense_write_gate_coupling_dwb564.py; do not change this heading's
    shape without checking that test.
    """
    condensed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    heading = f"## {condensed_at} - condensed\n"
    result = _replace_memory(
        db, agent_id=agent_id, file=file, content=content,
        heading=heading, err_cls=MemoryCondenseError,
    )
    result["condensed_at"] = condensed_at
    return result


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

# Path: app/services/session_narrative.py
# File: session_narrative.py
# Created: 2026-06-25
# Purpose: DWBG-014 — the summarizer. Feed a DWBG-013 work record to a pluggable
#          inference backend and get back a human-readable session wrap-up narrative
#          (thematic title + lead + grounded prose bullets + honest caveat) in the
#          SessionSummary JSON shape {lead, sections:[{title,bullets}]}. DWBG-017:
#          provider-agnostic — builds the prompt, calls get_provider().complete(),
#          parses. Best-effort: never raises, never blocks a close. Output is routed
#          through DWBG-008 redaction by the caller before persist.
# Caller: app/services/dwb_session.py (close_session auto-gen), app/routers/dwb_sessions.py
#         (POST /api/sessions/{id}/generate-narrative on-demand/regenerate)
# Callees: app.services.summarizer_providers (get_provider + NarrativeProvider),
#          app.services.session_work_record
# Data In: a DWBG-013 work record dict
# Data Out: narrative dict {lead, sections:[{title,bullets}]} or None on any failure
# Last Modified: 2026-06-25 (DWBG-017 abstracted inference behind a provider seam)

"""DWBG-014 — session wrap-up summarizer (the headline feature).

``generate_narrative(work_record)`` builds a prompt from the work record (git
commits + diffs primary, plus tool actions, completed tickets, and a bounded
agent-only transcript slice), asks the selected inference backend for a readable
wrap-up "story" of the session — grounded in real specifics like code symbols,
file:line refs, concrete facts, ending with an honest caveat — and parses the
result into the narrative JSON shape the SessionSummary component renders:
``{lead, sections:[{title,bullets}]}``.

DWBG-017: this module is PROVIDER-AGNOSTIC. It does not know or care which
inference backend runs — it builds the prompt, calls
``get_provider().complete(system=..., user=..., max_tokens=...)``, and parses the
returned text. The backend (Ollama by default, Anthropic, or the MLX stub) is
chosen by ``DWB_SUMMARIZER_PROVIDER`` inside the factory. Prompt text, the
parsing contract, and the best-effort behavior are unchanged from DWBG-014.

BEST-EFFORT (like the P1 narrative): this function NEVER raises. If the provider
returns ``None`` (backend unreachable / no key / SDK missing / call errored) or
the response can't be parsed, it logs and returns None — the caller closes
cleanly with the deterministic summary baseline and no narrative.

This is NOT a stats table — ticket counts already live in the deterministic
summary. The value here is the readable, grounded story.
"""

from __future__ import annotations

import json
import logging

from app.services.summarizer_providers import get_provider

logger = logging.getLogger(__name__)

# Token ceiling handed to the provider. For Anthropic this shares the budget with
# adaptive thinking, so it must hold BOTH the model's reasoning over the diff AND
# a full multi-section narrative — at 2000 the narrative truncated mid-sentence
# once thinking ran. 8000 gives the reasoning room while keeping a per-close
# wrap-up bounded and cheap. Providers map it to their own knob (Anthropic
# max_tokens, Ollama options.num_predict).
_MAX_TOKENS = 8000

_SYSTEM_PROMPT = (
    "You write the wrap-up narrative for a software work session, in the style of "
    "the session summaries an IDE shows after an agent finishes. Your job is to "
    "tell the STORY of the session, grounded in real specifics drawn from the "
    "evidence: code symbols (e.g. fetchCFCRRawData()), file references (e.g. "
    "DataManipulation.php:21), and concrete facts (e.g. 'widened money columns to "
    "decimal(17,6)', '~68% build optimization'). The git diff is your primary "
    "evidence; quote real identifiers from it. Do NOT produce a ticket-count or "
    "stats table — those already exist elsewhere. The value is the readable story.\n\n"
    "Output STRICT JSON only (no prose around it, no markdown fences) in exactly "
    "this shape:\n"
    '{"lead": "<thematic title or one short lead sentence>", '
    '"sections": [{"title": "<short section title>", '
    '"bullets": ["<flowing prose bullet grounded in specifics>", ...]}]}\n\n'
    "Guidance:\n"
    "- The lead is a thematic title or a single short framing sentence.\n"
    "- Bullets are flowing prose (full clauses), not fragments, each anchored to a "
    "real symbol, file, or fact from the evidence.\n"
    "- End with a section whose final bullet is an HONEST caveat (what was NOT done, "
    "what is uncertain, what the evidence could not confirm, or that the diff was "
    "truncated). Be candid; do not invent specifics you cannot see in the evidence.\n"
    "- If the evidence is thin, say so plainly rather than padding.\n"
    "- When you cite a file, use its REPO-RELATIVE path exactly as it appears in "
    "the diff headers (e.g. backend/app/services/foo.py), with :line when a "
    "specific line matters (e.g. backend/app/services/foo.py:42) - never a bare "
    "basename. Cite commit hashes verbatim from the evidence. These resolve into "
    "clickable links, so accuracy matters; if you only know a symbol or a bare "
    "filename, wrap it in backticks instead of writing it as a path.\n"
    "- No emoji, no em dashes."
)


def _build_user_prompt(work_record: dict) -> str:
    """Serialize the work record into the user turn. JSON keeps it unambiguous and
    bounds nothing further (the work record was already size-bounded in DWBG-013)."""
    project = work_record.get("project") or {}
    window = work_record.get("window") or {}
    header = (
        f"Session for project '{project.get('name', '')}' "
        f"({project.get('prefix') or 'n/a'}), window "
        f"{window.get('start', '?')} to {window.get('end', '?')}"
        f"{' (still open)' if window.get('live') else ''}.\n\n"
        "Evidence follows as JSON. Write the wrap-up narrative described in the "
        "system prompt, grounded in the git diff and the other evidence."
    )
    return header + "\n\n" + json.dumps(work_record, ensure_ascii=False, default=str)


def _parse_narrative(text: str) -> dict | None:
    """Parse the model's JSON into the {lead, sections:[{title,bullets}]} shape.
    Tolerates accidental code fences. Returns None if it can't be coerced into the
    contract (so the caller falls back to no-narrative rather than persisting junk)."""
    if not text or not text.strip():
        return None
    s = text.strip()
    # Strip a stray ```json ... ``` fence if the model added one.
    if s.startswith("```"):
        s = s.strip("`")
        # Drop a leading language tag line ("json").
        nl = s.find("\n")
        if nl != -1 and s[:nl].strip().lower() in ("json", ""):
            s = s[nl + 1 :]
        s = s.strip()
    try:
        data = json.loads(s)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    lead = data.get("lead")
    sections = data.get("sections")
    if not isinstance(lead, str) or not isinstance(sections, list):
        return None
    # Normalize sections defensively: keep only well-formed {title, bullets[str]}.
    clean_sections: list[dict] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        title = sec.get("title")
        bullets = sec.get("bullets")
        if not isinstance(title, str) or not isinstance(bullets, list):
            continue
        clean_bullets = [b for b in bullets if isinstance(b, str) and b.strip()]
        if clean_bullets:
            clean_sections.append({"title": title, "bullets": clean_bullets})
    if not clean_sections:
        return None
    return {"lead": lead, "sections": clean_sections}


def generate_narrative(work_record: dict) -> dict | None:
    """DWBG-014 — produce the wrap-up narrative via the selected provider.

    DWBG-017: provider-agnostic. Builds the prompt (unchanged), hands it to
    ``get_provider().complete(...)`` (Ollama by default; Anthropic/MLX by env),
    and parses the returned text into the {lead, sections:[{title,bullets}]}
    contract. Returns None on any failure — the provider returns None on every
    inference failure (no key, SDK missing, backend down, API/HTTP error), and an
    unparseable response also yields None. NEVER raises: callers depend on this
    being safe to run inside a close path. Redaction (DWBG-008) is applied by the
    caller before persist, not here."""
    provider = get_provider()
    text = provider.complete(
        system=_SYSTEM_PROMPT,
        user=_build_user_prompt(work_record),
        max_tokens=_MAX_TOKENS,
    )
    if text is None:
        # The provider already logged the specific failure; nothing to add.
        return None

    narrative = _parse_narrative(text)
    if narrative is None:
        logger.warning(
            "session narrative generation: model response did not parse into the "
            "narrative contract; skipping"
        )
    return narrative

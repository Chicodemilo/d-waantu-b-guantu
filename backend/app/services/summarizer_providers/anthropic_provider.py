# Path: app/services/summarizer_providers/anthropic_provider.py
# File: anthropic_provider.py
# Created: 2026-06-25
# Purpose: DWBG-019 — AnthropicProvider, the swappable Claude API summarizer
#          backend. A behavior-preserving move of the Anthropic SDK call that used
#          to live inline in session_narrative.py: adaptive thinking, sonnet-4-6
#          default, max_tokens passthrough, key from ANTHROPIC_API_KEY, best-effort
#          skip (None) when key/SDK missing or the call errors.
# Caller: app/services/summarizer_providers/__init__.py (get_provider factory)
# Callees: anthropic (Claude API SDK, optional at runtime), os.environ
# Data In: system + user prompts + max_tokens from generate_narrative
# Data Out: the model's text completion, or None on any failure
# Last Modified: 2026-06-25

"""DWBG-019 — Anthropic (Claude API) inference backend.

This is the EXISTING summarizer behavior, moved behind the provider seam with no
functional change. Selected by ``DWB_SUMMARIZER_PROVIDER=anthropic``. Preserves:

  - adaptive thinking (``thinking={"type": "adaptive"}``) so the model reasons
    over the diff before writing;
  - default model ``claude-sonnet-4-6``, overridable via ``DWB_SUMMARIZER_MODEL``;
  - the caller-supplied ``max_tokens`` (the summarizer passes 8000, unchanged);
  - key from ``ANTHROPIC_API_KEY``;
  - best-effort skip: returns ``None`` (never raises) when the key is unset, the
    SDK is not installed, or the API call errors — so a close never blocks.

Unlike the local Ollama default, this ships the work record (which carries the
git diff) to a remote API; that trade-off is why Ollama is the default.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Behavior-preserving defaults moved verbatim from session_narrative.py.
_DEFAULT_MODEL = "claude-sonnet-4-6"
_MODEL_ENV = "DWB_SUMMARIZER_MODEL"
_API_KEY_ENV = "ANTHROPIC_API_KEY"


class AnthropicProvider:
    """Best-effort narrative completion via the Claude API (existing path)."""

    def _model(self) -> str:
        return os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)

    @staticmethod
    def _extract_text(message) -> str:
        """Concatenate the text blocks of a Claude API response message."""
        parts: list[str] = []
        for block in getattr(message, "content", []) or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts)

    def complete(self, *, system: str, user: str, max_tokens: int) -> str | None:
        api_key = os.environ.get(_API_KEY_ENV)
        if not api_key:
            logger.info(
                "ANTHROPIC_API_KEY not set; skipping session narrative generation"
            )
            return None

        try:
            import anthropic  # imported lazily so the package is optional at runtime
        except ImportError:
            logger.warning(
                "anthropic package not installed; skipping session narrative generation"
            )
            return None

        try:
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self._model(),
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception:
            logger.warning(
                "session narrative generation: Claude API call failed; "
                "closing/returning without a narrative",
                exc_info=True,
            )
            return None

        text = self._extract_text(message)
        if not text or not text.strip():
            return None
        return text

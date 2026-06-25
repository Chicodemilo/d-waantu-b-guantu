# Path: app/services/summarizer_providers/ollama.py
# File: ollama.py
# Created: 2026-06-25
# Purpose: DWBG-018 — OllamaProvider, the DEFAULT summarizer backend. Talks to a
#          local Ollama daemon's /api/chat endpoint to produce the session-writeup
#          narrative. No API key. Best-effort: connection/HTTP/parse failures
#          return None (logged) so a close with Ollama down still completes.
# Caller: app/services/summarizer_providers/__init__.py (get_provider factory)
# Callees: requests (already a project dep), os.environ
# Data In: system + user prompts + max_tokens from generate_narrative
# Data Out: the model's text completion, or None on any failure
# Last Modified: 2026-06-25

"""DWBG-018 — local Ollama inference backend (the default provider).

``OllamaProvider.complete`` POSTs to ``{OLLAMA_BASE_URL}/api/chat`` with
``stream: false`` and a system+user message pair, then pulls the assistant text
out of the response.

PRIVACY: this is the DEFAULT provider partly for privacy. Ollama runs locally, so
the work record — which carries the session's git diff — never leaves the machine.
The Anthropic provider, by contrast, ships the diff to a remote API. Defaulting to
Ollama keeps source off the wire unless an operator opts into a remote backend.

BEST-EFFORT: every failure mode (daemon unreachable, non-200, malformed JSON,
missing field) is caught and returns ``None`` so a session close is never blocked
by inference. No live Ollama is required for tests; the HTTP call is mocked.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

# Where the local Ollama daemon listens; its default port.
_BASE_URL_ENV = "OLLAMA_BASE_URL"
_DEFAULT_BASE_URL = "http://localhost:11434"

# Model is shared with the Anthropic path via DWB_SUMMARIZER_MODEL, but the
# default differs per provider: a code-capable LOCAL model for Ollama.
_MODEL_ENV = "DWB_SUMMARIZER_MODEL"
_DEFAULT_MODEL = "qwen2.5-coder"

# Generous but bounded; a local round trip over a large diff can be slow, but a
# close must not hang indefinitely on a wedged daemon.
_TIMEOUT_SECONDS = 120


class OllamaProvider:
    """Best-effort narrative completion via a local Ollama daemon."""

    def _base_url(self) -> str:
        return (os.environ.get(_BASE_URL_ENV) or _DEFAULT_BASE_URL).rstrip("/")

    def _model(self) -> str:
        return os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)

    def complete(self, *, system: str, user: str, max_tokens: int) -> str | None:
        url = f"{self._base_url()}/api/chat"
        payload = {
            "model": self._model(),
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Ollama caps generation length via options.num_predict.
            "options": {"num_predict": max_tokens},
        }
        try:
            resp = requests.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            logger.warning(
                "Ollama summarizer: request to %s failed; returning no narrative",
                url, exc_info=True,
            )
            return None
        except ValueError:
            logger.warning(
                "Ollama summarizer: response from %s was not valid JSON; "
                "returning no narrative", url, exc_info=True,
            )
            return None

        # /api/chat (non-stream) shape: {"message": {"role","content"}, ...}.
        try:
            text = data["message"]["content"]
        except (KeyError, TypeError):
            logger.warning(
                "Ollama summarizer: response missing message.content; "
                "returning no narrative",
            )
            return None
        if not isinstance(text, str) or not text.strip():
            return None
        return text

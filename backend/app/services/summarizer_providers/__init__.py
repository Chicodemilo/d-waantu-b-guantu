# Path: app/services/summarizer_providers/__init__.py
# File: __init__.py
# Created: 2026-06-25
# Purpose: DWBG-017 — provider abstraction for the session-writeup summarizer.
#          Defines the NarrativeProvider Protocol (a single best-effort
#          complete(system, user, max_tokens) -> str | None call) and get_provider(),
#          the env-driven factory that selects the inference backend. Lets the
#          summarizer swap between Ollama (default, local), Anthropic, and MLX
#          (future stub) without touching the prompt-building / parsing layer.
# Caller: app/services/session_narrative.py (generate_narrative)
# Callees: app.services.summarizer_providers.ollama (OllamaProvider),
#          app.services.summarizer_providers.anthropic_provider (AnthropicProvider),
#          app.services.summarizer_providers.mlx (MLXProvider stub), os.environ
# Data In: env DWB_SUMMARIZER_PROVIDER (ollama|anthropic|mlx; default ollama)
# Data Out: a NarrativeProvider instance (always; unknown values fall back safely)
# Last Modified: 2026-06-25

"""DWBG-017 — narrative summarizer provider interface + factory.

The summarizer used to call the Anthropic SDK directly. This package puts a thin
provider seam in front of inference so the backend is swappable by env var:

  - ``ollama``    (DEFAULT) — local Ollama daemon, no API key, diff never leaves
                              the machine (privacy default; see ollama.py).
  - ``anthropic``           — the existing Claude API path, behavior-preserving.
  - ``mlx``                 — future on-device Apple-silicon backend, STUB ONLY.

Every provider implements one method, ``complete``. The contract is best-effort:
any failure (unreachable backend, missing key/SDK, HTTP/parse error) returns
``None`` rather than raising, so a session close never blocks on inference. The
caller (``session_narrative.generate_narrative``) builds the prompt, calls
``complete``, parses, and returns; redaction is applied further up in
``dwb_session.py``. None of that moved.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# env var that selects the backend; the values it accepts; the safe default.
_PROVIDER_ENV = "DWB_SUMMARIZER_PROVIDER"
_DEFAULT_PROVIDER = "ollama"
_VALID_PROVIDERS = ("ollama", "anthropic", "mlx")


@runtime_checkable
class NarrativeProvider(Protocol):
    """The inference seam for the summarizer.

    One method. Given a system prompt, a user prompt, and a token ceiling, return
    the model's text completion, or ``None`` on ANY failure. The ``None`` return
    is the best-effort contract: providers must catch their own errors (no key,
    backend down, HTTP error, bad response) and return ``None`` so that a session
    close which runs the summarizer can never be blocked by inference. Providers
    must NOT raise.
    """

    def complete(self, *, system: str, user: str, max_tokens: int) -> str | None:
        ...


def get_provider() -> NarrativeProvider:
    """Select the summarizer backend from ``DWB_SUMMARIZER_PROVIDER``.

    Default ``ollama``. Accepts ``ollama|anthropic|mlx`` (case-insensitive). An
    unknown value is logged and falls back to the default rather than erroring —
    a typo in config must not break session closes. Always returns a provider
    instance; the instance itself is best-effort at call time.
    """
    raw = os.environ.get(_PROVIDER_ENV, _DEFAULT_PROVIDER)
    name = (raw or _DEFAULT_PROVIDER).strip().lower()
    if name not in _VALID_PROVIDERS:
        logger.warning(
            "%s=%r is not one of %s; falling back to the default %r provider",
            _PROVIDER_ENV, raw, _VALID_PROVIDERS, _DEFAULT_PROVIDER,
        )
        name = _DEFAULT_PROVIDER

    if name == "anthropic":
        from app.services.summarizer_providers.anthropic_provider import (
            AnthropicProvider,
        )
        return AnthropicProvider()
    if name == "mlx":
        # MLX is DEFERRED (DWBG-019): the stub returns None so selecting it today
        # cleanly yields no narrative rather than erroring. TODO(DWBG-future):
        # implement on-device Apple-silicon inference in mlx.MLXProvider.
        from app.services.summarizer_providers.mlx import MLXProvider
        return MLXProvider()

    # Default + explicit "ollama".
    from app.services.summarizer_providers.ollama import OllamaProvider
    return OllamaProvider()


__all__ = ["NarrativeProvider", "get_provider"]

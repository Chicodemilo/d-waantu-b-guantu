# Path: app/services/summarizer_providers/mlx.py
# File: mlx.py
# Created: 2026-06-25
# Purpose: DWBG-019 — MLXProvider STUB. Placeholder for a future on-device
#          Apple-silicon (MLX) inference backend. DEFERRED: not implemented.
#          complete() returns None so selecting DWB_SUMMARIZER_PROVIDER=mlx today
#          cleanly yields no narrative rather than erroring a close.
# Caller: app/services/summarizer_providers/__init__.py (get_provider factory)
# Callees: none
# Data In: system + user prompts + max_tokens from generate_narrative
# Data Out: None (unimplemented; best-effort no-op)
# Last Modified: 2026-06-25

"""DWBG-019 — MLX inference backend (DEFERRED STUB; do NOT implement here).

MLX would run a model on-device via Apple's MLX framework — like Ollama, the
work record (and its git diff) would never leave the machine. It is intentionally
NOT built in this sprint. The stub satisfies the provider Protocol and returns
``None`` so that an operator who sets ``DWB_SUMMARIZER_PROVIDER=mlx`` gets the
best-effort no-narrative outcome (a clean close) rather than an error.

TODO(DWBG-future): implement on-device MLX inference here — load a local
code-capable model, run system+user through it, return the completion text;
keep the best-effort contract (return None on any failure).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MLXProvider:
    """Stub for a future on-device MLX backend. Always returns None for now."""

    def complete(self, *, system: str, user: str, max_tokens: int) -> str | None:
        logger.info(
            "MLXProvider is a deferred stub (DWBG-019); no MLX inference is wired. "
            "Returning no narrative. Set DWB_SUMMARIZER_PROVIDER=ollama or anthropic."
        )
        return None

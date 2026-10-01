# Path: tests/test_ceiling_fallback_guard_dwb627.py
# File: test_ceiling_fallback_guard_dwb627.py
# Created: 2026-10-01
# Purpose: DWB-627 - no call site may inline its own numeric token-ceiling
#          fallback. token_budget.DEFAULT_CEILING exists because the old code
#          used 800 and 1000 inconsistently; four sites in routers/projects.py
#          never adopted it. Guards the rule rather than the four values, so a
#          FIFTH site added later fails instead of passing quietly.
# Caller: pytest
# Callees: app/config/token_budget.py, source scan over app/**/*.py
# Data In: The app source tree
# Data Out: Assertions on inlined fallbacks and on the guard's own liveness

import re
from pathlib import Path

from app.config.token_budget import (
    DEFAULT_CEILING,
    TOKEN_CEILINGS,
    ceiling_for_category,
)

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# Any dict-get on a ceiling table with a hard-coded numeric fallback.
INLINE_FALLBACK = re.compile(r"TOKEN_CEILINGS\s*\.\s*get\s*\([^)]*?,\s*\d+\s*\)")

# Files the guard MUST be reading. A source scan that silently globs nothing
# passes every assertion made over it, so the set it covers is named here and
# asserted non-empty. Adding a module that classifies file categories means
# adding it here, which is the point: the failure is loud.
MUST_SCAN = {
    "routers/projects.py",
    "config/token_budget.py",
}


def _python_sources():
    return sorted(APP_ROOT.rglob("*.py"))


class TestNoInlinedCeilingFallback:
    def test_the_scan_actually_reads_the_files_it_claims_to(self):
        """The guard's own liveness check.

        A glob that matches nothing, or a root pointing at the wrong
        directory, makes every assertion below vacuously true. This fails
        first and names what is missing.
        """
        assert APP_ROOT.is_dir(), f"app root not found at {APP_ROOT}"
        found = _python_sources()
        assert found, "the source scan found no Python files at all"
        relative = {str(p.relative_to(APP_ROOT)) for p in found}
        missing = MUST_SCAN - relative
        assert not missing, (
            f"the scan is not covering {sorted(missing)}; fix the scan or "
            "update MUST_SCAN deliberately"
        )

    def test_the_guard_would_catch_a_violation(self):
        """Positive control: prove the pattern matches a real violation.

        Without this, a typo in the regex produces a guard that matches
        nothing and reports the codebase clean forever. The two shapes below
        are exactly what this ticket removed.
        """
        assert INLINE_FALLBACK.search("ceiling = _TOKEN_CEILINGS.get(category, 1000)")
        assert INLINE_FALLBACK.search("ceiling = TOKEN_CEILINGS.get(category, 800)")
        # And it must NOT flag the correct form, or it is unusable.
        assert not INLINE_FALLBACK.search(
            "ceiling = TOKEN_CEILINGS.get(category, DEFAULT_CEILING)"
        )
        assert not INLINE_FALLBACK.search("ceiling = _ceiling_for_category(category)")

    def test_no_call_site_inlines_a_numeric_ceiling_fallback(self):
        offenders = []
        for path in _python_sources():
            for lineno, line in enumerate(
                path.read_text().splitlines(), start=1
            ):
                if INLINE_FALLBACK.search(line):
                    offenders.append(
                        f"{path.relative_to(APP_ROOT)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "these call sites inline their own ceiling fallback instead of "
            "using token_budget.DEFAULT_CEILING (via ceiling_for_category):\n  "
            + "\n  ".join(offenders)
        )


class TestDefaultCeilingIsTheSingleSource:
    def test_helper_returns_the_default_for_an_unknown_category(self):
        assert "no_such_category_dwb627" not in TOKEN_CEILINGS
        assert ceiling_for_category("no_such_category_dwb627") == DEFAULT_CEILING

    def test_helper_returns_the_table_value_for_a_known_category(self):
        category, expected = next(iter(TOKEN_CEILINGS.items()))
        assert ceiling_for_category(category) == expected

    def test_default_ceiling_is_one_value_not_two(self):
        """The ticket's actual complaint: 800 and 1000 both acted as 'the'
        default depending on which of four lines served the request."""
        assert isinstance(DEFAULT_CEILING, int)
        assert DEFAULT_CEILING == 1000

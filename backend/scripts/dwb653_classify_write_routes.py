#!/usr/bin/env python3
# Path: scripts/dwb653_classify_write_routes.py
# File: dwb653_classify_write_routes.py
# Created: 2026-10-08 (DWB-653)
# Purpose: Turn the commit census the suite produces into a classification of
#          every write route: does a request to it commit, does it demonstrably
#          NOT commit, or has no test ever exercised it.
# Caller: a human, after a full pytest run has written the census
# Callees: app.main.app (for the authoritative route list and URL matching),
#          .pytest_cache/dwb653_commit_census.json
# Data In: the census JSON written by tests/persistence_instrument.write_census
# Data Out: a table on stdout, and a non-zero exit if the census is missing
# Last Modified: 2026-10-08 (DWB-653)

"""Classify every write route by whether a request to it commits.

WHAT EACH ANSWER IS WORTH, because they are not equally strong and reporting
them as if they were would be the defect this ticket is about, one level up.

  NO-COMMIT  is PROOF. Every observed 2xx request to this route completed with
             zero `Session.commit()` calls anywhere in the process. There is no
             other way for a row to reach disk, so nothing this route did
             persisted. This is the DWB-652 signature.

  COMMITS    is EVIDENCE, NOT PROOF. At least one commit happened during the
             request. It does not prove the route committed the RIGHT unit of
             work, only that a commit occurred. Confirming an individual route
             takes the `persisting` fixture, which reads the result back down a
             second connection.

  NOT-COVERED is not a verdict about the route at all. No test ever drove it to
             a 2xx, so the census has nothing to say. These are the ones a
             reader is most likely to mistake for "fine".

  MIXED      some 2xx requests committed and some did not. Usually a route with
             an early-return branch; occasionally a real bug on one path. Worth
             a human look, which is why it is not folded into COMMITS.

The route list comes from the live FastAPI app rather than from a grep, so it
cannot drift from what is actually served.

RUN IT LIKE THIS:
    .venv/bin/python -m pytest -q            # populates the census
    .venv/bin/python scripts/dwb653_classify_write_routes.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from collections import defaultdict
from urllib.parse import urlsplit

os.environ.setdefault("MYSQL_DATABASE", "lat_test")
os.environ.setdefault("TESTING", "1")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
CENSUS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / ".pytest_cache"
    / "dwb653_commit_census.json"
)


def write_routes():
    """Every write route under /api, from the live app."""
    out = []
    for route in app.routes:
        methods = (getattr(route, "methods", None) or set()) & WRITE_METHODS
        path = getattr(route, "path", "")
        if methods and path.startswith("/api"):
            for method in sorted(methods):
                out.append((method, path, route))
    return out


def match_route(method, url, routes):
    """Which route template served this URL. None when nothing matches."""
    path = urlsplit(url).path
    for route_method, template, route in routes:
        if route_method != method:
            continue
        regex = getattr(route, "path_regex", None)
        if regex is not None and regex.fullmatch(path):
            return (route_method, template)
    return None


def main() -> int:
    if not CENSUS_PATH.exists():
        print(
            f"No census at {CENSUS_PATH}.\n"
            "Run the suite first - the census is written at session end:\n"
            "    .venv/bin/python -m pytest -q",
            file=sys.stderr,
        )
        return 2

    payload = json.loads(CENSUS_PATH.read_text())
    meta = payload.get("meta", {})
    census = payload.get("rows", [])
    routes = write_routes()

    # THE PROVENANCE BANNER, PRINTED BEFORE ANY VERDICT. Every pytest session
    # overwrites the census, so a targeted run replaces a full one and the
    # classification silently becomes a report about five tests. A reader who
    # cannot see what produced the census cannot tell that from a regression.
    print("census provenance:")
    print(f"  written_at      : {meta.get('written_at', 'UNKNOWN (pre-provenance file)')}")
    print(f"  pytest argv     : {meta.get('argv', 'UNKNOWN')}")
    print(f"  requests        : {meta.get('requests', len(census))}")
    print(f"  write requests  : {meta.get('write_requests', 'UNKNOWN')}")
    # A SELECTOR, NOT "argv IS NON-EMPTY". The first version of this warned on
    # any argv at all, so a full `pytest -q` fired it every time - a warning
    # that cries wolf on the normal case is worse than no warning, because the
    # reader learns to skip it and then skips the real one. A selector is a
    # positional argument: a path or node id, not a flag.
    selectors = [a for a in meta.get("argv", []) if not a.startswith("-")]
    if selectors:
        print(
            f"  WARNING: this census came from a TARGETED run ({selectors}), not "
            "a full suite. NOT-COVERED below means 'this run did not reach it', "
            "not 'no test covers it'."
        )
    print()

    # (method, template) -> {"ok": n, "ok_nocommit": n, "other": n}
    seen = defaultdict(lambda: {"ok": 0, "ok_nocommit": 0, "other": 0})
    unmatched = 0
    for row in census:
        if row["method"] not in WRITE_METHODS:
            continue
        key = match_route(row["method"], row["url"], routes)
        if key is None:
            unmatched += 1
            continue
        # Only 2xx counts. A request that was REFUSED is supposed not to
        # commit, so counting a 4xx as "no-commit" would report every
        # validation test as a defect.
        if 200 <= row["status"] < 300:
            seen[key]["ok"] += 1
            if row["commits"] == 0:
                seen[key]["ok_nocommit"] += 1
        else:
            seen[key]["other"] += 1

    buckets = defaultdict(list)
    for method, template, _route in routes:
        key = (method, template)
        tally = seen.get(key)
        if tally is None or tally["ok"] == 0:
            verdict = "NOT-COVERED"
        elif tally["ok_nocommit"] == tally["ok"]:
            verdict = "NO-COMMIT"
        elif tally["ok_nocommit"] > 0:
            verdict = "MIXED"
        else:
            verdict = "COMMITS"
        buckets[verdict].append((method, template, tally))

    total = len(routes)
    print(f"DWB-653 write-route commit classification over {total} routes")
    print(f"census rows: {len(census)}   unmatched write URLs: {unmatched}")
    print()
    for verdict in ("NO-COMMIT", "MIXED", "NOT-COVERED", "COMMITS"):
        rows = buckets[verdict]
        print(f"=== {verdict} ({len(rows)}) ===")
        for method, template, tally in sorted(rows, key=lambda r: (r[1], r[0])):
            counts = (
                ""
                if tally is None
                else f"  [2xx={tally['ok']} of which no-commit={tally['ok_nocommit']}, non-2xx={tally['other']}]"
            )
            print(f"  {method:6} {template}{counts}")
        print()

    classified = sum(len(buckets[v]) for v in buckets)
    assert classified == total, f"{classified} classified of {total}"
    print(
        "NO-COMMIT is proof nothing persisted. COMMITS is evidence, not proof. "
        "NOT-COVERED is a gap in the tests, not a verdict on the route."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

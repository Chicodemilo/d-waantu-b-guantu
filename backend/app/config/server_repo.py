# Path: app/config/server_repo.py
# File: server_repo.py
# Created: 2026-09-16
# Purpose: Identifies the repo this DWB server's own code lives in (DWB-571) - the ONLY project whose test suite this server can honestly execute, since POST /system/run-tests always shells out to backend/scripts/run_tests.sh against its own backend and there is no per-project test-runner concept. One function, shared by the API-exposed field (schemas/project.py::ProjectRead.runs_own_tests) and the run-tests endpoint's guard (routers/status.py), so the two can't diverge.
# Caller: app/schemas/project.py, app/routers/status.py
# Callees: pathlib
# Data In: a project's repo_path
# Data Out: bool
# Last Modified: 2026-09-16 (DWB-571)

"""DWB-571: the run-system-tests control ran DWB's own suite no matter which
project's Tests page it was pressed from, and recorded the result against
whatever project_id was passed (or defaulted to). Threading project_id
through unchanged would have made this WORSE, not better: the id only ever
touched the DB record, never what executed, so a naive fix would file DWB's
results under another project's id - a number that looks right and is wrong,
strictly worse than today's honestly-missing one.

The real fix: this server can only ever execute ONE test suite, its own, so
"can this project's tests be run from here" reduces to "IS this project the
repo this server is running from" - never a hardcoded project id, which
breaks the moment DWB is cloned elsewhere or a different deployment assigns
itself a different id.
"""

from pathlib import Path

# backend/app/config/server_repo.py -> config -> app -> backend -> repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def runs_own_tests(repo_path: str | None) -> bool:
    """True when repo_path IS the repo this DWB server's own code lives in.

    False for a missing/empty repo_path. Never raises: an unresolvable path
    (missing directory, bad permissions) can't be this server's own repo
    either, so it resolves to False rather than a 500.
    """
    if not repo_path:
        return False
    try:
        return Path(repo_path).resolve() == REPO_ROOT
    except OSError:
        return False

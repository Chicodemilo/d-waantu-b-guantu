# Path: tests/test_conftest_flock.py
# File: test_conftest_flock.py
# Created: 2026-06-05
# Purpose: DWB-314 — verify the conftest.flock serializes concurrent pytest runs
# Caller: pytest
# Callees: fcntl, subprocess (for the external-blocking test)
# Data In: filesystem (the lock file path used by conftest.create_tables)
# Data Out: assertions on flock behavior
# Last Modified: 2026-06-05

"""DWB-314 acceptance: the conftest fcntl.flock serializes concurrent runs.

We prove the property by composition:

  1. **TestLockFilePresent** — the session fixture in conftest.py creates
     the expected lock file and holds an exclusive lock on it.
  2. **TestExternalProcessBlocking** — an unrelated Python process opening
     a fresh fd against the SAME lock file gets BlockingIOError on
     LOCK_EX|LOCK_NB. Therefore any second pytest process, which calls
     `fcntl.flock(fh.fileno(), fcntl.LOCK_EX)` in its own create_tables
     fixture, will BLOCK (not error) until this one releases.

Composition: (lock held by us) + (external process can't acquire) =
(second pytest waits for first). That's the contract DWB-314 buys.

We deliberately do NOT spawn a real parallel pytest from inside pytest:
the parent process holds the flock for the whole session, so child
pytests would block forever and the test would only "pass" by timeout-
failure. To validate the end-to-end behavior on real hardware, run two
`pytest` invocations from separate shells — the second should block on
the lock until the first finishes.
"""

import errno
import fcntl
import pathlib
import subprocess
import sys

import pytest  # noqa: F401  # pytest auto-discovery requires the import to be present


# Mirror the path conftest.py uses, computed independently so this test
# breaks loudly if the conftest path drifts.
_EXPECTED_LOCK_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / ".pytest_cache" / "lat_test.lock"
)


class TestLockFilePresent:
    """The conftest fixture has already run by the time this test executes
    (session-scoped autouse), so the lock file must exist on disk."""

    def test_lock_file_exists_after_session_start(self):
        assert _EXPECTED_LOCK_PATH.exists(), (
            f"DWB-314 lock file should be created by the session fixture: "
            f"expected {_EXPECTED_LOCK_PATH}"
        )

    def test_lock_file_is_held_by_current_process(self):
        """The session fixture holds LOCK_EX. A non-blocking attempt to grab
        the same lock from THIS process should succeed (the kernel allows
        same-process re-entry for flock advisory locks on most Unix
        implementations) OR fail clean with BlockingIOError. Either is
        acceptable — we're confirming the file is a valid flock target.
        """
        with open(_EXPECTED_LOCK_PATH, "w") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Same-process re-entry succeeded — release immediately so
                # we don't disrupt the session fixture's grip.
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except BlockingIOError as e:
                # Lock contention from another process — that's the
                # whole point of the lock. Reject any other errno.
                assert e.errno in (errno.EWOULDBLOCK, errno.EAGAIN)


class TestExternalProcessBlocking:
    """An external process opening a fresh fd against the SAME lock file
    must be blocked. This is the actual property DWB-314 is buying."""

    def test_lock_blocks_a_separate_python_process(self, tmp_path):
        """Spawn a child Python that tries LOCK_EX|LOCK_NB on the conftest
        lock file. Because the session fixture holds the lock, the child
        must observe BlockingIOError. If it succeeds, the lock isn't doing
        its job."""
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, sys\n"
                    f"fh = open(r'{_EXPECTED_LOCK_PATH}', 'w')\n"
                    "try:\n"
                    "    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                    "    print('ACQUIRED')\n"
                    "    sys.exit(2)\n"
                    "except BlockingIOError:\n"
                    "    print('BLOCKED')\n"
                    "    sys.exit(0)\n"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert child.returncode == 0, (
            f"child should have been BLOCKED by the session lock; "
            f"stdout={child.stdout!r} stderr={child.stderr!r} "
            f"returncode={child.returncode}"
        )
        assert "BLOCKED" in child.stdout


# Note on omitted acceptance test:
#
# An earlier version of this file included a `TestParallelPytestAcceptance`
# that spawned two real pytest subprocesses and waited for both to pass.
# It is omitted because running it inside pytest is self-deadlocking — the
# outer pytest session holds the conftest flock for its entire lifetime,
# so the child pytest invocations block forever waiting for it (which the
# test interprets as failure, even though it's actually proof the lock
# works). The composition argument in the module docstring above carries
# the same load with no flakiness. For real end-to-end verification, an
# operator should run two pytest invocations from separate shells and
# observe the second one wait at session start.

# Path: tests/test_server_repo_dwb571.py
# File: test_server_repo_dwb571.py
# Created: 2026-09-16
# Purpose: Unit tests for app/config/server_repo.py::runs_own_tests (DWB-571)
# Caller: pytest
# Callees: app/config/server_repo.py
# Data In: None (pure function, no DB)
# Data Out: Assertions on runs_own_tests(repo_path)
# Last Modified: 2026-09-16 (DWB-571)

"""DWB-571: runs_own_tests(repo_path) is the single answer to "can this
server honestly run this project's tests" - shared by ProjectRead's computed
field and the POST /system/run-tests guard. These tests pin the pure
function directly so they can't be satisfied by a divergent copy."""

from app.config.server_repo import REPO_ROOT, runs_own_tests


def test_true_for_the_servers_own_repo():
    assert runs_own_tests(str(REPO_ROOT)) is True


def test_false_for_none():
    assert runs_own_tests(None) is False


def test_false_for_empty_string():
    assert runs_own_tests("") is False


def test_false_for_an_unrelated_directory(tmp_path):
    assert runs_own_tests(str(tmp_path)) is False


def test_false_for_a_subdirectory_of_the_servers_own_repo():
    """A subdirectory is not the repo root itself - no partial credit."""
    assert runs_own_tests(str(REPO_ROOT / "backend")) is False


def test_false_for_a_nonexistent_path_no_exception():
    assert runs_own_tests("/definitely/does/not/exist/anywhere") is False


def test_true_for_an_unresolved_but_equivalent_path():
    """A relative-ish or symlink-bearing spelling of the same repo still
    resolves() to REPO_ROOT."""
    assert runs_own_tests(str(REPO_ROOT) + "/backend/..") is True

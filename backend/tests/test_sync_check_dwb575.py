# Path: tests/test_sync_check_dwb575.py
# File: test_sync_check_dwb575.py
# Created: 2026-09-17
# Purpose: Tests for DWB-575 - MEMORY_DIR is no longer hardcoded to one person's
#   home directory, and a source that can't be read is reported distinctly
#   from a source that was read and found empty.
# Caller: pytest
# Callees: app/services/sync_check.py
# Data In: None (pure functions + a db fixture for build_sync_report/sync_memory_to_db)
# Data Out: Assertions on load_memory_entries/build_sync_report/sync_memory_to_db
# Last Modified: 2026-09-17 (DWB-575)

"""DWB-575: sync_check.py used to hardcode one person's username and one
machine's repo directory name as a memory-directory slug, and treated a
missing memory directory the same as an empty one, so every clone but the
original machine silently reported "in sync" having read nothing. These
tests pin: (1) no hardcoded home-directory slug survives, for anyone's
username, (2) a missing/unreadable source is a DISTINCT outcome from a real
empty read, at every layer (load_memory_entries, build_sync_report,
sync_memory_to_db).

Deliberately synthetic paths throughout (/Users/alex/Dev/my-project, not a
real one): the slug algorithm was verified against a real
~/.claude/projects/ listing on a dev machine while writing this fix, and
that confirming already happened - a guard test only needs to pin the
shape, not carry a copy of the specific string it exists to keep out."""

import ast
import inspect

import pytest

from app.config.server_repo import REPO_ROOT
from app.services import sync_check
from app.services.sync_check import (
    SyncSourceUnreadable,
    _claude_project_slug,
    load_memory_entries,
    sync_memory_to_db,
)


class TestNoHardcodedPath:
    """AC 1: no variant of the original string survives, including as a
    fallback or a guess."""

    def test_no_home_directory_slug_literal_survives(self):
        """Guards the SHAPE of the regression - a hardcoded slug for ANY
        user's home directory, not just the one this ticket was filed
        against - so the guard itself never has to carry a copy of a real
        username. Every string constant in the module's source must not
        look like an OS home-directory slug ('-Users-...')."""
        tree = ast.parse(inspect.getsource(sync_check))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not any(s.startswith("-Users-") for s in literals)

    def test_slug_matches_a_known_shape(self):
        """The algorithm (verified against a real listing, see module
        docstring) turns every non-alphanumeric character into a dash, not
        just the slashes - this synthetic path exercises that with the
        underscore in 'my_project'."""
        assert (
            _claude_project_slug("/Users/alex/Dev/my_project")
            == "-Users-alex-Dev-my-project"
        )

    def test_memory_dir_is_derived_from_repo_root_not_a_constant_string(self):
        """MEMORY_DIR's project-slug component IS _claude_project_slug(REPO_ROOT) -
        change REPO_ROOT (e.g. by cloning DWB elsewhere) and MEMORY_DIR moves
        with it, rather than staying pinned to one machine's layout."""
        assert _claude_project_slug(REPO_ROOT) in str(sync_check.MEMORY_DIR)


class TestLoadMemoryEntriesSourceReadable:
    """AC 2/3: a missing or unreadable source is a distinct outcome, not an
    empty list indistinguishable from a real empty read."""

    def test_missing_directory_reports_an_error(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        entries, error = load_memory_entries(missing)
        assert entries == []
        assert error is not None
        assert "not found" in error

    def test_path_that_is_a_file_not_a_directory_reports_an_error(self, tmp_path):
        not_a_dir = tmp_path / "memory"
        not_a_dir.write_text("oops, this is a file")
        entries, error = load_memory_entries(not_a_dir)
        assert entries == []
        assert error is not None
        assert "not a directory" in error

    def test_genuinely_empty_directory_is_not_an_error(self, tmp_path):
        """The legitimate 'nothing pending' state: the directory exists,
        was read, and simply has nothing feedback-typed in it."""
        empty_dir = tmp_path / "memory"
        empty_dir.mkdir()
        entries, error = load_memory_entries(empty_dir)
        assert entries == []
        assert error is None

    def test_directory_with_a_feedback_entry_loads_it(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "some_lesson.md").write_text(
            "---\nname: some_lesson\ndescription: a lesson\n"
            "metadata:\n  type: feedback\n---\nThe body.\n"
        )
        entries, error = load_memory_entries(memory_dir)
        assert error is None
        assert len(entries) == 1
        assert entries[0].name == "some_lesson"


class TestBuildSyncReportSourceReadable:
    def test_missing_directory_marks_source_unreadable(self, db_session, tmp_path):
        report = sync_check.build_sync_report(db_session, memory_dir=tmp_path / "gone")
        assert report.source_readable is False
        assert report.source_error is not None
        assert report.memory_only == []

    def test_empty_directory_marks_source_readable(self, db_session, tmp_path):
        empty_dir = tmp_path / "memory"
        empty_dir.mkdir()
        report = sync_check.build_sync_report(db_session, memory_dir=empty_dir)
        assert report.source_readable is True
        assert report.source_error is None


class TestSyncMemoryToDbSourceReadable:
    """AC 4: the write path is covered by the same distinction."""

    def test_missing_directory_raises_instead_of_returning_empty(
        self, db_session, tmp_path
    ):
        with pytest.raises(SyncSourceUnreadable):
            sync_memory_to_db(db_session, memory_dir=tmp_path / "gone")

    def test_empty_directory_returns_empty_list_without_raising(
        self, db_session, tmp_path
    ):
        empty_dir = tmp_path / "memory"
        empty_dir.mkdir()
        created = sync_memory_to_db(db_session, memory_dir=empty_dir)
        assert created == []

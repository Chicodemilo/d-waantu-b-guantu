# Path: tests/test_suite_fingerprint_dwb635.py
# File: test_suite_fingerprint_dwb635.py
# Created: 2026-10-01
# Purpose: DWB-635 - pin the properties that made this the one checking
#          instrument of the night that survived inspection: content hashing
#          (not a status summary), a PER-ROOT empty refusal, explicit
#          exclusion of run-regenerated files, ownership that is never
#          assumed, and roles stated beside numbers.
# Caller: pytest
# Callees: backend/scripts/suite_fingerprint.py
# Data In: tmp_path trees built per test
# Data Out: Assertions on the snapshot, the refusal and the diff

import importlib.util
import pathlib

import pytest

_SRC = (
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "suite_fingerprint.py"
)
_spec = importlib.util.spec_from_file_location("suite_fingerprint", _SRC)
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def _tree(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


# A scope mirroring the real one's shape without needing a real checkout.
SCOPE = [
    ("code", "**/*.py", "the code under test"),
    ("corpus", "*/*/memory.md", "the gitignored live corpus"),
]

FULL = {
    "code/a.py": "x = 2\n",
    "corpus/DWB/Someone/memory.md": "a lesson\n",
}


class TestItDetectsWhatAStatusHashCannot:
    """The defining property, and the fixture shape is the whole test.

    `git status --porcelain` emits `<XY> <path>` with no content, so a
    content-only edit to a file ALREADY reading ` M` leaves the line
    byte-identical. A clean file ENTERS a status on first edit, so a test using
    a clean fixture would pass against a status hash too and confirm the wrong
    answer. Both agents who established this blindness by experiment first
    reached for a clean file. The fixture shape is named in the test name so a
    future edit cannot quietly weaken it.
    """

    def test_fingerprint_moves_on_a_content_only_edit_to_an_already_dirty_file(
        self, tmp_path
    ):
        repo = _tree(tmp_path, FULL)
        # First edit: the file becomes "dirty". A status hash moves here too,
        # so this transition proves nothing on its own.
        (repo / "code/a.py").write_text("x = 3\n")
        already_dirty = fp.snapshot(repo, SCOPE)

        # Second edit, content-only, status unchanged. THIS is the case a
        # status summary cannot see.
        (repo / "code/a.py").write_text("x = 4\n")
        after = fp.snapshot(repo, SCOPE)

        assert already_dirty["fingerprint"] != after["fingerprint"], (
            "a content-only edit to an already-dirty file did not move the "
            "fingerprint, which is the one case this instrument exists for"
        )


class TestRoleOfEachNumber:
    """Role drift: a number whose role is unstated gets promoted to evidence.

    This pins the roles as behaviour rather than as documentation.
    """

    def test_byte_count_cannot_detect_an_equal_length_change(self, tmp_path):
        """The measured instance, from Barry_DWB's own output: byte_count read
        6 before and 6 after a real content change, because `x = 2` and
        `x = 3` are the same length. The byte count answers DID IT HAVE INPUT.
        It is not a change detector, and this test is what stops a later reader
        treating it as one."""
        repo = _tree(tmp_path, FULL)
        before = fp.snapshot(repo, SCOPE)
        (repo / "code/a.py").write_text("x = 3\n")  # same length, different content
        after = fp.snapshot(repo, SCOPE)

        assert before["byte_count"] == after["byte_count"], (
            "fixture no longer exercises the equal-length case; pick two "
            "contents of identical length or this test proves nothing"
        )
        assert before["file_count"] == after["file_count"]
        assert before["fingerprint"] != after["fingerprint"], (
            "the content hash is the change detector and it failed to move"
        )

    def test_report_prints_each_role_beside_its_own_number(self, tmp_path, capsys):
        repo = _tree(tmp_path, FULL)
        fp.report(fp.snapshot(repo, SCOPE), "SNAPSHOT")
        out = capsys.readouterr().out
        fingerprint_line = next(l for l in out.splitlines() if "fingerprint=" in l)
        counts_line = next(l for l in out.splitlines() if "bytes=" in l)
        assert "[DID IT CHANGE]" in fingerprint_line
        assert "DID IT HAVE INPUT" in counts_line, (
            "the role must be on the same line as the number; a role living in "
            "the docstring does not travel with the number that gets quoted"
        )


class TestEmptyRootRefusal:
    """The refusal is PER-ROOT. The original checked only the total, so one
    root vanishing out of six passed while the others carried the count."""

    def test_a_root_matching_zero_files_refuses_even_when_other_roots_are_full(
        self, tmp_path
    ):
        # Everything present except the corpus: exactly the shape that passed
        # silently before, and the root no git view can see either.
        repo = _tree(tmp_path, {"code/a.py": "x = 2\n"})
        with pytest.raises(fp.ScopeRefused) as exc:
            fp.snapshot(repo, SCOPE)
        assert "corpus" in str(exc.value), (
            "the refusal must NAME the root that vanished; 'something is "
            "empty' sends the reader hunting"
        )

    def test_a_populated_scope_does_not_refuse(self, tmp_path):
        snap = fp.snapshot(_tree(tmp_path, FULL), SCOPE)
        assert snap["per_root"] == {"code": 1, "corpus": 1}


class TestRunRegeneratedFilesAreExcluded:
    def test_pycache_does_not_move_the_fingerprint(self, tmp_path):
        """A fingerprint that moves on every execution reports drift every
        time, gets labelled unreliable and is then removed. The original
        excluded these only by glob accident."""
        repo = _tree(tmp_path, FULL)
        before = fp.snapshot(repo, SCOPE)
        (repo / "code/__pycache__").mkdir(parents=True, exist_ok=True)
        (repo / "code/__pycache__/a.cpython-312.pyc").write_bytes(b"\x00compiled")
        (repo / "code/__pycache__/a.py").write_text("decoy that matches the glob\n")
        after = fp.snapshot(repo, SCOPE)
        assert before["fingerprint"] == after["fingerprint"]
        assert before["file_count"] == after["file_count"]


class TestOwnershipIsNeverAssumed:
    """A stale hardcoded owner list degrades to 'everything is THEIRS', which
    fails in the FLATTERING direction: 'nothing of yours moved' is what the
    reader wants to hear."""

    def _moved(self, tmp_path):
        repo = _tree(tmp_path, FULL)
        before = fp.snapshot(repo, SCOPE)
        (repo / "code/a.py").write_text("x = 99999\n")
        return before, fp.snapshot(repo, SCOPE)

    def test_without_mine_changes_are_unattributed_not_theirs(
        self, tmp_path, capsys
    ):
        before, after = self._moved(tmp_path)
        fp.diff(before, after, None)
        out = capsys.readouterr().out
        assert "UNATTRIBUTED" in out
        assert "THEIRS" not in out, (
            "absent ownership was reported as someone else's, which is the "
            "flattering failure this parameter exists to prevent"
        )
        assert "not the same as" in out

    def test_with_mine_a_prefix_claims_the_file(self, tmp_path, capsys):
        before, after = self._moved(tmp_path)
        fp.diff(before, after, ["code"])
        out = capsys.readouterr().out
        assert "MINE   code/a.py" in out
        assert "UNATTRIBUTED" not in out

    def test_a_prefix_does_not_claim_a_sibling_by_string_prefix(self):
        assert fp._owned("code/a.py", ["code"])
        assert not fp._owned("codex/a.py", ["code"]), (
            "'code' must not claim 'codex/'; prefix matching has to respect "
            "the path separator"
        )


class TestPathsArePortable:
    def test_recorded_paths_are_repo_relative(self, tmp_path):
        snap = fp.snapshot(_tree(tmp_path, FULL), SCOPE)
        assert set(snap["files"]) == {"code/a.py", "corpus/DWB/Someone/memory.md"}
        assert not any(k.startswith("/") for k in snap["files"]), (
            "absolute paths would make a snapshot unreadable on another clone"
        )

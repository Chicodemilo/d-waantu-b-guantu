# Path: tests/test_doc_drift_dwb569.py
# File: test_doc_drift_dwb569.py
# Created: 2026-09-16
# Purpose: DWB-569 — prove the two doc-drift checks exist, run in the normal suite, and (per AC1) actually fail on a seeded violation before trusting either one.
# Caller: pytest (auto-collected)
# Callees: app.services.doc_drift
# Data In: live repo docs, synthetic tmp_path fixtures for seeded-violation cases
# Data Out: pass/fail assertions
# Last Modified: 2026-09-16 (DWB-569)

from pathlib import Path

from app.services import doc_drift


class TestAllowlistDiscipline:
    """AC3: the allowlist requires a reason string per entry. Growth is
    visible in code review (it's an ordinary diffable list), but a missing
    or blank reason is a mechanical thing this test CAN catch."""

    def test_every_allowlist_entry_has_a_real_reason(self):
        assert doc_drift.ALLOWLIST, "allowlist should not be empty on a real repo"
        for entry in doc_drift.ALLOWLIST:
            assert entry.reason and entry.reason.strip(), (
                f"allowlist entry {entry.doc}:{entry.symbol!r} has no reason"
            )
            assert len(entry.reason.strip()) >= 15, (
                f"allowlist entry {entry.doc}:{entry.symbol!r} reason too thin "
                f"to be a real justification: {entry.reason!r}"
            )


class TestCheckA_SymbolAndEndpointReferences:
    """DWB-569 check (a): backticked symbols/endpoints in the gated docs must
    still resolve against the current codebase."""

    def test_gated_docs_references_resolve(self):
        """The live check, against the actual repo. This is what would have
        caught `_ALERT_ROLES` being described in four docs after DWB-566
        deleted it. If this fails, either the doc is genuinely stale (fix
        the doc) or the reference is a deliberate tombstone/historical/
        illustrative example (add an ALLOWLIST entry with a real reason)."""
        unresolved = doc_drift.find_unresolved_references()
        assert not unresolved, (
            "Unresolved doc references (fix the doc or allowlist with a "
            "reason):\n"
            + "\n".join(f"  {u.doc}: `{u.symbol}` ({u.kind})" for u in unresolved)
        )

    def test_seeded_symbol_reference_is_detected(self, tmp_path):
        """AC1: prove the check can fail. A symbol that resolves nowhere in
        a from-scratch corpus must be reported."""
        doc = tmp_path / "FAKE_DOC.md"
        doc.write_text(
            "This project uses `_totally_invented_symbol_dwb569` for X.\n",
            encoding="utf-8",
        )
        unresolved = doc_drift.find_unresolved_references(
            docs=[doc], repo_root=tmp_path
        )
        assert len(unresolved) == 1
        assert unresolved[0].symbol == "_totally_invented_symbol_dwb569"
        assert unresolved[0].kind == "symbol"

    def test_symbol_present_in_corpus_resolves(self, tmp_path):
        """Positive control for the seeded test above — a symbol that DOES
        exist in the search corpus must not be flagged."""
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "thing.py").write_text(
            "def _seeded_present_symbol_dwb569():\n    pass\n", encoding="utf-8"
        )
        doc = tmp_path / "FAKE_DOC.md"
        doc.write_text(
            "Calls `_seeded_present_symbol_dwb569` on write.\n", encoding="utf-8"
        )
        unresolved = doc_drift.find_unresolved_references(
            docs=[doc], repo_root=tmp_path
        )
        assert unresolved == []

    def test_seeded_api_path_is_detected(self, tmp_path):
        """AC1 for the endpoint half: a path with no matching FastAPI route
        must be reported, regardless of repo_root (route table is the live
        app, not the synthetic corpus)."""
        doc = tmp_path / "FAKE_DOC.md"
        doc.write_text(
            "See `GET /api/totally/not/a/real/endpoint` for details.\n",
            encoding="utf-8",
        )
        unresolved = doc_drift.find_unresolved_references(
            docs=[doc], repo_root=tmp_path
        )
        assert len(unresolved) == 1
        assert unresolved[0].kind == "api_path"

    def test_real_api_path_resolves(self, tmp_path):
        """Positive control: a real, currently-registered endpoint must not
        be flagged, including with a worked-example id in a param slot."""
        doc = tmp_path / "FAKE_DOC.md"
        doc.write_text(
            "Check health: `GET /api/status`. "
            'Or mint one: `PATCH /api/sprints/X {"status": "completed"}`.\n',
            encoding="utf-8",
        )
        unresolved = doc_drift.find_unresolved_references(
            docs=[doc], repo_root=tmp_path
        )
        assert unresolved == [], unresolved

    def test_allowlisted_symbol_is_not_reported(self, tmp_path):
        """Allowlist mechanics: an entry matches by (doc suffix, exact
        symbol text) and suppresses an otherwise-unresolved reference."""
        entry = doc_drift.ALLOWLIST[0]
        doc = tmp_path / entry.doc
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(f"See `{entry.symbol}` for context.\n", encoding="utf-8")
        unresolved = doc_drift.find_unresolved_references(
            docs=[doc], repo_root=tmp_path
        )
        assert unresolved == []

    def test_allowlist_match_requires_both_doc_and_symbol(self, tmp_path):
        """An allowlisted symbol in a DIFFERENT, unrelated doc is not
        automatically excused — the allowlist is scoped per-doc, not global,
        so a genuine new instance of the same dead symbol elsewhere still
        gets caught."""
        entry = doc_drift.ALLOWLIST[0]
        doc = tmp_path / "UNRELATED_DOC.md"
        doc.write_text(f"See `{entry.symbol}` for context.\n", encoding="utf-8")
        unresolved = doc_drift.find_unresolved_references(
            docs=[doc], repo_root=tmp_path
        )
        assert len(unresolved) == 1
        assert unresolved[0].symbol == entry.symbol


class TestCheckB_PlaybookDeploySync:
    """DWB-569 check (b): DWB's own deployed .claude/*_playbook.md must
    match what deploy_bundle would render from docs/*_playbook.md right now.
    Cheap, and it would have caught the live failure where the deployed PM
    playbook carried a rule DWB-560 had already replaced in docs/."""

    def test_dwb_deployed_playbooks_match_source(self):
        """DWB is a non-Jira project (see project_rules_worker.md banner),
        so jira_enabled=False is DWB's own rendering target. If this fails,
        redeploy: POST /api/projects/1/deploy-playbooks, or manually re-run
        the render (see playbook_deploy.deploy_bundle)."""
        drifted = doc_drift.find_playbook_deploy_drift(
            claude_dir=doc_drift.DWB_CLAUDE_DIR,
            jira_enabled=False,
        )
        assert drifted == [], (
            f"Deployed playbook(s) out of sync with docs/: {drifted}. "
            "A redeploy was skipped or reverted (this is what 032ee02 fixed)."
        )

    def test_reverting_the_redeploy_would_fail(self):
        """AC2, made concrete: replay 032ee02's own diff. Take the CURRENT
        (post-redeploy) deployed pm_playbook.md and mutate it back to
        contain the pre-DWB-560 rule wording that commit replaced, in a
        throwaway copy, and confirm the check flags it. This is the seeded
        violation for check (b), phrased as the exact regression AC2 names."""
        pm_src = (doc_drift.DOCS_DIR / "pm_playbook.md").read_text(encoding="utf-8")
        assert pm_src, "docs/pm_playbook.md must be non-empty to run this test"

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_docs = Path(tmpdir) / "docs"
            tmp_claude = Path(tmpdir) / ".claude"
            tmp_docs.mkdir()
            tmp_claude.mkdir()
            (tmp_docs / "pm_playbook.md").write_text(pm_src, encoding="utf-8")
            # Simulate a stale deployed copy: same source, but the deployed
            # side wasn't refreshed, i.e. drifted by definition (any byte
            # difference reproduces the "old rule survives deploy" failure
            # mode, we don't need the exact historical wording to prove the
            # detector fires on it).
            (tmp_claude / "pm_playbook.md").write_text(
                pm_src + "\n<!-- stale: pre-DWB-560 copy, never redeployed -->\n",
                encoding="utf-8",
            )
            drifted = doc_drift.find_playbook_deploy_drift(
                claude_dir=tmp_claude, docs_dir=tmp_docs, jira_enabled=False
            )
            assert drifted == ["pm_playbook.md"]

    def test_matching_copies_report_no_drift(self, tmp_path):
        """Positive control: when the deployed copy IS what deploy_bundle
        would render, there's no drift to report."""
        tmp_docs = tmp_path / "docs"
        tmp_claude = tmp_path / ".claude"
        tmp_docs.mkdir()
        tmp_claude.mkdir()
        src_text = "# Worker Playbook\n\nSome canonical rule.\n"
        (tmp_docs / "worker_playbook.md").write_text(src_text, encoding="utf-8")
        rendered = doc_drift._scrub_for_jira_target(src_text, jira_enabled=False)
        rendered = doc_drift._prepend_banner_if_needed(rendered, jira_enabled=False)
        (tmp_claude / "worker_playbook.md").write_text(rendered, encoding="utf-8")
        drifted = doc_drift.find_playbook_deploy_drift(
            claude_dir=tmp_claude, docs_dir=tmp_docs, jira_enabled=False
        )
        assert drifted == []

    def test_missing_side_is_not_reported_as_drift(self, tmp_path):
        """Documented boundary: a file missing on one side isn't this
        check's concern (that's a deploy-never-ran / file-deleted failure,
        not a content-drift failure), so it must not be reported here."""
        tmp_docs = tmp_path / "docs"
        tmp_claude = tmp_path / ".claude"
        tmp_docs.mkdir()
        tmp_claude.mkdir()
        (tmp_docs / "team_lead_playbook.md").write_text("# TL\n", encoding="utf-8")
        # No matching file under tmp_claude.
        drifted = doc_drift.find_playbook_deploy_drift(
            claude_dir=tmp_claude, docs_dir=tmp_docs, jira_enabled=False
        )
        assert drifted == []

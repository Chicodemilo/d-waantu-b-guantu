# Path: tests/test_ticket_number_derive_dwb529.py
# File: test_ticket_number_derive_dwb529.py
# Created: 2026-09-15
# Purpose: DWB-529: POST /api/tickets derives ticket_number from the trailing integer of ticket_key when omitted, accepts agreeing pairs unchanged, and 422s naming both values when they disagree or when nothing can be derived.
# Caller: pytest
# Callees: POST /api/tickets, app.schemas.ticket.ticket_number_from_key
# Data In: Factory-created project + sprint via conftest fixtures
# Data Out: Assertions on status codes, derived ticket_number, 422 detail text
# Last Modified: 2026-09-15 (DWB-529)

"""DWB-529: ticket_key and ticket_number are one fact written twice."""

import pytest

from app.schemas.ticket import ticket_number_from_key


class TestTrailingNumberHelper:
    @pytest.mark.parametrize("key,expected", [
        ("VTC-040", 40),
        ("DWB-1484", 1484),
        ("CRT-001", 1),
        ("X7", 7),
        ("ABC-12 ", 12),
        ("NOKEY", None),
        ("X-12-abc", None),
        ("", None),
    ])
    def test_trailing_integer(self, key, expected):
        assert ticket_number_from_key(key) == expected


class TestCreateDerivesNumber:
    def _post(self, client, project_id, **body):
        return client.post("/api/tickets", json={
            "project_id": project_id, "title": "derived", **body,
        })

    def test_omitted_number_is_derived_from_key(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = self._post(client, project["id"], ticket_key="VTC-040")
        assert r.status_code == 201, r.text
        assert r.json()["ticket_number"] == 40
        assert r.json()["ticket_key"] == "VTC-040"

    def test_leading_zeros_do_not_matter(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = self._post(client, project["id"], ticket_key="VTC-007")
        assert r.status_code == 201, r.text
        assert r.json()["ticket_number"] == 7

    def test_agreeing_pair_unchanged(self, client, make_project, make_sprint):
        """Existing callers send both; they keep working byte-for-byte."""
        project = make_project()
        make_sprint(project_id=project["id"])
        r = self._post(client, project["id"], ticket_key="VTC-040", ticket_number=40)
        assert r.status_code == 201, r.text
        assert r.json()["ticket_number"] == 40

    def test_disagreeing_pair_422_names_both(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = self._post(client, project["id"], ticket_key="VTC-040", ticket_number=41)
        assert r.status_code == 422, r.text
        msg = str(r.json()["detail"])
        assert "41" in msg
        assert "VTC-040" in msg
        assert "40" in msg

    def test_omitted_number_with_numberless_key_422(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = self._post(client, project["id"], ticket_key="NOKEY")
        assert r.status_code == 422, r.text
        assert "NOKEY" in str(r.json()["detail"])

    def test_numberless_key_with_explicit_number_still_allowed(
        self, client, make_project, make_sprint,
    ):
        """Nothing to compare against, so an explicit number is taken as-is
        (no new restriction on keys without a trailing integer)."""
        project = make_project()
        make_sprint(project_id=project["id"])
        r = self._post(client, project["id"], ticket_key="NOKEY", ticket_number=3)
        assert r.status_code == 201, r.text
        assert r.json()["ticket_number"] == 3

    def test_nothing_persisted_on_422(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        self._post(client, project["id"], ticket_key="VTC-040", ticket_number=41)
        listed = client.get("/api/tickets", params={"project_id": project["id"]}).json()
        assert listed == []

    def test_duplicate_derived_number_still_409(self, client, make_project, make_sprint):
        """The derived path feeds the same DWB-465 duplicate guard."""
        project = make_project()
        make_sprint(project_id=project["id"])
        assert self._post(client, project["id"], ticket_key="VTC-040").status_code == 201
        r = self._post(client, project["id"], ticket_key="VTC-040")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["ticket_number"] == 40

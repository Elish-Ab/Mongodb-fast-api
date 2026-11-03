"""permit_history: county permits always; Seattle permits by street address. Network faked."""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import lookups  # noqa: E402
from pivotal_engine.sources.kc_assessor_models import KCPermit  # noqa: E402

PERMIT = KCPermit("7036451-EL", "125 AMP service change,", "", "7/19/2024", "$2,500", "SEATTLE")


class FakeRecord:
    def __init__(self, jurisdiction):
        self.parcel_number, self.site_address, self.jurisdiction = "9331800500", "3302 S ORCAS ST 98118", jurisdiction
        self.permits = (PERMIT,)


class FakeClient:
    def __init__(self, record):
        self.record = record

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_detail(self, pin):
        return self.record


class FakeResponse:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self.rows


def use_record(monkeypatch, jurisdiction):
    monkeypatch.setattr(lookups, "KCAssessorClient", lambda: FakeClient(FakeRecord(jurisdiction)))


def test_street_part_drops_zip_and_unsafe_characters():
    assert lookups._street_part("3302 S ORCAS ST 98118") == "3302 S ORCAS ST"
    assert lookups._street_part("12 N 45th St'; drop") == "12 N 45TH ST DROP"


def test_seattle_lot_gets_city_permits_with_links(monkeypatch):
    use_record(monkeypatch, "SEATTLE")
    calls = []

    def fake_get(url, params, timeout, headers):
        calls.append(params["$where"])
        row = {"permitnum": "7036451-EL", "permittypemapped": "Electrical", "description": "125 AMP service change",
               "issueddate": "2024-07-19T00:00:00.000", "statuscurrent": "Completed", "link": {"url": "https://portal/7036451"}}
        return FakeResponse([row] if "c4tj" in url else [])

    monkeypatch.setattr(lookups.httpx, "get", fake_get)
    out = lookups.permit_history("9331800500")
    assert out["county_record"]["permits"][0]["number"] == "7036451-EL"
    electrical = out["seattle_permits"]["electrical"]["permits"][0]
    assert electrical["issued"] == "2024-07-19" and electrical["source_url"] == "https://portal/7036451"
    assert out["seattle_permits"]["building"]["permits"] == []
    assert all("3302 S ORCAS ST%" in where for where in calls)


def test_city_outage_is_reported_not_raised(monkeypatch):
    use_record(monkeypatch, "SEATTLE")

    def down(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(lookups.httpx, "get", down)
    out = lookups.permit_history("9331800500")
    assert all("error" in v for v in out["seattle_permits"].values())
    assert out["county_record"]["permits"]


def test_outside_seattle_only_county_permits(monkeypatch):
    use_record(monkeypatch, "BELLEVUE")
    out = lookups.permit_history("8146100590")
    assert "seattle_permits" not in out and "no city permit data" in out["city_permits"]


def test_link_url_accepts_socrata_objects_and_rejects_junk():
    assert lookups._link_url({"url": "https://portal/1"}) == "https://portal/1"
    assert lookups._link_url("https://portal/2") == "https://portal/2"
    assert lookups._link_url({"url": "javascript:alert(1)"}) is None
    assert lookups._link_url(None) is None

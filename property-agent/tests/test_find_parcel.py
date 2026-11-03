"""Address -> King County parcel number. Map service faked."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import lookups  # noqa: E402

ROWS = {
    "1256 111TH AVE NE": [{"PIN": "4348800050", "ADDR_FULL": "1256 111TH AVE NE", "CTYNAME": "Bellevue", "ZIP5": "98004"}],
    "100 MAIN ST": [{"PIN": "1111111111", "ADDR_FULL": "100 MAIN ST", "CTYNAME": "Seattle", "ZIP5": "98101"},
                    {"PIN": "2222222222", "ADDR_FULL": "100 MAIN ST", "CTYNAME": "Kent", "ZIP5": "98032"}],
}


@pytest.fixture(autouse=True)
def fake_map(monkeypatch):
    def query(url, params):
        street = params["where"].split("'")[1].rstrip("%")
        return {"features": [{"attributes": r} for r in ROWS.get(street, [])]}, url
    monkeypatch.setattr(lookups, "_arcgis_query", query)


@pytest.mark.parametrize("text", ["1256 111th Ave Ne, Bellevue, WA 98004", "1256 111th Avenue Northeast",
                                  "  1256 111TH AVE NE  98004"])
def test_finds_one_parcel_from_common_ways_of_writing_an_address(text):
    out = lookups.find_parcel(text)
    assert out["parcel_number"] == "4348800050"


def test_city_or_zip_picks_between_same_street_in_two_cities():
    assert lookups.find_parcel("100 Main St, Kent, WA")["parcel_number"] == "2222222222"
    assert lookups.find_parcel("100 Main Street 98101")["parcel_number"] == "1111111111"


def test_ambiguous_address_lists_the_choices():
    out = lookups.find_parcel("100 Main St")
    assert out["parcel_number"] is None and len(out["candidates"]) == 2


def test_unknown_address_and_garbage():
    assert lookups.find_parcel("999 Nowhere Rd")["parcel_number"] is None
    assert lookups.find_parcel("'; drop table")["parcel_number"] is None


def test_street_query_is_safe():
    assert "'" not in lookups.normalize_street("12 O'Brien Dr")

import pytest

from pivotal_engine.errors import ParcelNotFound, PageFormatChanged
from pivotal_engine.sources.kc_assessor_parser import parse_dashboard_page, parse_detail_page


class TestSeattleDetailPage:
    @pytest.fixture
    def record(self, seattle_detail_html):
        return parse_detail_page(seattle_detail_html)

    def test_parcel_and_address(self, record):
        assert record.parcel_number == "9331800500"
        assert record.site_address == "3302 S ORCAS ST 98118"
        assert record.jurisdiction == "SEATTLE"

    def test_land(self, record):
        assert record.land.present_use == "Single Family(Res Use/Zone)"
        assert record.land.land_sqft == 5700
        assert record.land.zoning == "NR"
        assert record.land.sewer_septic == "PUBLIC"
        assert record.land.easements == "NO"
        assert record.land.environmental == "NO"

    def test_nuisances_and_views(self, record):
        assert record.land.traffic_noise == "MODERATE"
        assert record.land.power_lines == "NO"
        assert record.land.views == {}  # no view ratings on this parcel

    def test_building_floor_areas(self, record):
        assert len(record.buildings) == 1
        b = record.buildings[0]
        assert b.year_built == 1918
        assert b.year_renovated is None  # "0" on the page means never renovated
        assert (b.first_floor, b.half_floor, b.second_floor, b.upper_floor) == (879, 0, 0, 0)
        assert b.total_basement == 830
        assert b.finished_basement == 160
        assert b.basement_garage == 0
        assert b.grade == "6  Low Average"
        assert b.condition == "Average"

    def test_permits(self, record):
        assert record.permits[0].number == "7036451-EL"
        assert "125 AMP service change" in record.permits[0].description
        assert record.permits[0].issue_date == "7/19/2024"

    def test_source_link(self, record):
        assert record.source_url.endswith("Detail.aspx?ParcelNbr=9331800500")


class TestBellevueDetailPage:
    def test_values_match_the_completed_analysis(self, bellevue_detail_html):
        record = parse_detail_page(bellevue_detail_html)
        assert record.jurisdiction == "BELLEVUE"
        assert record.land.land_sqft == 7337
        assert record.land.zoning == "SR-3"
        b = record.buildings[0]
        assert b.first_floor == 1220
        assert b.year_built == 1954
        assert b.attached_garage == 650

    def test_accessory_structures_are_listed(self, bellevue_detail_html):
        record = parse_detail_page(bellevue_detail_html)
        assert record.accessories[0].type.startswith("PRK:CARPORT")


def test_missing_parcel_raises_not_found(notfound_detail_html):
    with pytest.raises(ParcelNotFound):
        parse_detail_page(notfound_detail_html)


def test_unrecognized_page_raises_format_changed():
    with pytest.raises(PageFormatChanged):
        parse_detail_page("<html><body><p>maintenance</p></body></html>")


def test_records_are_immutable(seattle_detail_html):
    record = parse_detail_page(seattle_detail_html)
    with pytest.raises(AttributeError):
        record.jurisdiction = "OTHER"  # type: ignore[misc]


def test_dashboard_summary(seattle_dashboard_html):
    summary = parse_dashboard_page(seattle_dashboard_html)
    assert summary.parcel_number == "9331800500"
    assert summary.total_sqft == 1709
    assert summary.lot_size == 5700
    assert summary.year_built == 1918

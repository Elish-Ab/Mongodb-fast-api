"""Edge cases raised in code review."""

import httpx
import pytest

from pivotal_engine.errors import InvalidParcelNumber, PageFormatChanged, SourceUnavailable
from pivotal_engine.sources.kc_assessor_client import KCAssessorClient
from pivotal_engine.sources.kc_assessor_parser import _grid_rows, _soup, _to_float, _to_int, parse_detail_page
from pivotal_engine.sources.kc_parcel_number import normalize_kc_parcel_number
from pivotal_engine.template_inputs import Status, kc_record_to_inputs

FIRST_FLOOR = '1st Floor</b></font></td><td><font size="3">879<'
LAND_SQFT = 'Land SqFt</b></font></td><td><font size="3">5,700<'


def cells(record):
    return {i.cell: i for i in kc_record_to_inputs(record)}


def test_renamed_floor_label_is_reported_not_zeroed(seattle_detail_html):
    assert FIRST_FLOOR in seattle_detail_html
    html = seattle_detail_html.replace(FIRST_FLOOR, FIRST_FLOOR.replace("1st Floor", "First Level"))
    with pytest.raises(PageFormatChanged):
        parse_detail_page(html)


def test_missing_lot_size_is_check_not_record(seattle_detail_html):
    assert LAND_SQFT in seattle_detail_html
    html = seattle_detail_html.replace(LAND_SQFT, LAND_SQFT.replace("5,700", ""))
    b6 = cells(parse_detail_page(html))["B6"]
    assert b6.value is None
    assert b6.status is Status.CHECK


def test_blank_jurisdiction_is_check(seattle_detail_html):
    html = seattle_detail_html.replace(">SEATTLE<", "><")
    b21 = cells(parse_detail_page(html))["B21"]
    assert b21.value is None
    assert b21.status is Status.CHECK


def test_page_for_a_different_parcel_is_rejected(seattle_detail_html):
    client = KCAssessorClient(
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=seattle_detail_html))),
        min_interval_s=0,
    )
    with pytest.raises(PageFormatChanged):
        client.fetch_detail("8146100590")


def test_caller_http_client_headers_untouched(seattle_detail_html):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=seattle_detail_html)))
    KCAssessorClient(http=http, min_interval_s=0).fetch_detail("9331800500")
    assert "PivotalPropertyEngine" not in http.headers.get("user-agent", "")


def test_rate_limit_message_is_helpful():
    client = KCAssessorClient(
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))), min_interval_s=0
    )
    with pytest.raises(SourceUnavailable, match="rate"):
        client.fetch_detail("9331800500")


@pytest.mark.parametrize("raw", ["９３３１８００５００", "93318005²0"])
def test_non_ascii_digits_rejected(raw):
    with pytest.raises(InvalidParcelNumber):
        normalize_kc_parcel_number(raw)


def test_number_helpers_reject_non_finite():
    assert _to_int("inf") is None
    assert _to_float("nan") is None


def test_grid_skips_rows_that_do_not_line_up():
    html = "<table id='g'><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>pager</td></tr></table>"
    assert _grid_rows(_soup(html), "g") == [{"A": "1", "B": "2"}]


def test_multiple_living_units_flags_structure(seattle_detail_html):
    marker = 'Living Units</b></font></td><td><font size="3">1<'
    assert marker in seattle_detail_html
    html = seattle_detail_html.replace(marker, marker[:-2] + "2<")
    b40 = cells(parse_detail_page(html))["B40"]
    assert b40.status is Status.CHECK
    assert "2 living units" in b40.note

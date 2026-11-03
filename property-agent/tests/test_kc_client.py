import httpx
import pytest

from pivotal_engine.errors import ParcelNotFound, SourceUnavailable
from pivotal_engine.sources.kc_assessor_client import KCAssessorClient


def make_client(handler, **kwargs) -> KCAssessorClient:
    transport = httpx.MockTransport(handler)
    return KCAssessorClient(
        http=httpx.Client(transport=transport), min_interval_s=0, retry_backoff_s=0, **kwargs
    )


def test_client_error_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(SourceUnavailable):
        make_client(handler).fetch_detail("9331800500")
    assert calls["n"] == 1


def test_fetches_detail_page_with_honest_user_agent(seattle_detail_html):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text=seattle_detail_html)

    record = make_client(handler).fetch_detail("933180-0500")

    assert seen["url"] == "https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr=9331800500"
    assert "PivotalPropertyEngine" in seen["ua"]
    assert record.land.land_sqft == 5700


def test_not_found_parcel(notfound_detail_html):
    client = make_client(lambda r: httpx.Response(200, text=notfound_detail_html))
    with pytest.raises(ParcelNotFound):
        client.fetch_detail("0000000001")


def test_server_error_is_retried_then_reported():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503)

    client = make_client(handler, retries=2)
    with pytest.raises(SourceUnavailable):
        client.fetch_detail("9331800500")
    assert calls["n"] == 3  # first try + 2 retries


def test_network_error_is_reported():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    client = make_client(handler, retries=0)
    with pytest.raises(SourceUnavailable):
        client.fetch_detail("9331800500")


def test_fetches_dashboard(seattle_dashboard_html):
    client = make_client(lambda r: httpx.Response(200, text=seattle_dashboard_html))
    assert client.fetch_dashboard("9331800500").total_sqft == 1709


@pytest.mark.live
def test_live_king_county_site():
    with KCAssessorClient() as client:
        record = client.fetch_detail("9331800500")
    assert record.land.land_sqft == 5700

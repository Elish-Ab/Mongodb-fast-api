import json

import httpx

from pivotal_engine import __main__ as cli
from pivotal_engine.sources import kc_assessor_client


def _patch_client(monkeypatch, html, status=200):
    real_init = kc_assessor_client.KCAssessorClient.__init__

    def fake_init(self, *args, **kwargs):
        transport = httpx.MockTransport(lambda r: httpx.Response(status, text=html))
        real_init(self, http=httpx.Client(transport=transport), min_interval_s=0, retries=0)

    monkeypatch.setattr(kc_assessor_client.KCAssessorClient, "__init__", fake_init)


def test_prints_template_inputs(monkeypatch, capsys, seattle_detail_html):
    _patch_client(monkeypatch, seattle_detail_html)
    assert cli.main(["9331800500"]) == 0
    cells = {row["cell"]: row for row in json.loads(capsys.readouterr().out)}
    assert cells["B6"]["value"] == 5700
    assert cells["B6"]["status"] == "record"


def test_raw_record(monkeypatch, capsys, seattle_detail_html):
    _patch_client(monkeypatch, seattle_detail_html)
    assert cli.main(["9331800500", "--raw"]) == 0
    assert json.loads(capsys.readouterr().out)["land"]["zoning"] == "NR"


def test_error_message_and_exit_code(monkeypatch, capsys, notfound_detail_html):
    _patch_client(monkeypatch, notfound_detail_html)
    assert cli.main(["0000000001"]) == 1
    assert "no record" in capsys.readouterr().err

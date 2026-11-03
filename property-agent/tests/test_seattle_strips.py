"""Seattle strip check: legal right-of-way + surface, with the map services faked (no network)."""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import lookups  # noqa: E402
import lot_geometry as geo  # noqa: E402

SIDE = geo.Side(direction_deg=90.0, length_ft=51.7, gap_ft=16.0, kind="alley", gap_point=(10.0, 20.0))


def fake_post(row_sym, surface):
    def post(url, params):
        if url.startswith(lookups.SEATTLE_RIGHT_OF_WAY):
            return {"features": [{"attributes": {"L_FEA_SYM": row_sym}}] if row_sym else []}
        return {"features": [{"attributes": {"IMPSURF_FEATYPE_CODE": surface[0],
                                             "IMPSURF_SURFTYPE_CODE": surface[1]}}] if surface else []}
    return post


def test_paved_alley(monkeypatch):
    monkeypatch.setattr(lookups, "_arcgis_post", fake_post(9, ("STR", "SOL")))
    out = lookups._strip_record(SIDE)
    assert out["legal_status"] == ["alley right-of-way"]
    assert out["surface_2015"] == [{"kind": "street or alley", "finish": "solid (paved)"}]
    assert out["strip_width_ft"] == 16.0


def test_gravel_alley(monkeypatch):
    monkeypatch.setattr(lookups, "_arcgis_post", fake_post(9, ("STR", "PAK")))
    assert lookups._strip_record(SIDE)["surface_2015"][0]["finish"] == "discontinuous (gravel or broken)"


def test_strip_with_no_records(monkeypatch):
    monkeypatch.setattr(lookups, "_arcgis_post", fake_post(None, None))
    out = lookups._strip_record(SIDE)
    assert out["legal_status"] == ["no right-of-way record"]
    assert out["surface_2015"] == ["no hard surface mapped (grass or dirt)"]


def test_map_error_is_reported_not_raised(monkeypatch):
    def boom(url, params):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(lookups, "_arcgis_post", boom)
    assert "error" in lookups._strip_record(SIDE)


def test_every_lookup_the_agent_calls_exists():
    import re
    source = (Path(__file__).resolve().parents[1] / "agent_app" / "agent.py").read_text()
    for name in set(re.findall(r"lookups\.(\w+)", source)):
        assert hasattr(lookups, name), f"lookups.{name} is missing"

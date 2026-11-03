"""Plain-Python lookups the agent can call. No AI here: same input, same answer.

Each function returns a dict with a `source_url` so every value can be traced.
"""

import dataclasses
import json
from enum import Enum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlencode

import httpx

import lot_geometry as geo
from pivotal_engine.sources.kc_assessor_client import KCAssessorClient
from pivotal_engine.sources.kc_parcel_number import normalize_kc_parcel_number
from pivotal_engine.template_inputs import kc_record_to_inputs

TIMEOUT_S = 25
USER_AGENT = "PivotalPropertyEngine/0.1 (property analysis test)"
KC_PARCEL_LAYER = (
    "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_PropertyInfo/MapServer/2/query"
)
KC_PARCEL_VIEWER = "https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr={pin}"
SEATTLE_ARCGIS = "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services"
WA_STATE_PLANE_FT = 2926  # feet, so measurements come out in feet
WGS84 = 4326

# name shown to the agent -> (Seattle service, layer id, filter: only features matching this `where`)
SEATTLE_LAYERS = {
    "zoning": ("Current_Land_Use_Zoning_Detail_2", 0, None),
    "mha_zoning": ("Mandatory_Housing_Affordability_Zoning", 0, None),
    "mha_fee_area": ("MHA_Fee_Areas_1", 0, None),
    # SDCI walksheds (updated Dec 2025): 1/4 mile walk from a frequent stop. The older
    # Frequent_Transit_Service_Area layer is from 2023 and misses newer routes.
    "frequent_transit": ("SDCI_Transit_Stop_Walksheds", 0, "TRANSITSTOPTYPE='Frequent' AND DISTANCE=1320"),
    "eca_steep_slope": ("Environmentally_Critical_Areas_ECA", 9, None),
    "eca_potential_slide": ("Environmentally_Critical_Areas_ECA", 7, None),
    "eca_known_slide": ("Environmentally_Critical_Areas_ECA", 1, None),
    "eca_wetlands": ("Environmentally_Critical_Areas_ECA", 10, None),
    "eca_riparian": ("Environmentally_Critical_Areas_ECA", 8, None),
    "eca_flood_prone": ("Environmentally_Critical_Areas_ECA", 0, None),
    "eca_liquefaction": ("Environmentally_Critical_Areas_ECA", 5, None),
}
BELLEVUE_GIS = "https://gis-web.bellevuewa.gov/gisext/rest/services"
BELLEVUE_AGOL = "https://services1.arcgis.com/EYzEZbDhXZjURPbP/arcgis/rest/services"
BELLEVUE_AREA_LAYERS = {
    "zoning": f"{BELLEVUE_GIS}/Planning/Zoning/FeatureServer/0",
    "eca_steep_slope": f"{BELLEVUE_GIS}/Enterprise/Environmental/FeatureServer/50",
    "eca_liquefaction": f"{BELLEVUE_GIS}/Enterprise/Environmental/FeatureServer/52",
    "eca_flood_prone": f"{BELLEVUE_GIS}/Enterprise/Environmental/FeatureServer/254",
    "eca_coal_mine": f"{BELLEVUE_AGOL}/Coal_Zones/FeatureServer/3",
}
BELLEVUE_STREAMS = f"{BELLEVUE_AGOL}/Streams/FeatureServer/270"
BELLEVUE_FREQUENT_STOPS = f"{BELLEVUE_AGOL}/FrequentStops/FeatureServer/0"
STREAM_SEARCH_FT = 100
QUARTER_MILE_FT = 1320
TRANSIT_SEARCH_FT = 2640  # report stops out to half a mile so the distance is visible
SEATTLE_RIGHT_OF_WAY = f"{SEATTLE_ARCGIS}/Right_of_Way_Polygon/FeatureServer/0"
SEATTLE_SURFACES = f"{SEATTLE_ARCGIS}/Impervious_Surface_2015/FeatureServer/0"  # traced from 2015 aerials
ROW_KINDS = MappingProxyType({2: "street right-of-way", 9: "alley right-of-way", 6: "easement", 7: "tract",
                              40: "private road", 1: "lot", 5: "agency property"})
SURFACE_KINDS = MappingProxyType({"STR": "street or alley", "DRV": "driveway", "PRK": "parking lot",
                                  "WLK": "walkway or patio", "SDW": "sidewalk", "LND": "landscaping"})
FINISHES = MappingProxyType({"SOL": "solid (paved)", "PAK": "discontinuous (gravel or broken)",
                             "VEG": "vegetated", "OTH": "other"})
DROP_FIELDS = {"OBJECTID", "Shape__Area", "Shape__Length", "SHAPE_Length", "SHAPE_Area", "GlobalID"}


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (MappingProxyType, dict)):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Enum):
        return obj.value
    return obj


def _arcgis_query(url: str, params: dict) -> tuple[dict, str]:
    full = f"{url}?{urlencode({**params, 'f': 'json'})}"
    resp = httpx.get(full, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return _check(resp.json()), full


def _arcgis_post(url: str, params: dict) -> dict:
    """POST for queries whose geometry is too long for a URL."""
    resp = httpx.post(url, data={**params, "f": "json"}, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return _check(resp.json())


def _check(data: dict) -> dict:
    if "error" in data:
        raise RuntimeError(f"map service error: {data['error'].get('message')}")
    return data


# ---------- King County assessor record (already-built engine) ----------

def kc_assessor(parcel_number: str) -> dict:
    with KCAssessorClient() as client:
        record = client.fetch_detail(parcel_number)
    return {
        "source_url": KC_PARCEL_VIEWER.format(pin=record.parcel_number),
        "suggested_cells": _jsonable(kc_record_to_inputs(record)),
        "record": _jsonable(record),
    }


# ---------- King County parcel shape + measurements ----------

def _lot_ring(pin: str) -> tuple[list[tuple[float, float]], dict, str]:
    base = {"where": f"PIN='{pin}'", "outFields": "*", "returnGeometry": "true", "outSR": WA_STATE_PLANE_FT}
    data, url = _arcgis_query(KC_PARCEL_LAYER, base)
    if not data.get("features"):
        return [], {}, url
    feature = data["features"][0]
    return [tuple(p) for p in feature["geometry"]["rings"][0]], feature, url


def _neighbour_rings(pin: str, lot: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    xs, ys = [p[0] for p in lot], [p[1] for p in lot]
    pad = geo.RAY_MAX_FT
    envelope = {"xmin": min(xs) - pad, "ymin": min(ys) - pad, "xmax": max(xs) + pad, "ymax": max(ys) + pad,
                "spatialReference": {"wkid": WA_STATE_PLANE_FT}}
    data = _arcgis_post(KC_PARCEL_LAYER, {
        "geometry": json.dumps(envelope), "geometryType": "esriGeometryEnvelope", "inSR": WA_STATE_PLANE_FT,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "PIN", "returnGeometry": "true",
        "outSR": WA_STATE_PLANE_FT,
    })
    return [
        [tuple(p) for p in ring]
        for f in data.get("features", []) if f["attributes"].get("PIN") != pin
        for ring in f["geometry"]["rings"]
    ]


def kc_parcel_map(parcel_number: str) -> dict:
    pin = normalize_kc_parcel_number(parcel_number)
    lot, feature, url = _lot_ring(pin)
    if not lot:
        return {"source_url": url, "found": False, "note": "parcel not on the county map"}
    short_side, long_side, short_dir = geo.min_rectangle(lot)
    area = geo.polygon_area(lot)
    sides = geo.lot_sides(lot, _neighbour_rings(pin, lot))
    width = geo.lot_width(sides, short_dir, short_side)
    lonlat, _ = _arcgis_query(KC_PARCEL_LAYER, {"where": f"PIN='{pin}'", "outFields": "PIN", "returnGeometry": "true", "outSR": WGS84})
    ll = lonlat["features"][0]["geometry"]["rings"][0]
    return {
        "source_url": url,
        "found": True,
        "attributes": {k: v for k, v in feature["attributes"].items() if k not in DROP_FIELDS},
        "measurements_ft": {
            "polygon_area_sqft": round(area),
            "bounding_rectangle_short_side": round(short_side, 1),
            "bounding_rectangle_long_side": round(long_side, 1),
            "rectangularity": round(area / (short_side * long_side), 2),
        },
        "sides": [s._asdict() for s in sides],
        "frontage": {
            **width,
            "street_sides": sum(s.kind == "street" for s in sides),
            "alley_sides": sum(s.kind == "alley" for s in sides),
            "how_sides_were_read": "gap to the parcel across each side: 0-2 ft neighbour, "
                                   "2-30 ft alley or narrow strip, over 30 ft street, nothing within 150 ft open",
        },
        "center": {"lat": round(sum(p[1] for p in ll) / len(ll), 6), "lon": round(sum(p[0] for p in ll) / len(ll), 6)},
    }


# ---------- city layers over the whole lot ----------

def _lot_grid(parcel_number: str) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    lot, _, _ = _lot_ring(normalize_kc_parcel_number(parcel_number))
    return lot, (geo.grid_points(lot) if lot else [])


def _grid_query(grid: list[tuple[float, float]], **extra: Any) -> dict:
    multipoint = json.dumps({"points": [list(p) for p in grid], "spatialReference": {"wkid": WA_STATE_PLANE_FT}})
    return {
        "geometry": multipoint, "geometryType": "esriGeometryMultipoint", "inSR": WA_STATE_PLANE_FT,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "outSR": WA_STATE_PLANE_FT, **extra,
    }


def _area_layer(layer_url: str, grid: list[tuple[float, float]], where: str | None = None) -> dict:
    """Polygons touching any part of the lot, with each one's share of the lot."""
    try:
        query = _grid_query(grid, returnGeometry="true", maxAllowableOffset=1, **({"where": where} if where else {}))
        features = _arcgis_post(f"{layer_url}/query", query).get("features", [])
    except (httpx.HTTPError, RuntimeError) as exc:
        return {"source_url": layer_url, "error": str(exc)}
    return {"source_url": layer_url, **_coverage(features, grid)}


def _coverage(features: list[dict], grid: list[tuple[float, float]]) -> dict:
    hits = []
    for f in features:
        rings = [[tuple(p) for p in r] for r in (f.get("geometry") or {}).get("rings", [])]
        share = sum(geo.point_in_rings(p, rings) for p in grid) / len(grid) if rings else None
        attrs = {k: v for k, v in f["attributes"].items() if k not in DROP_FIELDS and v not in (None, "", " ")}
        hits = [*hits, {"share_of_lot": None if share is None else round(share, 2), "attributes": attrs}]
    hits = sorted(hits, key=lambda h: -(h["share_of_lot"] or 0))
    return {"inside": bool(hits), "features": hits[:3]}


def _nearby_layer(layer_url: str, lot: list[tuple[float, float]], grid: list[tuple[float, float]],
                  within_ft: float, name_field: str | None = None) -> dict:
    """Lines or points within `within_ft` of the lot, with the nearest distance to the lot edge."""
    try:
        query = _grid_query(grid, returnGeometry="true", distance=within_ft, units="esriSRUnit_Foot")
        features = _arcgis_post(f"{layer_url}/query", query).get("features", [])
    except (httpx.HTTPError, RuntimeError) as exc:
        return {"source_url": layer_url, "error": str(exc)}
    found = sorted(
        ({"distance_ft": round(geo.distance_to_lot(_feature_points(f), lot)),
          "name": f["attributes"].get(name_field) if name_field else None} for f in features),
        key=lambda h: h["distance_ft"],
    )
    return {"source_url": layer_url, "searched_within_ft": within_ft, "count": len(found),
            "nearest_ft": found[0]["distance_ft"] if found else None, "nearest": found[:3]}


def _feature_points(feature: dict) -> list[tuple[float, float]]:
    g = feature.get("geometry") or {}
    if "x" in g:
        return [(g["x"], g["y"])]
    return [tuple(p) for part in g.get("paths", []) + g.get("rings", []) for p in part]


def seattle_layers(parcel_number: str) -> dict:
    lot, grid = _lot_grid(parcel_number)
    if not lot:
        return {"error": "parcel not on the county map"}
    layers = {
        name: _area_layer(f"{SEATTLE_ARCGIS}/{service}/FeatureServer/{layer}", grid, where)
        for name, (service, layer, where) in SEATTLE_LAYERS.items()
    }
    pin = normalize_kc_parcel_number(parcel_number)
    return {"checked_points_across_lot": len(grid), "layers": layers, "narrow_strips": _seattle_strips(pin, lot)}


def _seattle_strips(pin: str, lot: list[tuple[float, float]]) -> list[dict]:
    """For each 2-30 ft strip beside the lot: is it a street or alley in the city's street network?"""
    strips = [s for s in geo.lot_sides(lot, _neighbour_rings(pin, lot)) if s.kind == "alley" and s.gap_point]
    return [_strip_record(s) for s in strips]


def _strip_record(side: geo.Side) -> dict:
    """What the city's maps say is in the strip: legal right-of-way kind, and the surface on the ground."""
    point = json.dumps({"x": side.gap_point[0], "y": side.gap_point[1], "spatialReference": {"wkid": WA_STATE_PLANE_FT}})
    query = {"geometry": point, "geometryType": "esriGeometryPoint", "inSR": WA_STATE_PLANE_FT,
             "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "false"}
    base = {"side_length_ft": side.length_ft, "strip_width_ft": side.gap_ft,
            "source_url": SEATTLE_RIGHT_OF_WAY, "surface_source_url": SEATTLE_SURFACES}
    try:
        row = _arcgis_post(f"{SEATTLE_RIGHT_OF_WAY}/query", {**query, "outFields": "L_FEA_SYM"}).get("features", [])
        ground = _arcgis_post(f"{SEATTLE_SURFACES}/query", {
            **query, "outFields": "IMPSURF_FEATYPE_CODE,IMPSURF_SURFTYPE_CODE"}).get("features", [])
    except (httpx.HTTPError, RuntimeError) as exc:
        return {**base, "error": str(exc)}
    legal = [ROW_KINDS.get(f["attributes"].get("L_FEA_SYM"), "other") for f in row]
    surface = [{"kind": SURFACE_KINDS.get(f["attributes"].get("IMPSURF_FEATYPE_CODE"), "other"),
                "finish": FINISHES.get(f["attributes"].get("IMPSURF_SURFTYPE_CODE"), "other")} for f in ground]
    return {**base, "legal_status": legal or ["no right-of-way record"],
            "surface_2015": surface or ["no hard surface mapped (grass or dirt)"]}


def bellevue_layers(parcel_number: str) -> dict:
    lot, grid = _lot_grid(parcel_number)
    if not lot:
        return {"error": "parcel not on the county map"}
    layers = {name: _area_layer(url, grid) for name, url in BELLEVUE_AREA_LAYERS.items()}
    layers = {
        **layers,
        "eca_stream": _nearby_layer(BELLEVUE_STREAMS, lot, grid, STREAM_SEARCH_FT, "NAME"),
        "frequent_transit_stops": {
            **_nearby_layer(BELLEVUE_FREQUENT_STOPS, lot, grid, TRANSIT_SEARCH_FT, "StopID"),
            "quarter_mile_ft": QUARTER_MILE_FT,
        },
    }
    return {"checked_points_across_lot": len(grid), "layers": layers}


# ---------- permit history (county record + Seattle open data) ----------

SEATTLE_PERMIT_DATASETS = MappingProxyType({
    "building": "https://data.seattle.gov/resource/76t5-zqzr.json",
    "electrical": "https://data.seattle.gov/resource/c4tj-daue.json",
    "trade": "https://data.seattle.gov/resource/c87v-5hwh.json",  # plumbing, mechanical, side sewer...
})
PERMIT_FIELDS = "permitnum,permittypemapped,permitclass,description,issueddate,statuscurrent,link"
MAX_PERMITS_PER_DATASET = 50


def permit_history(parcel_number: str) -> dict:
    """Every permit on record for the lot, newest first. No judgement here: the agent applies the rules."""
    with KCAssessorClient() as client:
        record = client.fetch_detail(parcel_number)
    county = {
        "source_url": KC_PARCEL_VIEWER.format(pin=record.parcel_number),
        "permits": [_jsonable(p) for p in record.permits],
    }
    result = {"address": record.site_address, "jurisdiction": record.jurisdiction, "county_record": county}
    if record.jurisdiction.strip().upper() != "SEATTLE":
        return {**result, "city_permits": "no city permit data source for this jurisdiction yet"}
    return {**result, "seattle_permits": {
        kind: _seattle_permits(url, record.site_address) for kind, url in SEATTLE_PERMIT_DATASETS.items()}}


def _seattle_permits(dataset_url: str, site_address: str) -> dict:
    street = _street_part(site_address)
    if not street:
        return {"source_url": dataset_url, "error": "no street address on the county record"}
    params = {"$where": f"upper(originaladdress1) like '{street}%'", "$select": PERMIT_FIELDS,
              "$order": "issueddate DESC", "$limit": MAX_PERMITS_PER_DATASET}
    try:
        resp = httpx.get(dataset_url, params=params, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"source_url": dataset_url, "error": str(exc)}
    permits = [{
        "number": r.get("permitnum"), "type": r.get("permittypemapped"), "class": r.get("permitclass"),
        "description": (r.get("description") or "")[:300], "issued": (r.get("issueddate") or "")[:10],
        "status": r.get("statuscurrent"), "source_url": _link_url(r.get("link")) or dataset_url,
    } for r in rows]
    return {"source_url": f"{dataset_url}?{urlencode(params)}", "searched_address": street, "permits": permits}


def _link_url(link: object) -> str | None:
    """Socrata url columns come back as {"url": "..."}; older rows may be a plain string."""
    if isinstance(link, dict):
        link = link.get("url")
    return link if isinstance(link, str) and link.startswith("https://") else None


def _street_part(site_address: str) -> str:
    """'3302 S ORCAS ST 98118' -> '3302 S ORCAS ST'. Letters, digits and spaces only (safe in a query)."""
    words = site_address.upper().replace(",", " ").split()
    while words and words[-1].isdigit() and len(words[-1]) == 5:  # drop a trailing ZIP
        words = words[:-1]
    return " ".join(w for w in ("".join(ch for ch in word if ch.isalnum()) for word in words) if w)


# ---------- address -> parcel number ----------

STREET_WORDS = MappingProxyType({
    "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "PLACE": "PL", "ROAD": "RD", "DRIVE": "DR", "COURT": "CT",
    "BOULEVARD": "BLVD", "LANE": "LN", "TERRACE": "TER", "CIRCLE": "CIR", "PARKWAY": "PKWY", "HIGHWAY": "HWY",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
})
STATE_WORDS = frozenset({"WA", "WASHINGTON", "USA"})
MAX_CANDIDATES = 5


def normalize_street(address: str) -> str:
    """'1256 111th Avenue Northeast, Bellevue, WA 98004' -> '1256 111TH AVE NE' (county style).

    Only letters, digits and spaces are kept, so the result is safe inside a map query.
    """
    street = address.split(",")[0].upper()
    words = ["".join(ch for ch in w if ch.isalnum()) for w in street.split()]
    words = [STREET_WORDS.get(w, w) for w in words if w]
    while words and (words[-1] in STATE_WORDS or (words[-1].isdigit() and len(words[-1]) == 5)):
        words = words[:-1]
    return " ".join(words)


def find_parcel(address: str) -> dict:
    """Find the King County parcel for a street address. City or ZIP in the text breaks ties."""
    street = normalize_street(address)
    if not street or not street.split()[0].isdigit():
        return {"parcel_number": None, "candidates": [], "note": "start the address with the house number"}
    rows = _parcels_on(street)
    words = street.split()
    while not rows and len(words) > 2:  # e.g. a city name written without a comma
        words = words[:-1]
        rows = _parcels_on(" ".join(words))
    rows = _narrow_by_place(rows, address.upper())
    candidates = [{"parcel_number": r["PIN"], "address": f"{r['ADDR_FULL']}, {r['CTYNAME']} {r['ZIP5']}"}
                  for r in rows[:MAX_CANDIDATES]]
    found = candidates[0]["parcel_number"] if len(candidates) == 1 else None
    note = "" if found else ("no parcel with that address" if not candidates else "several parcels match")
    return {"parcel_number": found, "candidates": candidates, "searched": street, "note": note}


def _parcels_on(street: str) -> list[dict]:
    data, _ = _arcgis_query(KC_PARCEL_LAYER, {"where": f"ADDR_FULL LIKE '{street}%'",
                                              "outFields": "PIN,ADDR_FULL,CTYNAME,ZIP5", "returnGeometry": "false"})
    return [f["attributes"] for f in data.get("features", [])]


def _narrow_by_place(rows: list[dict], text: str) -> list[dict]:
    if len(rows) < 2:
        return rows
    narrowed = [r for r in rows if (r.get("ZIP5") and r["ZIP5"] in text)
                or (r.get("CTYNAME") and r["CTYNAME"].upper() in text)]
    return narrowed or rows

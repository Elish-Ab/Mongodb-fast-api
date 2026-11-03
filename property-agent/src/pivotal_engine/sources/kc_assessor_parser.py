"""Read King County eRealProperty pages (Detail.aspx and Dashboard.aspx) into records.

The pages are ASP.NET tables with stable ids such as cphContent_DetailsViewResBldg.
Two layouts appear:
  * label/value tables: each row has two cells, "1st Floor" | "879"
  * grids: a header row followed by data rows (permits, tax roll, accessories)
"""

import math
import re
from types import MappingProxyType
from typing import Optional

from bs4 import BeautifulSoup, Tag

from pivotal_engine.errors import PageFormatChanged, ParcelNotFound
from pivotal_engine.sources.kc_assessor_models import (
    KCAccessory,
    KCAssessorRecord,
    KCBuilding,
    KCDashboardSummary,
    KCLand,
    KCPermit,
)

BASE_URL = "https://blue.kingcounty.com/Assessor/eRealProperty"
DETAIL_URL = BASE_URL + "/Detail.aspx?ParcelNbr={parcel}"
DASHBOARD_URL = BASE_URL + "/Dashboard.aspx?ParcelNbr={parcel}"
_NOT_FOUND_TEXT = "no data found"


# ---------- small helpers ----------

def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _label_values(soup: BeautifulSoup, table_id: str) -> dict[str, str]:
    table = soup.find("table", id=table_id)
    if not isinstance(table, Tag):
        return {}
    pairs: dict[str, str] = {}
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) == 2:
            pairs[cells[0].get_text(" ", strip=True)] = cells[1].get_text(" ", strip=True)
    return pairs


def _grid_rows(soup: BeautifulSoup, table_id: str) -> list[dict[str, str]]:
    table = soup.find("table", id=table_id)
    if not isinstance(table, Tag):
        return []
    rows = table.find_all("tr", recursive=False) or table.find_all("tr")
    if not rows:
        return []
    header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    data = []
    for row in rows[1:]:
        values = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        if len(values) == len(header) and any(values):  # skip pager / spacer rows
            data.append(dict(zip(header, values)))
    return data


def _to_float(text: Optional[str]) -> Optional[float]:
    cleaned = (text or "").replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _to_int(text: Optional[str]) -> Optional[int]:
    number = _to_float(text)
    return int(number) if number is not None else None


def _area(values: dict[str, str], label: str) -> Optional[int]:
    """Floor area in sq ft; None when the label is missing (never a silent 0)."""
    return _to_int(values.get(label)) if label in values else None


def _year(text: Optional[str]) -> Optional[int]:
    year = _to_int(text)
    return year if year else None  # the county writes 0 for "none"


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _check_page(soup: BeautifulSoup, required_table: str) -> None:
    message = soup.find(id="cphContent_LblMsg")
    if isinstance(message, Tag) and _NOT_FOUND_TEXT in message.get_text(strip=True).lower():
        raise ParcelNotFound("King County has no record for this parcel number.")
    if soup.find("table", id=required_table) is None:
        raise PageFormatChanged(
            f"The King County page is missing '{required_table}'. The site may be down or its layout changed."
        )


# ---------- section parsers ----------

def _parse_land(soup: BeautifulSoup) -> KCLand:
    land = _label_values(soup, "cphContent_DetailsViewLand")
    system = _label_values(soup, "cphContent_DetailsViewLandSystem")
    designations = _label_values(soup, "cphContent_DetailsViewLandDesignations")
    nuisances = _label_values(soup, "cphContent_DetailsViewLandNuisances")
    enviro = _label_values(soup, "cphContent_DetailsViewLandEnviro")
    waterfront = _label_values(soup, "cphContent_DetailsViewLandWaterfront")
    views = {k: v for k, v in _label_values(soup, "cphContent_DetailsViewLandViews").items() if v}
    return KCLand(
        present_use=land.get("Present Use", ""),
        land_sqft=_to_int(land.get("Land SqFt")),
        acres=_to_float(land.get("Acres")),
        zoning=system.get("Zoning", ""),
        water=system.get("Water", ""),
        sewer_septic=system.get("Sewer/Septic", ""),
        road_access=system.get("Road Access", ""),
        unbuildable=system.get("Unbuildable", ""),
        restrictive_size_shape=system.get("Restrictive Size Shape", ""),
        easements=designations.get("Easements", ""),
        environmental=enviro.get("Environmental", ""),
        topography=nuisances.get("Topography", ""),
        traffic_noise=nuisances.get("Traffic Noise", ""),
        airport_noise=nuisances.get("Airport Noise", ""),
        power_lines=nuisances.get("Power Lines", ""),
        other_nuisances=nuisances.get("Other Nuisances", ""),
        waterfront_location=waterfront.get("Waterfront Location", ""),
        views=MappingProxyType(views),
    )


def _parse_building(values: dict[str, str]) -> KCBuilding:
    return KCBuilding(
        building_number=_to_int(values.get("Building Number")) or 1,
        year_built=_year(values.get("Year Built")),
        year_renovated=_year(values.get("Year Renovated")),
        stories=_to_float(values.get("Stories")),
        living_units=_to_int(values.get("Living Units")),
        grade=values.get("Grade", ""),
        condition=values.get("Condition", ""),
        first_floor=_area(values, "1st Floor"),
        half_floor=_area(values, "1/2 Floor"),
        second_floor=_area(values, "2nd Floor"),
        upper_floor=_area(values, "Upper Floor"),
        finished_basement=_area(values, "Finished Basement"),
        total_basement=_area(values, "Total Basement"),
        basement_garage=_area(values, "Basement Garage"),
        attached_garage=_area(values, "Attached Garage"),
        bedrooms=_to_int(values.get("Bedrooms")),
    )


_BUILDING_TABLE = re.compile(r"^cphContent_DetailsViewResBldg")
REQUIRED_BUILDING_LABELS = ("Year Built", "1st Floor", "2nd Floor", "Total Basement", "Basement Garage")


def _parse_buildings(soup: BeautifulSoup) -> tuple[KCBuilding, ...]:
    buildings = []
    for table in soup.find_all("table", id=_BUILDING_TABLE):
        values = _label_values(soup, table["id"])
        if not values:
            continue
        missing = [label for label in REQUIRED_BUILDING_LABELS if label not in values]
        if missing:
            raise PageFormatChanged(
                f"The King County building table no longer has {', '.join(missing)}. Update the parser."
            )
        buildings.append(_parse_building(values))
    return tuple(buildings)


def _parse_accessories(soup: BeautifulSoup) -> tuple[KCAccessory, ...]:
    return tuple(
        KCAccessory(
            type=row.get("Accessory Type", ""),
            description=row.get("Description", ""),
            sqft=_to_int(row.get("SqFt")),
        )
        for row in _grid_rows(soup, "cphContent_GridViewResBldgAccessory")
    )


def _parse_permits(soup: BeautifulSoup) -> tuple[KCPermit, ...]:
    return tuple(
        KCPermit(
            number=row.get("Permit Number", ""),
            description=row.get("Permit Description", ""),
            type=row.get("Type", ""),
            issue_date=row.get("Issue Date", ""),
            value=row.get("Permit Value", ""),
            jurisdiction=row.get("Issuing Jurisdiction", ""),
        )
        for row in _grid_rows(soup, "cphContent_GridViewPermits")
    )


# ---------- public API ----------

def parse_detail_page(html: str) -> KCAssessorRecord:
    """Parse eRealProperty Detail.aspx. Raises ParcelNotFound or PageFormatChanged."""
    soup = _soup(html)
    _check_page(soup, "cphContent_DetailsViewParcel")
    parcel = _label_values(soup, "cphContent_DetailsViewParcel")
    parcel2 = _label_values(soup, "cphContent_DetailsViewParcel2")
    parcel_number = _digits(parcel.get("Parcel", ""))
    if not parcel_number:
        raise PageFormatChanged("The King County page has no parcel number. Update the parser.")
    return KCAssessorRecord(
        parcel_number=parcel_number,
        site_address=parcel.get("Site Address", ""),
        jurisdiction=parcel2.get("Jurisdiction", ""),
        land=_parse_land(soup),
        buildings=_parse_buildings(soup),
        accessories=_parse_accessories(soup),
        permits=_parse_permits(soup),
        source_url=DETAIL_URL.format(parcel=parcel_number),
    )


def parse_dashboard_page(html: str) -> KCDashboardSummary:
    """Parse eRealProperty Dashboard.aspx (the summary page)."""
    soup = _soup(html)
    _check_page(soup, "cphContent_DetailsViewDashboardHeader")
    header = _label_values(soup, "cphContent_DetailsViewDashboardHeader")
    facts = _label_values(soup, "cphContent_DetailsViewPropTypeR")
    parcel_number = _digits(header.get("Parcel Number", ""))
    if not parcel_number:
        raise PageFormatChanged("The King County summary page has no parcel number. Update the parser.")
    return KCDashboardSummary(
        parcel_number=parcel_number,
        site_address=header.get("Site Address", ""),
        year_built=_year(facts.get("Year Built")),
        total_sqft=_to_int(facts.get("Total Square Footage")),
        lot_size=_to_int(facts.get("Lot Size")),
        grade=facts.get("Grade", ""),
        condition=facts.get("Condition", ""),
        source_url=DASHBOARD_URL.format(parcel=parcel_number),
    )

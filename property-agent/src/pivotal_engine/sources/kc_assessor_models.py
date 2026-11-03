"""Immutable records for data read from the King County Assessor (eRealProperty)."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional


@dataclass(frozen=True)
class KCLand:
    present_use: str
    land_sqft: Optional[int]
    acres: Optional[float]
    zoning: str
    water: str
    sewer_septic: str
    road_access: str
    unbuildable: str
    restrictive_size_shape: str
    easements: str
    environmental: str
    topography: str
    traffic_noise: str
    airport_noise: str
    power_lines: str
    other_nuisances: str
    waterfront_location: str
    views: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class KCBuilding:
    building_number: int
    year_built: Optional[int]
    year_renovated: Optional[int]  # None when the county shows 0 (never renovated)
    stories: Optional[float]
    living_units: Optional[int]
    grade: str
    condition: str
    # Areas in sq ft. None means the county page did not show the field.
    first_floor: Optional[int]
    half_floor: Optional[int]
    second_floor: Optional[int]
    upper_floor: Optional[int]
    finished_basement: Optional[int]
    total_basement: Optional[int]
    basement_garage: Optional[int]
    attached_garage: Optional[int]
    bedrooms: Optional[int]


@dataclass(frozen=True)
class KCAccessory:
    type: str
    description: str
    sqft: Optional[int]


@dataclass(frozen=True)
class KCPermit:
    number: str
    description: str
    type: str
    issue_date: str
    value: str
    jurisdiction: str


@dataclass(frozen=True)
class KCAssessorRecord:
    parcel_number: str
    site_address: str
    jurisdiction: str
    land: KCLand
    buildings: tuple[KCBuilding, ...]
    accessories: tuple[KCAccessory, ...]
    permits: tuple[KCPermit, ...]
    source_url: str


@dataclass(frozen=True)
class KCDashboardSummary:
    parcel_number: str
    site_address: str
    year_built: Optional[int]
    total_sqft: Optional[int]
    lot_size: Optional[int]
    grade: str
    condition: str
    source_url: str

"""Turn source records into values for the Property Analysis Template's Inputs tab.

Each value carries a status and a source link so an analyst can verify it.
Values must match the template's dropdown options exactly; anything that is
missing or doesn't fit is left blank and marked CHECK, never guessed.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from pivotal_engine.sources.kc_assessor_models import KCAssessorRecord, KCBuilding

CellValue = Union[str, int, float, None]


class Status(str, Enum):
    RECORD = "record"  # copied from an official record
    MEASURED = "measured"  # calculated from official map data
    CHECK = "check"  # filled or left blank, but a person should look
    MANUAL = "manual"  # needs a person


@dataclass(frozen=True)
class InputValue:
    cell: str
    label: str
    value: CellValue
    status: Status
    source: str
    note: str = ""


# Inputs!B21 dropdown: Seattle, Bellevue, Kirkland, Other, Redmond
JURISDICTIONS = {"SEATTLE": "Seattle", "BELLEVUE": "Bellevue", "KIRKLAND": "Kirkland", "REDMOND": "Redmond"}

# Inputs!B39 dropdown: Vacant Land, Single Family, Duplex, Triplex, Fourplex.
# Matched on the county's present-use text before any "(" qualifier, ignoring case.
PRESENT_USE_OPTIONS = {
    "single family": "Single Family",
    "duplex": "Duplex",
    "triplex": "Triplex",
    "4-plex": "Fourplex",
    "fourplex": "Fourplex",
    "vacant(single-family)": "Vacant Land",
    "vacant": "Vacant Land",
}

FLOOR_CELLS = (
    ("B40", "1st Floor", "first_floor"),
    ("B41", "1/2 Floor", "half_floor"),
    ("B42", "2nd Floor", "second_floor"),
    ("B43", "Upper Floor", "upper_floor"),
    ("B44", "Total Basement", "total_basement"),
    ("B45", "Basement Garage", "basement_garage"),
)


def _structure_type(present_use: str) -> Optional[str]:
    key = present_use.casefold().strip()
    if key in PRESENT_USE_OPTIONS:
        return PRESENT_USE_OPTIONS[key]
    return PRESENT_USE_OPTIONS.get(key.split("(")[0].strip())


def _value_or_check(cell: str, label: str, value: CellValue, src: str, missing_note: str) -> InputValue:
    if value is None:
        return InputValue(cell, label, None, Status.CHECK, src, missing_note)
    return InputValue(cell, label, value, Status.RECORD, src)


def _jurisdiction(record: KCAssessorRecord, src: str) -> InputValue:
    county = record.jurisdiction.strip().upper()
    if not county:
        return InputValue("B21", "Jurisdiction", None, Status.CHECK, src, "County page shows no jurisdiction.")
    return InputValue("B21", "Jurisdiction", JURISDICTIONS.get(county, "Other"), Status.RECORD, src,
                      f"County jurisdiction: {record.jurisdiction}")


def _structure(record: KCAssessorRecord, src: str) -> InputValue:
    present_use = record.land.present_use
    option = _structure_type(present_use)
    if option:
        return InputValue("B39", "Type of Structure", option, Status.RECORD, src)
    return InputValue("B39", "Type of Structure", None, Status.CHECK, src,
                      f"County present use '{present_use}' has no matching dropdown option.")


def _building_inputs(record: KCAssessorRecord, building: KCBuilding, src: str) -> list[InputValue]:
    inputs = [
        _value_or_check(cell, label, getattr(building, attr), src, f"County page did not show {label}.")
        for cell, label, attr in FLOOR_CELLS
    ]
    flags = []
    if building.living_units and building.living_units > 1:
        flags.append(f"{building.living_units} living units")
    if len(record.buildings) > 1:
        flags.append(f"{len(record.buildings)} buildings on record; only building 1 is mapped")
    if flags:
        b40 = inputs[0]
        inputs[0] = InputValue(b40.cell, b40.label, b40.value, Status.CHECK, src,
                               "; ".join(flags) + ". Check floors and enter any second unit in column D.")

    # The team fills "Year Renovated" with the later of year built / renovated
    # (see the completed analyses); B52 then takes the latest update year.
    years = [y for y in (building.year_built, building.year_renovated) if y]
    inputs.append(_value_or_check(
        "B50", "Year Renovated (latest of built/renovated)", max(years) if years else None, src,
        "County page shows no year built.",
    ))
    return inputs


def kc_record_to_inputs(record: KCAssessorRecord) -> tuple[InputValue, ...]:
    """Map a King County assessor record to template input cells."""
    src = record.source_url
    inputs = [
        _value_or_check("B6", "Lot Size", record.land.land_sqft, src, "County page shows no lot size."),
        _jurisdiction(record, src),
        _structure(record, src),
    ]
    if record.buildings:
        inputs.extend(_building_inputs(record, record.buildings[0], src))
    else:
        inputs.append(InputValue("B40", "1st Floor", None, Status.CHECK, src, "No residential building on record."))
    return tuple(inputs)

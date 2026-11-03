import pytest

from pivotal_engine.errors import InvalidParcelNumber
from pivotal_engine.sources.kc_parcel_number import normalize_kc_parcel_number


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9331800500", "9331800500"),
        ("933180-0500", "9331800500"),
        (" 933180 0500 ", "9331800500"),
        ("331800500", "0331800500"),  # leading zero dropped by spreadsheets
    ],
)
def test_normalizes_common_formats(raw, expected):
    assert normalize_kc_parcel_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "27053300204900", "93318005", "9331800500x"])
def test_rejects_values_that_are_not_king_county_parcels(raw):
    with pytest.raises(InvalidParcelNumber):
        normalize_kc_parcel_number(raw)

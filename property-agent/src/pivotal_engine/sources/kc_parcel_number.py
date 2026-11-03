"""King County parcel numbers: 10 digits, often written as 6-4 (933180-0500)."""

import re

from pivotal_engine.errors import InvalidParcelNumber

KC_PARCEL_LENGTH = 10
_SEPARATORS = re.compile(r"[\s\-]")
_ASCII_DIGITS = re.compile(r"[0-9]+")


def normalize_kc_parcel_number(raw: str) -> str:
    """Return the 10-digit form of a King County parcel number.

    Accepts dashes and spaces, and restores a single leading zero that
    spreadsheets often drop. Raises InvalidParcelNumber otherwise.
    """
    digits = _SEPARATORS.sub("", raw or "")
    if not _ASCII_DIGITS.fullmatch(digits):
        raise InvalidParcelNumber(f"'{raw}' is not a King County parcel number (expected 10 digits).")
    if len(digits) == KC_PARCEL_LENGTH - 1:
        digits = "0" + digits
    if len(digits) != KC_PARCEL_LENGTH:
        raise InvalidParcelNumber(
            f"'{raw}' has {len(digits)} digits; King County parcel numbers have 10. "
            "Snohomish parcel numbers have 14 and need the Snohomish source."
        )
    return digits

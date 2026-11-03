"""Errors raised by the engine. Each one tells the analyst what to do next."""


class EngineError(Exception):
    """Base class for all engine errors."""


class InvalidParcelNumber(EngineError):
    """The value given is not a valid parcel number for this county."""


class ParcelNotFound(EngineError):
    """The county has no record for this parcel number."""


class SourceUnavailable(EngineError):
    """The county website could not be reached or returned an error."""


class PageFormatChanged(EngineError):
    """The county page loaded but no longer looks the way the parser expects."""

"""Command line: look up a King County parcel and print template inputs as JSON.

    python -m pivotal_engine 9331800500
    python -m pivotal_engine 933180-0500 --raw    # full assessor record
"""

import argparse
import dataclasses
import json
import logging
import sys
from enum import Enum
from types import MappingProxyType
from typing import Any, Optional, Sequence

from pivotal_engine.errors import EngineError
from pivotal_engine.sources.kc_assessor_client import KCAssessorClient
from pivotal_engine.template_inputs import kc_record_to_inputs


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Look up a King County parcel for the Property Analysis Template.")
    parser.add_argument("parcel", help="King County parcel number, e.g. 9331800500 or 933180-0500")
    parser.add_argument("--raw", action="store_true", help="print the full assessor record instead of template inputs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    try:
        with KCAssessorClient() as client:
            record = client.fetch_detail(args.parcel)
    except EngineError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    payload = record if args.raw else kc_record_to_inputs(record)
    sys.stdout.write(json.dumps(_jsonable(payload), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

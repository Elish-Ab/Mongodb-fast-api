"""The property agent: King County APN in, checked Inputs-tab cells out.

Used by the command line (run_agent.py) and the web service (service.py). Each call to
`analyze` has its own state, so several analyses can run at once.
"""

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import anthropic  # noqa: E402
from anthropic import beta_tool  # noqa: E402

import lookups  # noqa: E402
from pivotal_engine.sources.kc_parcel_number import normalize_kc_parcel_number  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 15
PRICE_PER_MTOK = {"input": 4.00, "output": 20.00}  # USD, Opus 5.5
REQUIRED_CELLS = ("B3", "B6", "B7", "B11", "B12", "B13", "B14", "B16", "B21", "B23", "B25", "B26",
                  "B39", "B40", "B41", "B42", "B43", "B44", "B45", "B50", "B51")

STATUSES = ("record", "measured", "check", "missing")
FORMULA_START = ("=", "+", "-", "@")  # a sheet would treat text starting with these as a formula

Log = Callable[[str], None]


class AgentFailed(RuntimeError):
    """The agent stopped without handing in its answers."""


class CellInput(TypedDict):
    cell: str
    value: str
    status: Literal["record", "measured", "check", "missing"]
    source_url: str
    note: str


@dataclass
class Run:
    """State for one analysis: what the tools returned and what the agent handed in."""
    log: Log = print
    seen_sources: set[str] = field(default_factory=set)
    submitted: list[dict] = field(default_factory=list)

    def collect_sources(self, obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.endswith("source_url") and isinstance(value, str):
                    self.seen_sources.add(value)
                else:
                    self.collect_sources(value)
        elif isinstance(obj, list):
            for value in obj:
                self.collect_sources(value)

    def call(self, name: str, fn: Callable, *args: str) -> str:
        started = time.monotonic()
        try:
            result = fn(*args)
        except Exception as exc:  # report the failure to the agent instead of crashing the run
            self.log(f"  ✗ {name}{args} failed: {exc}")
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        self.collect_sources(result)
        self.log(f"  ✓ {name}{args}  ({time.monotonic() - started:.1f}s)")
        return json.dumps(result, default=str)

    def submit(self, items: list | str) -> str:
        if isinstance(items, str):  # the model sometimes sends the list as JSON text
            try:
                items = json.loads(items)
            except json.JSONDecodeError as exc:
                return json.dumps({"error": f"items must be a JSON list of cells: {exc}. Send it again."})
        if not isinstance(items, list) or not all(isinstance(i, dict) and "cell" in i for i in items):
            return json.dumps({"error": "items must be a list of {cell, value, status, source_url, note}. "
                                        "Send it again."})
        self.submitted.extend(items)
        missing = sorted(set(REQUIRED_CELLS) - {i["cell"] for i in items})
        return json.dumps({"received": len(items), "cells_not_sent": missing})

    def validate(self, items: list[dict]) -> list[dict]:
        """Plain code, not AI: downgrade anything the agent can't back up with a source from this run."""
        checked, seen = [], set()
        for item in items:
            cell = item.get("cell")
            if cell not in REQUIRED_CELLS or cell in seen:  # only agreed input cells, once each
                continue
            seen.add(cell)
            fixed = {"cell": cell, "value": item.get("value", ""), "status": item.get("status", "check"),
                     "source_url": item.get("source_url", ""), "note": item.get("note", "")}
            has_value = str(fixed["value"]).strip() != ""
            if fixed["status"] not in STATUSES:
                fixed = {**fixed, "status": "check", "note": f"[validator] unknown status. {fixed['note']}"}
            if isinstance(fixed["value"], str) and fixed["value"].strip().startswith(FORMULA_START):
                fixed = {**fixed, "status": "check",
                         "note": f"[validator] value looks like a formula; written as plain text. {fixed['note']}"}
            if has_value and fixed["source_url"] not in self.seen_sources:
                fixed = {**fixed, "status": "check", "note": f"[validator] source not from this run. {fixed['note']}"}
            if not has_value and fixed["status"] != "missing":
                fixed = {**fixed, "status": "missing"}
            checked.append(fixed)
        skipped = [{"cell": c, "value": "", "status": "missing", "source_url": "",
                    "note": "[validator] the agent did not fill this cell"} for c in REQUIRED_CELLS if c not in seen]
        return checked + skipped


def make_tools(run: Run) -> list:
    """The tools the agent can call, bound to one run."""

    @beta_tool
    def kc_assessor_record(parcel_number: str) -> str:
        """Official King County Assessor record: address, jurisdiction, present use, lot sq ft,
        zoning, buildings (floor areas, basement, garage), year built/renovated, permits.
        Includes `suggested_cells` already mapped to template cells by code. Use this first.

        Args:
            parcel_number: 10-digit King County parcel number (APN), with or without dash.
        """
        return run.call("kc_assessor_record", lookups.kc_assessor, parcel_number)

    @beta_tool
    def kc_parcel_map(parcel_number: str) -> str:
        """King County parcel map, measured by code: lot area, each side of the lot and what lies across
        it (neighbour, alley, street), corner lot yes/no, and `frontage.width_ft` = Pivotal's lot width
        (narrow end; corner lot: the narrower end). Also the lot's center lat/lon.

        Args:
            parcel_number: 10-digit King County parcel number.
        """
        return run.call("kc_parcel_map", lookups.kc_parcel_map, parcel_number)

    @beta_tool
    def permit_history(parcel_number: str) -> str:
        """Every permit on record for the lot: the county assessor's permit list, plus (in Seattle)
        the city's building, electrical and trade permits found by street address, newest first,
        each with its own link. Use it for B51 Recent System Update.

        Args:
            parcel_number: 10-digit King County parcel number.
        """
        return run.call("permit_history", lookups.permit_history, parcel_number)

    @beta_tool
    def seattle_map_layers(parcel_number: str) -> str:
        """City of Seattle map layers checked across the WHOLE lot (a grid of points, not just the
        center): zoning, MHA zoning and fee area, frequent transit (1/4-mile walkshed of a frequent
        stop), and environmentally critical areas (steep slope, slides, wetlands, riparian, flood,
        liquefaction). Each hit has `share_of_lot` (0-1). `narrow_strips` says, for each 2-30 ft strip
        beside the lot, whether it is legal alley/street right-of-way and whether it is paved. Only
        meaningful inside Seattle.

        Args:
            parcel_number: 10-digit King County parcel number.
        """
        return run.call("seattle_map_layers", lookups.seattle_layers, parcel_number)

    @beta_tool
    def bellevue_map_layers(parcel_number: str) -> str:
        """City of Bellevue map layers checked across the WHOLE lot: zoning (current code), critical
        areas (steep slope, liquefaction, flood, coal mine; streams within 100 ft), and the distance
        from the lot to the nearest frequent-transit stop. Only meaningful inside Bellevue.

        Args:
            parcel_number: 10-digit King County parcel number.
        """
        return run.call("bellevue_map_layers", lookups.bellevue_layers, parcel_number)

    @beta_tool
    def submit_inputs(items: list[CellInput] | str) -> str:
        """Hand in the final values for the Inputs tab. Call exactly once, at the end.

        Args:
            items: One entry per cell. status: record = copied from an official record;
                measured = calculated from map data; check = filled but a person should look;
                missing = no tool returned it (value empty). source_url must be copied exactly
                from a tool result. note: short reason, required for check/missing.
        """
        return run.submit(items)

    return [kc_assessor_record, kc_parcel_map, permit_history, seattle_map_layers, bellevue_map_layers,
            submit_inputs]


MAX_RULES_CHARS = 30_000


def default_rules() -> str:
    return (HERE / "rules.md").read_text()


def build_system_prompt(rules: str | None = None) -> str:
    """Instructions + Pivotal's rules. `rules` comes from the sheet's Rules tab; else the built-in file."""
    return (HERE / "prompt.md").read_text() + "\n\n" + (rules if rules and rules.strip() else default_rules())


def run_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return round((input_tokens * PRICE_PER_MTOK["input"] + output_tokens * PRICE_PER_MTOK["output"]) / 1e6, 3)


def analyze(apn: str, log: Log = print, client: anthropic.Anthropic | None = None,
            rules: str | None = None) -> dict:
    """Run the agent on one King County APN with Pivotal's rules (from the sheet, or the built-in file).

    Raises InvalidParcelNumber for a bad APN and AgentFailed if the agent hands in nothing.
    """
    pin = normalize_kc_parcel_number(apn)
    if rules and len(rules) > MAX_RULES_CHARS:
        raise ValueError(f"The rules are {len(rules):,} characters; the limit is {MAX_RULES_CHARS:,}.")
    run = Run(log=log)
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    started = time.monotonic()
    tokens = {"input": 0, "output": 0}
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=build_system_prompt(rules),
        tools=make_tools(run),
        messages=[{"role": "user", "content": f"Analyze King County APN {pin}."}],
        max_iterations=MAX_TOOL_ROUNDS,
    )
    for turn, message in enumerate(runner, start=1):
        tokens = {"input": tokens["input"] + message.usage.input_tokens,
                  "output": tokens["output"] + message.usage.output_tokens}
        log(f"— turn {turn} (stop: {message.stop_reason})")
        for block in message.content:
            if block.type == "tool_use":
                log(f"  agent calls → {block.name}")
    seconds = round(time.monotonic() - started)
    if not run.submitted:
        raise AgentFailed(f"the agent stopped without handing in its answers after {seconds}s")
    return {
        "apn": pin,
        "parcel_viewer_url": lookups.KC_PARCEL_VIEWER.format(pin=pin),
        "cells": run.validate(run.submitted),
        "seconds": seconds,
        "tokens": tokens,
        "cost_usd": run_cost_usd(tokens["input"], tokens["output"]),
        "model": MODEL,
        "rules_source": "Rules tab" if rules and rules.strip() else "built-in rules",
    }

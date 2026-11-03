"""Claude app plug-in (MCP server): the agent's tools, for asking questions in a chat.

An analyst adds this as a custom connector in the Claude app, then asks things like
"analyze 1256 111th Ave NE, Bellevue" or "why is the alley No on 9331800500?".

Two kinds of tools:
- look-ups (read-only, free apart from the chat itself): the same county and city data the agent uses
- start_analysis / analysis_result: the full checked analysis, the same as the sheet's button

Access: a secret key, PIVOTAL_MCP_TOKEN, sent as "Authorization: Bearer <key>" or as ?key=<key>
in the connector URL (the Claude app's custom connector form only takes a URL).
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

import agent  # noqa: E402
import jobs  # noqa: E402
import lookups  # noqa: E402
from pivotal_engine.errors import EngineError  # noqa: E402

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
INSTRUCTIONS = (
    "Pivotal Real Estate property research for King County, WA. For a full Inputs-tab analysis use "
    "start_analysis, then call analysis_result every ~15 seconds until it is done (about 1-2 minutes); "
    "show cells marked check or missing first, with their notes. To answer questions about one value, "
    "use the look-up tools and pivotal_rules, and always give the source link. Never invent values."
)


def _safe(fn: Callable, *args: str) -> dict:
    """Run a look-up; turn failures into a message Claude can relay instead of a crash."""
    try:
        return fn(*args)
    except EngineError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # the county or city site is down, or changed
        return {"error": f"{type(exc).__name__}: the data source did not answer. Try again later."}


def create_mcp_app(store: jobs.JobStore):
    server = MCPServer(name="pivotal-property", title="Pivotal property research", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def find_parcel(address: str) -> dict:
        """Find the King County parcel number (APN) for a street address, e.g. '1256 111th Ave NE, Bellevue'."""
        return _safe(lookups.find_parcel, address)

    @server.tool(annotations=READ_ONLY)
    def property_record(parcel_number: str) -> dict:
        """Official King County Assessor record: address, jurisdiction, lot size, zoning, buildings
        (floor areas, basement, garage), year built/renovated, permits, plus template-ready cells."""
        return _safe(lookups.kc_assessor, parcel_number)

    @server.tool(annotations=READ_ONLY)
    def lot_measurements(parcel_number: str) -> dict:
        """Lot shape from the county parcel map, measured by code: each side and what lies across it
        (neighbour, alley, street), corner lot, and Pivotal's lot width with how it was chosen."""
        return _safe(lookups.kc_parcel_map, parcel_number)

    @server.tool(annotations=READ_ONLY)
    def permit_history(parcel_number: str) -> dict:
        """Permits on record: the county list, plus Seattle building/electrical/trade permits in Seattle."""
        return _safe(lookups.permit_history, parcel_number)

    @server.tool(annotations=READ_ONLY)
    def seattle_map_layers(parcel_number: str) -> dict:
        """Seattle zoning, MHA, frequent transit, critical areas (whole-lot check) and alley/strip details."""
        return _safe(lookups.seattle_layers, parcel_number)

    @server.tool(annotations=READ_ONLY)
    def bellevue_map_layers(parcel_number: str) -> dict:
        """Bellevue zoning, critical areas, streams and the distance to the nearest frequent-transit stop."""
        return _safe(lookups.bellevue_layers, parcel_number)

    @server.tool(annotations=READ_ONLY)
    def pivotal_rules() -> str:
        """Pivotal's rules for each Inputs-tab cell (lot width, alley, zoning, permits, ...)."""
        return agent.default_rules()

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, idempotent_hint=False))
    def start_analysis(parcel_number_or_address: str) -> dict:
        """Start the full checked analysis of one property (about 1-2 minutes, costs about $0.20).
        Returns a job_id; then call analysis_result."""
        text = parcel_number_or_address.strip()
        looks_like_apn = text.replace("-", "").replace(" ", "").isdigit()
        try:
            return jobs.start_analysis(store, apn=text if looks_like_apn else None,
                                       address=None if looks_like_apn else text)
        except (jobs.BadRequest, jobs.Busy) as exc:
            return {"error": str(exc)}

    @server.tool(annotations=READ_ONLY)
    def analysis_result(job_id: str) -> dict:
        """Status of an analysis started with start_analysis. When done, `result.cells` has each Inputs
        cell with value, status (record/measured/check/missing), note and source link."""
        found = store.get(job_id)
        if found is None:
            return {"error": "No such job (finished jobs are kept for 6 hours)."}
        return {k: found[k] for k in ("job_id", "apn", "status", "result", "error")}

    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # Host-header checks protect servers on a laptop; this one is public and key-protected.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


class KeyGuard:
    """ASGI wrapper: lets a request through only with the right key (header or ?key=)."""

    def __init__(self, app: Any, key_ok: Callable[[str | None], bool]) -> None:
        self.app = app
        self.key_ok = key_ok

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or self.key_ok(self._key(scope)):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "Missing or wrong key."}).encode()
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _key(scope: dict) -> str | None:
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("key")
        return values[0] if values else None

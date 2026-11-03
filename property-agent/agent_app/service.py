"""Web service on Railway: the sheet's Analyze button and the Claude app plug-in.

Sheet button (header X-Pivotal-Token = PIVOTAL_SERVICE_TOKEN):
    POST /analyze   {"apn": "9331800500"} or {"address": "...", "rules": "<Rules tab text>"} -> 202 {"job_id"}
    GET  /jobs/{id} -> {"status": "running" | "done" | "failed", "result": {...}, "error": ...}
    GET  /rules     -> the built-in rules (to fill a new Rules tab)
Claude app plug-in (MCP), only when PIVOTAL_MCP_TOKEN is set:
    /mcp            see mcp_server.py
Open:
    GET  /health    -> {"ok": true}

Settings (environment variables): ANTHROPIC_API_KEY, PIVOTAL_SERVICE_TOKEN; optional
PIVOTAL_MCP_TOKEN (turns on /mcp) and MAX_RUNNING_JOBS (default 3).
"""

import contextlib
import hmac
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import agent  # noqa: E402
import jobs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REQUIRED_SETTINGS = ("ANTHROPIC_API_KEY", "PIVOTAL_SERVICE_TOKEN")


class AnalyzeRequest(BaseModel):
    apn: str | None = Field(default=None, max_length=20, description="King County parcel number")
    address: str | None = Field(default=None, max_length=200, description="Street address, if no APN")
    rules: str | None = Field(default=None, max_length=agent.MAX_RULES_CHARS, description="Rules tab text")


def missing_settings() -> list[str]:
    return [name for name in REQUIRED_SETTINGS if not os.environ.get(name)]


def token_matches(given: str | None, setting: str) -> bool:
    expected = os.environ.get(setting, "")
    return bool(expected and given) and hmac.compare_digest(given.encode(), expected.encode())


def check_token(given: str | None) -> None:
    if not token_matches(given, "PIVOTAL_SERVICE_TOKEN"):
        raise HTTPException(status_code=401, detail="Missing or wrong service token.")


def create_app(store: jobs.JobStore | None = None) -> FastAPI:
    missing = missing_settings()
    if missing:
        raise RuntimeError(f"Set these environment variables before starting: {', '.join(missing)}")
    job_store = store or jobs.JobStore(max_running=int(os.environ.get("MAX_RUNNING_JOBS", "3")))
    mcp_app = None
    if os.environ.get("PIVOTAL_MCP_TOKEN"):
        import mcp_server  # only loaded when the plug-in is turned on
        mcp_app = mcp_server.create_mcp_app(job_store)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        if mcp_app is None:
            yield
        else:
            async with mcp_app.router.lifespan_context(mcp_app):  # the MCP session manager
                yield

    app = FastAPI(title="Pivotal property agent", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/analyze", status_code=202)
    def analyze(body: AnalyzeRequest, x_pivotal_token: str | None = Header(default=None)) -> dict:
        check_token(x_pivotal_token)
        try:
            return jobs.start_analysis(job_store, apn=body.apn, address=body.address, rules=body.rules)
        except jobs.BadRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except jobs.Busy as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}")
    def job(job_id: str, x_pivotal_token: str | None = Header(default=None)) -> dict:
        check_token(x_pivotal_token)
        found = job_store.get(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such job (finished jobs are kept for 6 hours).")
        return found

    @app.get("/rules")
    def rules(x_pivotal_token: str | None = Header(default=None)) -> dict:
        check_token(x_pivotal_token)
        return {"rules": agent.default_rules()}

    if mcp_app is not None:
        app.mount("/", mcp_server.KeyGuard(mcp_app, lambda key: token_matches(key, "PIVOTAL_MCP_TOKEN")))
    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn --factory."""
    return create_app()

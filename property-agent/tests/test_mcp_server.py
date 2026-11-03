"""Claude app plug-in: key check and tools over real MCP requests. Data sources and the agent faked."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import agent  # noqa: E402
import jobs  # noqa: E402
import service  # noqa: E402

KEY = "mcp-key"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    monkeypatch.setenv("PIVOTAL_SERVICE_TOKEN", "sheet-token")
    monkeypatch.setenv("PIVOTAL_MCP_TOKEN", KEY)
    monkeypatch.setattr(jobs.lookups, "find_parcel",
                        lambda a: {"parcel_number": "4348800050", "candidates": [], "note": ""})
    monkeypatch.setattr(agent, "analyze", lambda apn, log, rules=None: {"apn": apn, "cells": []})
    with TestClient(service.create_app()) as test_client:  # `with` runs the MCP session manager
        yield test_client


def rpc(client, method, params=None, key=KEY):
    url = "/mcp" + (f"?key={key}" if key else "")
    return client.post(url, headers=MCP_HEADERS,
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def call(client, name, arguments):
    resp = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


def test_wrong_or_missing_key_is_rejected(client):
    assert rpc(client, "tools/list", key=None).status_code == 401
    assert rpc(client, "tools/list", key="nope").status_code == 401


def test_bearer_header_also_works(client):
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {KEY}"}
    resp = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 200, resp.text


def test_lists_the_research_tools(client):
    resp = rpc(client, "tools/list")
    assert resp.status_code == 200, resp.text
    names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert {"find_parcel", "property_record", "lot_measurements", "permit_history", "pivotal_rules",
            "start_analysis", "analysis_result"} <= names


def test_find_parcel_tool(client):
    assert "4348800050" in str(call(client, "find_parcel", {"address": "1256 111th Ave NE"}))


def test_full_analysis_by_address(client):
    started = call(client, "start_analysis", {"parcel_number_or_address": "1256 111th Ave NE, Bellevue"})
    assert "4348800050" in str(started)


def test_unknown_job(client):
    assert "No such job" in str(call(client, "analysis_result", {"job_id": "nope"}))


def test_sheet_routes_still_need_their_own_token(client):
    resp = client.post("/analyze", json={"apn": "9331800500"}, headers={"X-Pivotal-Token": KEY})
    assert resp.status_code == 401

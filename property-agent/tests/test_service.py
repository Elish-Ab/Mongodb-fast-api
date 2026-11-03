"""Web service for the Analyze button: auth, validation, job flow. The agent itself is faked."""

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import agent  # noqa: E402
import jobs  # noqa: E402
import service  # noqa: E402

TOKEN = "test-token"
AUTH = {"X-Pivotal-Token": TOKEN}
RESULT = {"apn": "9331800500", "cells": [], "seconds": 1, "cost_usd": 0.2}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    monkeypatch.setenv("PIVOTAL_SERVICE_TOKEN", TOKEN)
    monkeypatch.delenv("PIVOTAL_MCP_TOKEN", raising=False)
    monkeypatch.setattr(agent, "analyze", lambda apn, log, rules=None: {**RESULT, "apn": apn, "rules": rules})
    return TestClient(service.create_app())


def wait_for(client, job_id):
    for _ in range(50):
        job = client.get(f"/jobs/{job_id}", headers=AUTH).json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_refuses_to_start_without_settings(monkeypatch):
    monkeypatch.delenv("PIVOTAL_SERVICE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="PIVOTAL_SERVICE_TOKEN"):
        service.create_app()


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"ok": True}


def test_wrong_or_missing_token_is_rejected(client):
    assert client.post("/analyze", json={"apn": "9331800500"}).status_code == 401
    assert client.post("/analyze", json={"apn": "9331800500"}, headers={"X-Pivotal-Token": "nope"}).status_code == 401
    assert client.get("/jobs/abc", headers={"X-Pivotal-Token": "nope"}).status_code == 401


def test_bad_apn_is_rejected_before_any_ai_runs(client):
    resp = client.post("/analyze", json={"apn": "12345678901234"}, headers=AUTH)
    assert resp.status_code == 400 and "14" in resp.json()["detail"]


def test_analyze_then_poll_until_done(client):
    resp = client.post("/analyze", json={"apn": "933180-0500"}, headers=AUTH)
    assert resp.status_code == 202 and resp.json()["apn"] == "9331800500"
    job = wait_for(client, resp.json()["job_id"])
    assert job["status"] == "done" and job["result"]["apn"] == "9331800500"


def test_agent_failure_becomes_a_readable_error(client, monkeypatch):
    def fail(apn, log, rules=None):
        raise agent.AgentFailed("the agent stopped without handing in its answers")
    monkeypatch.setattr(agent, "analyze", fail)
    job = wait_for(client, client.post("/analyze", json={"apn": "9331800500"}, headers=AUTH).json()["job_id"])
    assert job["status"] == "failed" and "handing in" in job["error"]


def test_unexpected_crash_does_not_leak_details(client, monkeypatch):
    def crash(apn, log, rules=None):
        raise KeyError("secret internal detail")
    monkeypatch.setattr(agent, "analyze", crash)
    job = wait_for(client, client.post("/analyze", json={"apn": "9331800500"}, headers=AUTH).json()["job_id"])
    assert job["status"] == "failed" and "secret" not in job["error"]


def test_unknown_job(client):
    assert client.get("/jobs/does-not-exist", headers=AUTH).status_code == 404


def test_too_many_running_jobs():
    store = jobs.JobStore(max_running=1)
    assert store.start("9331800500") is not None
    assert store.start("8146100590") is None


def test_a_stuck_job_times_out_and_frees_its_slot(monkeypatch):
    store = jobs.JobStore(max_running=1)
    stuck = store.start("9331800500")
    real_time = time.time
    monkeypatch.setattr(jobs.time, "time", lambda: real_time() + jobs.JOB_TIMEOUT_S + 1)
    assert store.get(stuck)["status"] == "failed"
    assert store.start("8146100590") is not None
    store.finish(stuck, result={"late": True})  # a late answer doesn't revive it
    assert store.get(stuck)["status"] == "failed"


def test_address_is_turned_into_a_parcel_number(client, monkeypatch):
    monkeypatch.setattr(jobs.lookups, "find_parcel",
                        lambda a: {"parcel_number": "4348800050", "candidates": [], "note": ""})
    resp = client.post("/analyze", json={"address": "1256 111th Ave NE, Bellevue"}, headers=AUTH)
    assert resp.status_code == 202 and resp.json()["apn"] == "4348800050"


def test_ambiguous_address_asks_for_the_parcel_number(client, monkeypatch):
    two = [{"parcel_number": "1111111111", "address": "100 MAIN ST, Seattle"},
           {"parcel_number": "2222222222", "address": "100 MAIN ST, Kent"}]
    monkeypatch.setattr(jobs.lookups, "find_parcel", lambda a: {"parcel_number": None, "candidates": two})
    resp = client.post("/analyze", json={"address": "100 Main St"}, headers=AUTH)
    assert resp.status_code == 400 and "1111111111" in resp.json()["detail"]


def test_nothing_to_analyze(client):
    assert client.post("/analyze", json={}, headers=AUTH).status_code == 400


def test_rules_from_the_sheet_reach_the_agent(client):
    resp = client.post("/analyze", json={"apn": "9331800500", "rules": "Width: round down."}, headers=AUTH)
    job = wait_for(client, resp.json()["job_id"])
    assert job["result"]["rules"] == "Width: round down."


def test_too_long_rules_are_rejected(client):
    resp = client.post("/analyze", json={"apn": "9331800500", "rules": "x" * (agent.MAX_RULES_CHARS + 1)},
                       headers=AUTH)
    assert resp.status_code == 422


def test_default_rules_for_a_new_rules_tab(client):
    assert client.get("/rules").status_code == 401
    assert "Lot width" in client.get("/rules", headers=AUTH).json()["rules"]


def test_plugin_is_off_without_its_own_key(client):
    assert client.post("/mcp", json={}).status_code == 404

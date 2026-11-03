"""Command line: missing key, success writes a result file, failure leaves it alone. Agent faked."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import agent  # noqa: E402
import run_agent  # noqa: E402

RESULT = {"apn": "9331800500", "seconds": 1, "cost_usd": 0.2, "tokens": {"input": 10, "output": 5},
          "cells": [{"cell": "B3", "value": "3302 S ORCAS ST", "status": "record", "note": ""},
                    {"cell": "B7", "value": "", "status": "missing", "note": "no map"}]}


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(run_agent, "HERE", tmp_path)
    monkeypatch.setattr(run_agent, "load_env_file", lambda path: None)
    return tmp_path


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run_agent.py", *args])
    return run_agent.main()


def test_needs_an_api_key(cli, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run(monkeypatch, "9331800500") == 2


def test_success_saves_the_result(cli, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    monkeypatch.setattr(agent, "analyze", lambda apn: RESULT)
    assert run(monkeypatch, "9331800500") == 0
    assert json.loads((cli / "result_9331800500.json").read_text())["apn"] == "9331800500"
    assert "🟥 B7" in capsys.readouterr().out


def test_failure_leaves_no_file(cli, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")

    def fail(apn):
        raise agent.AgentFailed("stopped")
    monkeypatch.setattr(agent, "analyze", fail)
    assert run(monkeypatch, "9331800500") == 1
    assert not list(cli.glob("result_*.json"))


def test_tools_only_needs_no_key(cli, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for name in ("kc_assessor", "kc_parcel_map", "permit_history"):
        monkeypatch.setattr(run_agent.lookups, name, lambda apn, n=name: {"tool": n, "source_url": "https://x"})
    assert run(monkeypatch, "9331800500", "--tools-only") == 0
    assert "permit_history" in capsys.readouterr().out


def test_env_file_is_read_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nPIVOTAL_X='from file'\nPIVOTAL_Y=file\nnot a setting\n")
    monkeypatch.delenv("PIVOTAL_X", raising=False)
    monkeypatch.setenv("PIVOTAL_Y", "already set")
    run_agent.load_env_file(env)
    import os
    assert os.environ["PIVOTAL_X"] == "from file" and os.environ["PIVOTAL_Y"] == "already set"

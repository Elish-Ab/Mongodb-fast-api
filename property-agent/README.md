# Pivotal property agent

This fills the **Inputs** tab of Pivotal's Property Analysis sheet from a King County parcel number or street address. It uses only official county and city data, and every value comes with its source link. Uncertain or missing values are flagged red with a note.

You can use it two ways:

| | How | Best for |
|---|---|---|
| **Analyze button** in the sheet | Put the APN in B4 (or an address in B3) and click Analyze. About 1–2 minutes. | Daily analyses |
| **Claude app plug-in** (MCP) | Ask Claude, e.g. "analyze 1256 111th Ave NE, Bellevue" or "why is the alley No on 9331800500?" | Questions and checking a value |

Both use the same service on Railway, the same tools and the same rules.

## How a run works

```
Sheet button / Claude app
        │  APN or address (+ Rules tab text)
        ▼
Railway service ── finds the parcel ── starts a job
        │
        ▼
Claude agent ── county assessor record, county parcel map (measured by code),
        │       permits, Seattle or Bellevue map layers
        │       applies Pivotal's rules (Rules tab, or agent_app/rules.md)
        ▼
Validator (plain code) ── only trusts sources returned in this run, only the agreed cells
        ▼
21 cells with value, status (record / measured / check / missing), note, source link
```

## Changing things

| What | Where | Redeploy? |
|---|---|---|
| A rule (for example how width is rounded, what counts as an alley) | The sheet's **Rules** tab, in plain English | No |
| The built-in default rules | `agent_app/rules.md` | Yes (automatic on push to `main`) |
| The agent's general instructions | `agent_app/prompt.md` | Yes |
| A data source, or a new city | `agent_app/lookups.py` (tests in `tests/`) | Yes |

Code changes can be made with any AI editor (Antigravity, Claude Code, Cursor). Run the tests before pushing:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

## Setup

- **Railway and the sheet:** see [apps_script/README.md](apps_script/README.md).
- **Run one property from the command line** (needs `ANTHROPIC_API_KEY` in `.env`):
  `.venv/bin/python agent_app/run_agent.py 9331800500`
  Add `--tools-only` to see the raw data with no AI.

## Layout

```
agent_app/
  agent.py        the agent: tools, Claude loop, validator
  rules.md        Pivotal's default rules (plain English)
  prompt.md       the agent's instructions
  lookups.py      county/city data: assessor, parcel map, permits, Seattle/Bellevue layers, address search
  lot_geometry.py lot sides, width, corner/alley, whole-lot sampling
  jobs.py         background analysis jobs
  service.py      web service: /analyze, /jobs, /rules, /health (+ /mcp)
  mcp_server.py   Claude app plug-in
  run_agent.py    command line
src/pivotal_engine/  King County assessor page reader
apps_script/Code.gs  the Analyze button
tests/               offline tests (no network, no AI)
```

## Coverage today

- **King County only.** Map layers exist for Seattle and Bellevue; for other cities, the map-based cells come back "missing".
- **Not built yet:** Snohomish County, valuation and comps, real slope (no elevation data), city permits outside Seattle.

"""Run the property agent from the command line on one King County APN.

    .venv/bin/python agent_app/run_agent.py 9331800500

    # no API key? run only the lookup tools (no AI) to see what the agent would get:
    .venv/bin/python agent_app/run_agent.py 9331800500 --tools-only

The API key is read from ANTHROPIC_API_KEY or from the git-ignored .env file.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent  # noqa: E402
import lookups  # noqa: E402
from pivotal_engine.errors import EngineError  # noqa: E402

HERE = Path(__file__).resolve().parent
FLAG = {"record": "  ", "measured": "  ", "check": "🟥", "missing": "🟥"}


def print_result(result: dict) -> None:
    print("\n================ RESULT ================")
    for item in result["cells"]:
        print(f"{FLAG.get(item['status'], '? ')} {item['cell']:<5} {str(item['value'])[:45]:<45} "
              f"[{item['status']}] {item.get('note', '')[:70]}")
    print(f"\n{len(result['cells'])} cells · {result['seconds']}s · tokens in {result['tokens']['input']:,} / "
          f"out {result['tokens']['output']:,} · ${result['cost_usd']}")


def tools_only(apn: str) -> None:
    run = agent.Run()
    for fn in (lookups.kc_assessor, lookups.kc_parcel_map, lookups.permit_history):
        print(json.dumps(json.loads(run.call(fn.__name__, fn, apn)), indent=2)[:4000])


def load_env_file(path: Path) -> None:
    """Read KEY=value lines from a private .env file (git-ignored) into the environment."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env_file(HERE.parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("apn")
    parser.add_argument("--tools-only", action="store_true", help="run lookups only, no AI")
    args = parser.parse_args()
    if args.tools_only:
        tools_only(args.apn)
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("Set ANTHROPIC_API_KEY first, or use --tools-only to run the lookups without AI.\n")
        return 2
    try:
        result = agent.analyze(args.apn)
    except (EngineError, agent.AgentFailed) as exc:
        print(f"\n✗ FAILED: {exc}. Previous result file left unchanged.")
        return 1
    print_result(result)
    out = HERE / f"result_{result['apn']}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

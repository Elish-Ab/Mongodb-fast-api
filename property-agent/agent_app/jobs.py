"""Analysis jobs, shared by the sheet button (service.py) and the Claude app plug-in (mcp_server.py).

An analysis takes about a minute, so it runs in a background thread: the caller starts a job,
then checks back. Jobs live in memory; one Railway instance is plenty for 20-100 a month.
"""

import logging
import threading
import time
import uuid

import agent
import lookups
from pivotal_engine.errors import EngineError, InvalidParcelNumber
from pivotal_engine.sources.kc_parcel_number import normalize_kc_parcel_number

log = logging.getLogger("pivotal.jobs")

JOB_TTL_S = 6 * 3600          # forget finished jobs after 6 hours
JOB_TIMEOUT_S = 10 * 60       # a job still running after this is treated as failed
MAX_LOG_LINES = 200


class BadRequest(ValueError):
    """The caller's input can't be analyzed. The message is safe to show to the user."""


class Busy(RuntimeError):
    """Too many analyses are running."""


class JobStore:
    def __init__(self, max_running: int) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.max_running = max_running

    def start(self, apn: str) -> str | None:
        """Create a job, or return None when too many are already running."""
        with self._lock:
            self._forget_old()
            self._expire_stuck()
            if sum(j["status"] == "running" for j in self._jobs.values()) >= self.max_running:
                return None
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {"job_id": job_id, "apn": apn, "status": "running", "started": time.time(),
                                  "log": [], "result": None, "error": None}
            return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            self._expire_stuck()
            job = self._jobs.get(job_id)
            return None if job is None else {**job, "log": list(job["log"][-20:])}

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._jobs[job_id] = {**job, "log": [*job["log"], line][-MAX_LOG_LINES:]}

    def finish(self, job_id: str, *, result: dict | None = None, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "running":  # already timed out or forgotten
                return
            self._jobs[job_id] = {**job, "status": "failed" if error else "done", "result": result,
                                  "error": error, "finished": time.time()}

    def _expire_stuck(self) -> None:
        cutoff = time.time() - JOB_TIMEOUT_S
        self._jobs = {k: ({**j, "status": "failed", "finished": time.time(),
                           "error": "Timed out after 10 minutes. Try again."}
                          if j["status"] == "running" and j["started"] < cutoff else j)
                      for k, j in self._jobs.items()}

    def _forget_old(self) -> None:
        cutoff = time.time() - JOB_TTL_S
        self._jobs = {k: j for k, j in self._jobs.items() if j.get("finished", time.time()) > cutoff}


def resolve_parcel(apn: str | None, address: str | None) -> str:
    """A 10-digit parcel number from either an APN or a street address. Raises BadRequest."""
    if apn and apn.strip():
        try:
            return normalize_kc_parcel_number(apn)
        except InvalidParcelNumber as exc:
            raise BadRequest(str(exc)) from exc
    if not address or not address.strip():
        raise BadRequest("Give a King County parcel number or a street address.")
    found = lookups.find_parcel(address)
    if found["parcel_number"]:
        return found["parcel_number"]
    if found["candidates"]:
        choices = "; ".join(f"{c['parcel_number']} ({c['address']})" for c in found["candidates"])
        raise BadRequest(f"Several parcels match '{address}': {choices}. Use the parcel number.")
    raise BadRequest(f"No King County parcel found for '{address}'. Check the address or use the parcel number.")


def start_analysis(store: JobStore, apn: str | None = None, address: str | None = None,
                   rules: str | None = None) -> dict:
    """Start an analysis in the background. Raises BadRequest or Busy."""
    if rules and len(rules) > agent.MAX_RULES_CHARS:
        raise BadRequest(f"The rules are {len(rules):,} characters; the limit is {agent.MAX_RULES_CHARS:,}.")
    pin = resolve_parcel(apn, address)
    job_id = store.start(pin)
    if job_id is None:
        raise Busy("Too many analyses running. Try again in a minute.")
    threading.Thread(target=run_job, args=(store, job_id, pin, rules), daemon=True).start()
    return {"job_id": job_id, "apn": pin}


def run_job(store: JobStore, job_id: str, apn: str, rules: str | None = None) -> None:
    def job_log(line: str) -> None:
        store.append_log(job_id, line)
        log.info("[%s] %s", job_id[:8], line)

    try:
        store.finish(job_id, result=agent.analyze(apn, log=job_log, rules=rules))
    except (EngineError, agent.AgentFailed, ValueError) as exc:
        store.finish(job_id, error=str(exc))
    except Exception as exc:  # anything unexpected: tell the caller, keep details in the server log
        log.exception("[%s] analysis of %s crashed", job_id[:8], apn)
        store.finish(job_id, error=f"Unexpected error ({type(exc).__name__}). Try again; if it repeats, "
                                   "check the service log.")

"""Fetch King County eRealProperty pages with httpx, politely.

* Identifies itself honestly in the User-Agent (no browser disguise).
* Waits at least `min_interval_s` between requests.
* Retries server errors and network failures a few times, then raises SourceUnavailable.
"""

import logging
import time
from typing import Callable, Optional, TypeVar

import httpx

from pivotal_engine.errors import PageFormatChanged, SourceUnavailable
from pivotal_engine.sources.kc_assessor_models import KCAssessorRecord, KCDashboardSummary
from pivotal_engine.sources.kc_assessor_parser import (
    DASHBOARD_URL,
    DETAIL_URL,
    parse_dashboard_page,
    parse_detail_page,
)
from pivotal_engine.sources.kc_parcel_number import normalize_kc_parcel_number

logger = logging.getLogger(__name__)

USER_AGENT = "PivotalPropertyEngine/0.1 (Pivotal Real Estate property research)"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MIN_INTERVAL_S = 1.0
DEFAULT_RETRIES = 2
RETRY_BACKOFF_S = 1.5

T = TypeVar("T")


class KCAssessorClient:
    def __init__(
        self,
        http: Optional[httpx.Client] = None,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        retries: int = DEFAULT_RETRIES,
        retry_backoff_s: float = RETRY_BACKOFF_S,
    ) -> None:
        self._http = http or httpx.Client(timeout=DEFAULT_TIMEOUT_S, follow_redirects=True)
        self._min_interval_s = min_interval_s
        self._retries = retries
        self._retry_backoff_s = retry_backoff_s
        self._last_request_at = 0.0

    def __enter__(self) -> "KCAssessorClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def fetch_detail(self, parcel_number: str) -> KCAssessorRecord:
        parcel = normalize_kc_parcel_number(parcel_number)
        return self._fetch(parcel, DETAIL_URL.format(parcel=parcel), parse_detail_page)

    def fetch_dashboard(self, parcel_number: str) -> KCDashboardSummary:
        parcel = normalize_kc_parcel_number(parcel_number)
        return self._fetch(parcel, DASHBOARD_URL.format(parcel=parcel), parse_dashboard_page)

    def _fetch(self, parcel: str, url: str, parse: Callable[[str], T]) -> T:
        result = parse(self._get_html(url))
        returned = getattr(result, "parcel_number", parcel)
        if returned != parcel:
            raise PageFormatChanged(
                f"Asked King County for parcel {parcel} but the page shows {returned}. Not using this page."
            )
        return result

    def _get_html(self, url: str) -> str:
        last_problem = "unknown error"
        for attempt in range(self._retries + 1):
            if attempt:
                time.sleep(self._retry_backoff_s * attempt)
            self._wait_turn()
            try:
                response = self._http.get(url, headers={"User-Agent": USER_AGENT})
            except httpx.HTTPError as exc:
                last_problem = f"network error: {exc}"
                logger.warning("King County request failed (%s), attempt %d: %s", url, attempt + 1, exc)
                continue
            if response.status_code < 500:
                if response.status_code == 429:
                    raise SourceUnavailable(
                        "King County is rate limiting requests (HTTP 429). Wait a few minutes, then try again."
                    )
                if response.status_code >= 400:
                    raise SourceUnavailable(f"King County returned HTTP {response.status_code} for {url}.")
                return response.text
            last_problem = f"HTTP {response.status_code}"
            logger.warning("King County returned %s for %s, attempt %d", response.status_code, url, attempt + 1)
        raise SourceUnavailable(
            f"Could not load the King County assessor page after {self._retries + 1} tries ({last_problem}). "
            "Try again later or open the page manually."
        )

    def _wait_turn(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

import re
import time
import logging
import random
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError
from serpapi import GoogleSearch

SERPAPI_KEY = "b4668d1c393882893582179b82712fa16730834cced7ef979f44a750e07dc7c1"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def extract_apn_from_text(text: str) -> str | None:
    patterns = [
        r"APN Number[:\s]*(\d{9,15})",
        r"Parcel Number[:\s]*(\d{9,15})",
        r"Parcel ID[:\s]*(\d{9,15})",
        r"Tax Parcel[:\s]*(\d{9,15})",
        r"Parcel (ID|Number)[:\s]*(\d{3}[-\s]?\d{3}[-\s]?\d{2,4})"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            apn = match.group(2) if match.lastindex == 2 else match.group(1)
            return re.sub(r"\D", "", apn)
    return None


def get_parcel_number_with_playwright(search_term: str, candidate_id: str) -> str | None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            query = urllib.parse.quote_plus(search_term)
            url = f"https://www.google.com/search?q={query}"
            logger.info(f"[Playwright] Searching: {url}")
            page.goto(url, timeout=30000)
            time.sleep(random.uniform(1, 2))

            # Extract text snippets
            snippets = page.locator("div:has-text('Parcel'), span:has-text('Parcel')")
            for i in range(snippets.count()):
                text = snippets.nth(i).inner_text().replace(",", "")
                apn = extract_apn_from_text(text)
                if apn:
                    logger.info(f"[Playwright] Found APN in snippet: {apn}")
                    return apn

        except TimeoutError:
            logger.warning(f"[Playwright] Timeout for candidate {candidate_id}")
        except Exception as e:
            logger.error(f"[Playwright] Error for {candidate_id}: {e}")
            Path(f"debug_google_{candidate_id}_error.html").write_text(page.content(), encoding="utf-8")
        finally:
            browser.close()
    return None


def get_parcel_number_with_serpapi(search_term: str, candidate_id: str) -> str | None:
    try:
        logger.info(f"[SerpAPI] Fallback: Searching for {search_term}")
        search = GoogleSearch({
            "q": search_term,
            "api_key": SERPAPI_KEY,
            "engine": "google",
            "num": 10
        })
        results = search.get_dict()
        for result in results.get("organic_results", []):
            snippet = result.get("snippet", "")
            apn = extract_apn_from_text(snippet)
            if apn:
                logger.info(f"[SerpAPI] Found APN: {apn}")
                return apn
    except Exception as e:
        logger.error(f"[SerpAPI] Error: {e}")
    return None


def get_parcel_number(search_term: str, candidate_id: str) -> str | None:
    apn = get_parcel_number_with_playwright(search_term, candidate_id)
    if apn:
        return apn
    logger.warning(f"[Playwright] No APN found, trying SerpAPI for {candidate_id}")
    return get_parcel_number_with_serpapi(search_term, candidate_id)


def scrape_batch(candidates: list[dict]):
    for i, candidate in enumerate(candidates):
        cid = candidate.get("id") or f"cand_{i}"
        address = candidate.get("address")
        if not address:
            continue
        apn = get_parcel_number(address, cid)
        print(f"{cid} | {address} → APN: {apn or 'Not found'}")


# Example usage
if __name__ == "__main__":
    test_candidates = [
        {"id": "test1", "address": "33668 Pereira Ct Fremont CA 94555 parcel number -site:zillow.com"},
        {"id": "test2", "address": "10754 14th Ave NE Seattle WA parcel number -site:zillow.com"}
    ]
    scrape_batch(test_candidates)

import os
import time
import re
import random
import logging
import urllib.parse
import shutil

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.chrome.service import Service

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--remote-debugging-port=9222")
    options.binary_location = "/opt/google/chrome-beta/chrome"

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ]
    options.add_argument(f"user-agent={random.choice(user_agents)}")

    driver_path = shutil.which("chromedriver")
    if not driver_path:
        raise RuntimeError("❌ chromedriver not found in PATH. Install it manually.")

    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def handle_cookies(driver):
    try:
        consent_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept')] | //div[text()='Accept all']"))
        )
        consent_button.click()
        time.sleep(1)
    except TimeoutException:
        pass

def extract_apn_from_text(text):
    patterns = [
        r"Parcel Number[:\s]*(\d{10})",
        r"Parcel ID[:\s]*(\d{10})",
        r"Tax Parcel[:\s]*(\d{10})",
        r"Parcel Number[:\s]*(\d{3}-\d{3}-\d{3})",
        r"Parcel ID[:\s]*(\d{3}-\d{3}-\d{3})"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).replace("-", "")
    return None

def get_parcel_number(search_term: str, candidate_id: str, driver=None, retries=3) -> str | None:
    attempt = 0
    while attempt < retries:
        try:
            if driver is None:
                driver = get_driver()
                own_driver = True
            else:
                own_driver = False

            query = urllib.parse.quote_plus(search_term)
            driver.get(f"https://www.google.com/search?q={query}")
            handle_cookies(driver)
            time.sleep(random.uniform(1, 2))

            # Step 1: Try .gov links
            try:
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='.gov']")
                for i in range(min(len(links), 3)):
                    link = driver.find_elements(By.CSS_SELECTOR, "a[href*='.gov']")[i]
                    url = link.get_attribute("href")
                    if "zillow.com" in url:
                        continue
                    try:
                        driver.get(url)
                        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                        page_source = driver.page_source
                        apn = extract_apn_from_text(page_source)
                        if apn:
                            logger.info(f"[Google] Found APN via .gov page on {url}: {apn}")
                            return apn
                        driver.back()
                        time.sleep(random.uniform(1, 2))
                    except Exception as e:
                        logger.warning(f"Failed to scrape {url}: {e}")
                        driver.back()
            except Exception as e:
                logger.warning(f"No .gov links found for {candidate_id}: {e}")

            # Step 2: Fallback to Google snippets
            snippets = driver.find_elements(By.XPATH, "//div[contains(@class, 'VwiC3b')]")
            for snippet in snippets:
                text = snippet.text.replace(",", "")
                apn = extract_apn_from_text(text)
                if apn:
                    logger.info(f"[Google Snippet] Found APN: {apn}")
                    return apn

            # Step 3: No APN found
            logger.warning(f"No APN found for candidate {candidate_id}")
            with open(f"debug_google_{candidate_id}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            return None

        except StaleElementReferenceException as e:
            logger.error(f"Stale element error for {candidate_id}: {e}")
        except TimeoutException as e:
            logger.error(f"Timeout during scraping {candidate_id}: {e}")
        except Exception as e:
            logger.error(f"Parcel lookup failed for {candidate_id}: {e}")
            if "captcha" in str(e).lower() or "recaptcha" in driver.page_source.lower():
                logger.error(f"CAPTCHA detected during lookup for {candidate_id}")
            with open(f"debug_google_{candidate_id}_error.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        finally:
            attempt += 1
            time.sleep(random.uniform(2, 4))

            if own_driver:
                driver.quit()

    return None

def scrape_batch(candidates: list[dict]):
    driver = get_driver()
    try:
        for i, candidate in enumerate(candidates):
            cid = candidate.get("id") or f"cand_{i}"
            address = candidate.get("address")
            if not address:
                continue
            apn = get_parcel_number(address, cid, driver=driver)
            print(f"{cid} | {address} → APN: {apn}")
            time.sleep(random.uniform(2, 4))  # Throttle between queries
    finally:
        driver.quit()

# Example usage
if __name__ == "__main__":
    test_candidates = [
        {"id": "test1", "address": "123 Main St, Seattle, WA parcel number -site:zillow.com"},
        {"id": "test2", "address": "456 Pine St, Seattle, WA parcel number -site:zillow.com"}
    ]
    scrape_batch(test_candidates)

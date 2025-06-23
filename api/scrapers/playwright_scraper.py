from playwright.sync_api import sync_playwright
from pymongo import MongoClient
from datetime import datetime
import logging
import time


def scrape_from_mongo_and_update_playwright(mongo_uri: str, db_name: str, collection_name: str, limit: int = None):
    logging.basicConfig(filename="scrape_errors.log", level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    client = MongoClient(mongo_uri)
    db = client[db_name]
    collection = db[collection_name]

    apns = [
        doc["apn"] for doc in collection.find({}, {"apn": 1}).limit(limit or 0)
        if "apn" in doc and str(doc["apn"]).isdigit() and len(str(doc["apn"])) == 10
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()

        for i, apn in enumerate(apns, start=1):
            result = {}
            start_time = time.time()
            try:
                url = f"https://blue.kingcounty.com/Assessor/eRealProperty/Dashboard.aspx?ParcelNbr={apn}"
                page.goto(url, timeout=30000)

                grade_sel = page.wait_for_selector('xpath=/html/body/form/table/tbody/tr/td[2]/table/tbody/tr[2]/td[1]/table/tbody/tr[4]/td/table/tbody/tr/td[1]/div/table/tbody/tr[5]/td[2]')
                result["Grade"] = grade_sel.inner_text().strip()

                # Click to details
                try:
                    page.click("text=Property Detail", timeout=5000)
                    page.wait_for_url("**/Detail.aspx", timeout=5000)
                    time.sleep(1)
                except:
                    pass

                # Sale data
                try:
                    rows = page.query_selector_all("#cphContent_GridViewSales tr")
                    if len(rows) > 1:
                        cells = rows[1].query_selector_all("td")
                        result["Sale Price"] = cells[3].inner_text().strip()
                        result["Sale Instrument"] = cells[6].inner_text().strip()
                        result["Sale Reason"] = cells[7].inner_text().strip()
                        result["Document Date"] = cells[2].inner_text().strip()
                except:
                    pass

                # Tax value
                try:
                    rows = page.query_selector_all("#cphContent_GridViewTaxRoll tr")
                    if len(rows) > 1:
                        cells = rows[1].query_selector_all("td")
                        result["Appraised Imps Value"] = cells[6].inner_text().strip()
                        result["Appraised Total Value"] = cells[7].inner_text().strip()
                except:
                    pass

                # Condition
                try:
                    cond = page.query_selector('xpath=//*[@id="cphContent_DetailsViewResBldg"]/tbody/tr[8]/td[2]')
                    result["Condition"] = cond.inner_text().strip() if cond else "Not Found"
                except:
                    result["Condition"] = "Not Found"

                # Year Built
                try:
                    rows = page.query_selector_all("#cphContent_DetailsViewResBldg tr")
                    for r in rows:
                        cells = r.query_selector_all("td")
                        if len(cells) == 2 and "Year Built" in cells[0].inner_text():
                            result["Year Built"] = cells[1].inner_text().strip()
                except:
                    pass

                # Zoning & Sewer/Septic
                try:
                    rows = page.query_selector_all("#cphContent_DetailsViewLandSystem tr")
                    for r in rows:
                        cells = r.query_selector_all("td")
                        if len(cells) == 2:
                            k = cells[0].inner_text().strip()
                            v = cells[1].inner_text().strip()
                            if "Zoning" in k:
                                result["Zoning"] = v
                            if "Sewer/Septic" in k:
                                result["Sewer/Septic"] = v
                except:
                    pass

                # Save
                collection.update_one(
                    {"apn": apn},
                    {"$set": {
                        "scraped_data": result,
                        "scraped_at": datetime.utcnow()
                    }}
                )
                logging.info(f"[✔️] {i}/{len(apns)} - Scraped {apn} in {round(time.time() - start_time, 2)}s")

            except Exception as e:
                logging.error(f"[✘] {apn} failed: {str(e)}")

        browser.close()
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import shutil

options = webdriver.ChromeOptions()
options.add_argument("--headless=new")

# ✅ Set binary location to Chrome Beta
options.binary_location = "/opt/google/chrome-beta/chrome"

# ✅ Use local chromedriver
driver_path = shutil.which("chromedriver")
if not driver_path:
    raise RuntimeError("❌ chromedriver not found in PATH.")

driver = webdriver.Chrome(service=Service(driver_path), options=options)
driver.get("https://www.google.com")
print(driver.title)
driver.quit()

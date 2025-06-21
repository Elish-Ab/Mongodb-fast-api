import streamlit as st
import requests
import pandas as pd
import os
import io
from dotenv import load_dotenv

# ---------- Load Config ----------
load_dotenv()
API_URL = os.getenv("API_URL", "https://store-data.up.railway.app")
API_KEY = os.getenv("API_KEY", "supersecureapikey123")
HEADERS = {"X-API-KEY": API_KEY}

st.set_page_config(page_title="Unified Real Estate Dashboard", layout="wide")
st.title("🏡 Unified Real Estate Data Dashboard")

tabs = st.tabs([
    "📤 Upload CSV", "📈 Upload Session", "🏷️ Enrich Fallbacks",
    "❌ View Fallbacks", "🔍 Property Lookup", "🧹 Scraping", "⬇️ Export", "ℹ️ Help"
])

# ---------- Tab 1: Upload CSV ----------
with tabs[0]:
    st.subheader("📤 Upload Unified CSV File")
    uploaded_file = st.file_uploader("Choose CSV File", type=["csv"])

    if uploaded_file and st.button("📤 Upload and Process"):
        with st.spinner("Reading file..."):
            file_bytes = uploaded_file.read()

        progress = st.progress(10)
        st.info("Uploading file to server...")

        try:
            response = requests.post(
                f"{API_URL}/upload/unified",
                headers=HEADERS,
                files={"file": (uploaded_file.name, io.BytesIO(file_bytes), "text/csv")}
            )
            progress.progress(90)

            if response.ok:
                st.success("✅ File uploaded. Background processing started.")
                st.json(response.json())
            else:
                st.error("❌ Upload failed")
                st.text(response.text)
        except Exception as e:
            st.error(f"🚫 Request failed: {e}")
        progress.empty()

# ---------- Tab 2: Upload Session ----------
with tabs[1]:
    st.subheader("📈 Upload Session Summary Report")
    session_id = st.text_input("Enter Upload Session ID")
    format = st.radio("Select Format", ["json", "csv"])

    if st.button("📄 Fetch Report"):
        if not session_id:
            st.warning("⚠️ Please enter a session ID")
        else:
            with st.spinner("Fetching report..."):
                try:
                    resp = requests.get(f"{API_URL}/upload/sessions/{session_id}/report?format={format}")
                    if resp.ok:
                        if format == "json":
                            st.json(resp.json())
                        else:
                            st.download_button("📥 Download CSV", resp.content, file_name=f"{session_id}_report.csv")
                        st.success("✅ Report loaded")
                    else:
                        st.error("❌ Failed to fetch report")
                        st.text(resp.text)
                except Exception as e:
                    st.error(f"🚫 Error: {e}")

# ---------- Tab 3: Enrich Missing APNs ----------
with tabs[2]:
    st.subheader("🏷️ Enrich Fallback Candidates")
    limit = st.slider("Number of fallback records to enrich", 1, 100, 10)

    if st.button("🚀 Run Enrichment"):
        progress = st.progress(5)
        with st.spinner("Running enrichment..."):
            try:
                resp = requests.post(f"{API_URL}/fallback/enrich_missing_apn?limit={limit}", headers=HEADERS)
                progress.progress(80)
                if resp.ok:
                    st.success("🎉 Enrichment Complete")
                    st.json(resp.json().get("summary", {}))
                else:
                    st.error("❌ Enrichment failed.")
                    st.text(resp.text)
            except Exception as e:
                st.error(f"🚫 Error: {e}")
        progress.empty()

# ---------- Tab 4: View Fallbacks ----------
with tabs[3]:
    st.subheader("❌ View Unresolved Fallback Candidates")
    if st.button("📥 Download Fallback Candidates"):
        with st.spinner("Downloading fallback candidates..."):
            try:
                resp = requests.get(f"{API_URL}/export/fallback")
                if resp.ok:
                    st.download_button("Download Fallback CSV", resp.content, "fallback_candidates.csv")
                    st.success("✅ Download ready")
                else:
                    st.error("❌ Failed to download fallback candidates.")
                    st.text(resp.text)
            except Exception as e:
                st.error(f"🚫 Error: {e}")

# ---------- Tab 5: Property Lookup ----------
with tabs[4]:
    st.subheader("🔍 Property Lookup")
    apn = st.text_input("Enter APN (Parcel Number)")

    if st.button("🔍 Lookup"):
        if not apn:
            st.warning("⚠️ Enter a valid APN")
        else:
            with st.spinner("Searching property..."):
                try:
                    resp = requests.get(f"{API_URL}/properties/{apn}")
                    if resp.ok:
                        st.success("✅ Property Found")
                        st.json(resp.json())
                    else:
                        st.error("❌ Property not found")
                        st.text(resp.text)
                except Exception as e:
                    st.error(f"🚫 Error: {e}")

# ---------- Tab 6: Scraping ----------
with tabs[5]:
    st.subheader("🧹 King County Scraper")
    mode = st.radio("Choose Scrape Source", ["📁 From CSV", "🗃️ From MongoDB"])

    if mode == "📁 From CSV":
        scrape_file = st.file_uploader("Upload File to Scrape", type=["csv"])
        if scrape_file and st.button("Start File-Based Scrape"):
            with st.spinner("Running file scrape..."):
                try:
                    resp = requests.post(
                        f"{API_URL}/scrape/kingcounty/json",
                        files={"file": (scrape_file.name, scrape_file, "text/csv")}
                    )
                    if resp.ok:
                        df = pd.DataFrame(resp.json())
                        st.success("✅ Scraping complete")
                        st.dataframe(df)
                        csv = df.to_csv(index=False).encode("utf-8")
                        st.download_button("Download Scraped CSV", csv, "scraped_data.csv")
                    else:
                        st.error("❌ Scraping failed.")
                        st.text(resp.text)
                except Exception as e:
                    st.error(f"🚫 Error: {e}")
    else:
        mongo_limit = st.slider("Mongo scrape limit", 1, 100, 10)
        if st.button("Run MongoDB Scrape"):
            with st.spinner("Scraping from MongoDB..."):
                try:
                    resp = requests.post(f"{API_URL}/scrape/kingcounty/mongo?limit={mongo_limit}")
                    if resp.ok:
                        st.success("✅ MongoDB Scrape complete")
                        st.json(resp.json())
                    else:
                        st.error("❌ Mongo scrape failed.")
                        st.text(resp.text)
                except Exception as e:
                    st.error(f"🚫 Error: {e}")

# ---------- Tab 7: Export ----------
with tabs[6]:
    st.subheader("⬇️ Export Full Dataset")
    if st.button("📥 Download Enriched Data"):
        with st.spinner("Exporting data..."):
            try:
                resp = requests.get(f"{API_URL}/export/full")
                if resp.ok:
                    st.download_button("Download CSV", resp.content, "full_export.csv")
                    st.success("✅ Export complete")
                else:
                    st.error("❌ Export failed.")
                    st.text(resp.text)
            except Exception as e:
                st.error(f"🚫 Error: {e}")

# ---------- Tab 8: Help ----------
with tabs[7]:
    st.subheader("ℹ️ API Field Requirements & Docs")
    if st.button("📋 Show Upload Field Requirements"):
        with st.spinner("Fetching field requirements..."):
            try:
                resp = requests.get(f"{API_URL}/upload/requirements/unified")
                if resp.ok:
                    data = resp.json()
                    st.markdown("### ✅ Required Fields:")
                    st.json(data.get("required_fields", {}))
                    st.markdown("### 🟡 Optional Fields:")
                    st.json(data.get("optional_fields", {}))
                else:
                    st.error("❌ Could not fetch requirements.")
            except Exception as e:
                st.error(f"🚫 Error: {e}")

    st.markdown("---")
    st.markdown("🔗 [View Swagger Docs](http://localhost:8000/docs)")

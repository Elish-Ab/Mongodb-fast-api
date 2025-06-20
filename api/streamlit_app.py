import streamlit as st
import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "your-api-key")  # replace with yours or set in .env

headers = {"X-API-KEY": API_KEY}

st.set_page_config(page_title="Unified Real Estate Dashboard", layout="centered")
st.title("🏡 Unified Real Estate Data Interface")

tab1, tab2, tab3 = st.tabs(["Upload CSV", "Fallback Enrichment", "Unresolved Fallbacks"])

# ------------------- Upload CSV -------------------
with tab1:
    st.header("📤 Upload Unified CSV")

    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    if uploaded_file:
        if st.button("Upload and Process"):
            with st.spinner("Uploading..."):
                files = {"file": uploaded_file.getvalue()}
                resp = requests.post(f"{API_URL}/upload/unified", files={"file": uploaded_file}, headers=headers)
                if resp.ok:
                    data = resp.json()
                    st.success("Upload successful!")
                    st.json(data)
                else:
                    st.error(f"Upload failed: {resp.status_code}")
                    st.text(resp.text)

# ------------------- Enrich Fallbacks -------------------
with tab2:
    st.header(" Enrich Missing APNs")
    limit = st.number_input("How many fallback records to try enriching?", min_value=1, max_value=100, value=10)
    if st.button("Run Enrichment"):
        with st.spinner("Enriching..."):
            resp = requests.post(f"{API_URL}/fallback/enrich_missing_apn?limit={limit}", headers=headers)
            if resp.ok:
                result = resp.json()
                st.success("Enrichment completed.")
                st.json(result["summary"])
            else:
                st.error("Failed to enrich")
                st.text(resp.text)

# ------------------- View Unresolved -------------------
with tab3:
    st.header("❌ Unresolved Fallback Records")
    reason = st.text_input("Filter by reason (optional)", value="")
    limit = st.slider("Limit", min_value=1, max_value=200, value=20)

    if st.button("Get Failed Records"):
        with st.spinner("Fetching failed records..."):
            params = {"limit": limit}
            if reason.strip():
                params["reason"] = reason.strip()
            resp = requests.get(f"{API_URL}/fallback/failed", params=params)
            if resp.ok:
                result = resp.json()
                st.success(f"Found {result['count']} unresolved records")
                st.dataframe(result["records"])
            else:
                st.error("Failed to fetch fallback records")
                st.text(resp.text)

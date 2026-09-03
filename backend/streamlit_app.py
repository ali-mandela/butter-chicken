import requests
import streamlit as st
from pymongo import MongoClient

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="AIVAR QA Agent", layout="wide")
st.title("AIVAR — Self-Healing QA Agent")

with st.form("run_form"):
    intent = st.text_area(
        "Test intent",
        "Log in with valid credentials and verify products page loads",
    )
    custom_target = st.checkbox("Use a custom target (instead of saucedemo default)")

    url = username = password = None
    if custom_target:
        col1, col2, col3 = st.columns(3)
        url = col1.text_input("URL")
        username = col2.text_input("Username")
        password = col3.text_input("Password", type="password")

    submitted = st.form_submit_button("Run")

if submitted:
    payload = {"intent": intent, "custom_target": custom_target}
    if custom_target:
        payload.update({"url": url, "username": username, "password": password})

    with st.spinner("Running..."):
        resp = requests.post(f"{API_URL}/execute", json=payload, timeout=180)

    if resp.status_code != 200:
        st.error(f"{resp.status_code}: {resp.text}")
    else:
        result = resp.json()

        status = result["status"]
        st.subheader(f"Result: {'✅ PASSED' if status == 'passed' else '❌ FAILED'}")

        st.write("**Steps**")
        for step_result in result["results"]:
            icon = "✅" if step_result["status"] == "passed" else "❌"
            target = step_result["step"].get("target", "")
            source = step_result.get("source", "")
            st.write(f"{icon} `{target}` — action: {step_result['step'].get('action')} — source: **{source}**")
            if step_result["status"] == "failed":
                st.caption(step_result.get("error", ""))

        if result["healing_events"]:
            st.write("**Healing events**")
            for event in result["healing_events"]:
                with st.container(border=True):
                    st.write(f"Target: `{event['target']}`")
                    st.write(f"Old attempt: {event['old_attempt']}")
                    st.write(f"New selector: `{event['new_selector']}`")
                    st.caption(event["reasoning"])

st.divider()
st.subheader("Run history")

client = MongoClient("mongodb://localhost:27017")
runs = list(client["aivar"]["runs"].find().sort("created_at", -1).limit(20))

if not runs:
    st.write("No runs yet.")
else:
    for r in runs:
        icon = "✅" if r["status"] == "passed" else "❌"
        st.write(f"{icon} {r['created_at']} — `{r['intent']}` — {r['url']} — {len(r['healing_events'])} heal(s)")

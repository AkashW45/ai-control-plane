import streamlit as st
import json
import os
import time

from services.jira import get_ticket
from services.llm import analyze_ticket
from services.rundeck import build_job_yaml, import_job, run_job, get_execution_state

st.set_page_config(layout="wide")
st.title("AI Control Plane")

# --------------------------
# 1️⃣ Fetch Jira
# --------------------------
jira_key = st.text_input("Jira Issue Key")

if st.button("Fetch Jira"):
    try:
        ticket = get_ticket(jira_key)
        st.session_state["ticket"] = ticket
        st.success("Jira ticket loaded")
    except Exception as e:
        st.error(str(e))

# --------------------------
# 2️⃣ Jira Preview
# --------------------------
if "ticket" in st.session_state:

    ticket = st.session_state["ticket"]

    st.subheader("Jira Overview")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Project", ticket["project"])
    col2.metric("Status", ticket["status"])
    col3.metric("Priority", ticket["priority"])
    col4.metric("Version", ticket["fixVersion"])

    st.markdown("### Summary")
    st.info(ticket["summary"])

    st.markdown("### Description")
    st.write(ticket["description"] or "No description")

    with st.expander("Full Jira Metadata"):
        st.json(ticket)

    # --------------------------
    # 3️⃣ Generate AI Plan
    # --------------------------
    if st.button("Generate AI Workflow"):

        with st.spinner("Analyzing ticket..."):
            plan = analyze_ticket(ticket)
            st.session_state["plan"] = plan

        st.success("AI Workflow Generated")

# --------------------------
# 4️⃣ Runbook Detailed Preview
# --------------------------
if "plan" in st.session_state:

    plan = st.session_state["plan"]

    st.subheader("AI Runbook Plan")

    for idx, step in enumerate(plan["steps"], start=1):
        st.markdown(f"#### Step {idx}: {step['description']}")

        for cmd in step["commands"]:
            st.code(cmd, language="bash")

    # --------------------------
    # Build YAML
    # --------------------------
    if st.button("Build Rundeck YAML"):

        yaml_payload = build_job_yaml(
            st.session_state["ticket"],
            st.session_state["plan"]
        )

        st.session_state["yaml"] = yaml_payload
        st.success("YAML Generated")

# --------------------------
# 5️⃣ YAML Preview
# --------------------------
if "yaml" in st.session_state:

    st.subheader("Generated Rundeck YAML")
    st.code(st.session_state["yaml"], language="yaml")

    if st.button("Create / Update in Rundeck"):

        result = import_job(st.session_state["yaml"])
        st.session_state["import_result"] = result

        if result.get("succeeded"):
            job_id = result["succeeded"][0]["id"]
            st.session_state["job_id"] = job_id
            st.success(f"Job Imported: {job_id}")
        else:
            st.error("Import Failed")
            st.json(result)

# --------------------------
# 6️⃣ Execution Panel
# --------------------------
if "job_id" in st.session_state:

    st.subheader("Execute Job")

    env_input = st.text_input("Environment", value="QA")
    version_input = st.text_input(
        "Version",
        value=st.session_state["ticket"]["fixVersion"]
    )

    if st.button("Run Job"):

        execution = run_job(
            st.session_state["job_id"],
            options={
                "environment": env_input,
                "version": version_input,
                "dry_run": "false"
            }
        )

        st.session_state["execution"] = execution
        execution_id = execution["id"]

        base = os.getenv("RUNDECK_BASE_URL")
        project = os.getenv("RUNDECK_PROJECT")

        execution_link = f"{base}/project/{project}/execution/show/{execution_id}"

        st.success("Execution Started")
        st.write("Execution Link:")
        st.write(execution_link)

# --------------------------
# 7️⃣ Execution Status
# --------------------------
if "execution" in st.session_state:

    execution_id = st.session_state["execution"]["id"]

    if st.button("Check Execution Status"):

        state = get_execution_state(execution_id)
        st.json(state)

        if state.get("completed"):
            st.success(f"Final Status: {state.get('executionState')}")
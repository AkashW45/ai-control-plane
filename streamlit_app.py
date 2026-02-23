import streamlit as st
import os

from services.jira import get_ticket
from services.llm import analyze_ticket, build_execution_brief
from services.rundeck import build_job_yaml, import_job, run_job, get_execution_state
from services.rundeck import get_execution_output
import time

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

        # Auto-generate execution brief from Jira
        execution_brief = build_execution_brief(ticket)
        st.session_state["execution_brief"] = execution_brief

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

# --------------------------
# 3️⃣ Execution Intent Editor
# --------------------------
if "execution_brief" in st.session_state:

    st.subheader("Execution Intent (Editable)")

    edited_brief = st.text_area(
        "Modify or refine what should be executed:",
        value=st.session_state["execution_brief"],
        height=200
    )

    additional_notes = st.text_area(
        "Additional Instructions (Optional)",
        placeholder="Example: include rollback, validate release folder, add timestamp log..."
    )

    final_prompt = edited_brief.strip()

    if additional_notes:
        final_prompt += "\n\nAdditional Notes:\n" + additional_notes.strip()

    if st.button("Generate AI Workflow"):

        with st.spinner("Generating runbook plan..."):
            plan = analyze_ticket(
                st.session_state["ticket"],
                final_prompt
            )
            st.session_state["plan"] = plan

        st.success("AI Workflow Generated")

# --------------------------
# 4️⃣ Runbook Preview
# --------------------------
if "plan" in st.session_state:

    plan = st.session_state["plan"]

    st.subheader("AI Runbook Plan")

    for idx, step in enumerate(plan["steps"], start=1):
        st.markdown(f"#### Step {idx}: {step['description']}")
        for cmd in step["commands"]:
            st.code(cmd, language="bash")

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
# --------------------------
# 8️⃣ Live Execution Logs
# --------------------------
if "execution" in st.session_state:

    execution_id = st.session_state["execution"]["id"]

    st.subheader("Live Execution Logs")

    log_placeholder = st.empty()

    if st.button("Start Live Log Stream"):

        for _ in range(30):  # poll 30 times (~60 seconds)
            try:
                output = get_execution_output(execution_id)

                lines = [
                    entry["log"]
                    for entry in output.get("entries", [])
                ]

                log_text = "\n".join(lines)

                log_placeholder.code(log_text)

                if output.get("completed"):
                    st.success("Execution Completed")
                    break

                time.sleep(2)

            except Exception as e:
                st.error(str(e))
                break
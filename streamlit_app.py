import streamlit as st
import time

from services.jira import get_ticket
from services.llm import analyze_ticket, build_execution_brief

# Rundeck (unchanged)
from services.rundeck import (
    build_job_yaml,
    import_job
)

from services.executor_factory import get_executor
from services.notifier import send_execution_email


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
# 3️⃣ Execution Intent
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
        placeholder="Example: include rollback, validate release folder..."
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

    executor_choice = st.selectbox(
        "Select Execution Backend",
        ["rundeck", "awx"],
        index=0
    )

    st.session_state["selected_executor"] = executor_choice

    # Rundeck YAML build remains same
    if executor_choice == "rundeck":
        if st.button("Build Rundeck YAML"):

            yaml_payload = build_job_yaml(
                st.session_state["ticket"],
                plan
            )

            st.session_state["yaml"] = yaml_payload
            st.success("YAML Generated")


# --------------------------
# 5️⃣ Rundeck YAML Preview
# --------------------------
if "yaml" in st.session_state and st.session_state.get("selected_executor") == "rundeck":

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
# 6️⃣ Execution Panel (Unified)
# --------------------------
if "plan" in st.session_state:

    st.subheader("Execute Job")

    env_input = st.text_input("Environment", value="QA")
    version_input = st.text_input(
        "Version",
        value=st.session_state["ticket"]["fixVersion"]
    )

    if st.button("Run Job"):

        ticket = st.session_state["ticket"]
        plan = st.session_state["plan"]
        executor_type = st.session_state.get("selected_executor", "rundeck")

        executor = get_executor(executor_type)

        execution = executor.run(
            ticket,
            plan,
            options={
                "environment": env_input,
                "version": version_input,
                "dry_run": "false"
            },
            context={
                "environment": env_input,
                "version": version_input
            }
        )

        st.session_state["execution"] = execution
        st.session_state["active_executor"] = executor_type

        st.success("Execution Started")


# --------------------------
# 7️⃣ Live Logs (Executor Agnostic)
# --------------------------
if "execution" in st.session_state:

    execution = st.session_state["execution"]
    executor_type = st.session_state["active_executor"]

    executor = get_executor(executor_type)

    execution_id = execution.get("id") or execution.get("job")

    execution_url = executor.get_execution_url(execution_id)

    st.success("Execution Started")
    execution_url = executor.get_execution_url(execution_id)
    st.write("Execution Link:")
    st.write(execution_url)
    st.markdown(f"[Open Execution in {executor_type.upper()}]({execution_url})")

    st.subheader("Live Execution Logs")

    log_placeholder = st.empty()

    if st.button("Start Live Log Stream"):

        for _ in range(30):

            try:
                status = executor.get_status(execution_id)
                logs = executor.get_logs(execution_id)

                if isinstance(logs, str):
                    log_placeholder.code(logs)
                else:
                    lines = [entry["log"] for entry in logs.get("entries", [])]
                    log_placeholder.code("\n".join(lines))

                if status.get("status") in ["successful", "failed"]:

                    final_state = status["status"]
                    st.success(f"Execution Completed: {final_state}")

                    subject = f"{executor_type.upper()} Execution {final_state.upper()}"
                    body = f"""
Job: {jira_key}
State: {final_state}

Logs:
{logs}
"""

                    send_execution_email(subject, body)
                    break

                time.sleep(2)

            except Exception as e:
                st.error(str(e))
                break
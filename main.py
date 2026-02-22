from services.jira import get_ticket
from services.llm import analyze_ticket
from services.rundeck import build_job_yaml, import_job, run_job, get_execution_state
import os
import json
import time


def execute_control_plane(issue_key: str):

    print(f"\nFetching Jira Ticket: {issue_key}")
    ticket = get_ticket(issue_key)

    print("\nGenerating AI Workflow...")
    plan = analyze_ticket(ticket)

    print("\n=== AI WORKFLOW PREVIEW (JSON) ===")
    print(json.dumps(plan, indent=2))

    print("\nBuilding Rundeck YAML...")
    yaml_payload = build_job_yaml(ticket, plan)

    print("\n=== RUNBOOK YAML PREVIEW ===")
    print(yaml_payload)

    decision = input("\nCreate / Update job in Rundeck? (yes/no): ").strip().lower()
    if decision != "yes":
        print("Cancelled.")
        return

    print("\nImporting job...")
    result = import_job(yaml_payload)

    if not result.get("succeeded"):
        print("Import failed:")
        print(json.dumps(result, indent=2))
        return

    job_id = result["succeeded"][0]["id"]
    print(f"\nJob Created/Updated: {job_id}")

    run_now = input("\nExecute job now? (yes/no): ").strip().lower()
    if run_now != "yes":
        return

    env_input = input("Environment (default QA): ").strip() or "QA"
    version_input = input(f"Version (default {ticket['fixVersion']}): ").strip() or ticket["fixVersion"]

    execution = run_job(job_id, options={
        "environment": env_input,
        "version": version_input,
        "dry_run": "false"
    })

    print("\nExecution started:")
    print(json.dumps(execution, indent=2))

    execution_id = execution["id"]
    base = os.getenv("RUNDECK_BASE_URL")
    project = os.getenv("RUNDECK_PROJECT")

    execution_link = f"{base}/project/{project}/execution/show/{execution_id}"

    print("\nView execution in browser:")
    print(execution_link)

    print("\nPolling execution state...")

    while True:
        state = get_execution_state(execution_id)

        if state.get("completed"):
            final_status = state.get("executionState")
            print("\nExecution completed.")
            print(f"Final Status: {final_status}")
            break

        print("Execution still running...")
        time.sleep(3)


if __name__ == "__main__":
    issue = input("Enter Jira Issue Key: ").strip()
    execute_control_plane(issue)
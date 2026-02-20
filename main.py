from services.jira import get_ticket
from services.llm import analyze_ticket
from services.rundeck import create_dynamic_job
import os
import json


def execute_control_plane(issue_key: str):
    print(f"\nFetching Jira Ticket: {issue_key}")
    ticket = get_ticket(issue_key)

    print("\nGenerating AI Workflow...")
    job_definition = analyze_ticket(ticket)

    print("\n=== AI WORKFLOW PREVIEW ===")
    print(json.dumps(job_definition, indent=2))

    commands = job_definition.get("sequence", {}).get("commands", [])
    if not commands:
        print("No steps generated. Aborting.")
        return

    decision = input("\nCreate job in Rundeck? (yes/no): ").strip().lower()
    if decision != "yes":
        print("Cancelled.")
        return

    print("\nCreating job...")
    result = create_dynamic_job(job_definition)

    if not result.get("succeeded"):
        print("Job creation failed:")
        print(json.dumps(result, indent=2))
        return

    job_id = result["succeeded"][0]["id"]
    base = os.getenv("RUNDECK_BASE_URL")
    project = os.getenv("RUNDECK_PROJECT")

    print("\n✅ Job Successfully Created.")
    print("\nOpen this job to review and execute manually:")
    print(f"{base}/project/{project}/job/show/{job_id}")


if __name__ == "__main__":
    execute_control_plane("DEV-1")
# test change

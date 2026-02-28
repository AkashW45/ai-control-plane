# services/job_router.py

import os


def route_job(ticket: dict) -> dict:

    default_executor = os.getenv("DEFAULT_EXECUTOR", "rundeck")
    default_rundeck_project = os.getenv("RUNDECK_DEFAULT_PROJECT")
    default_awx_template = os.getenv("AWX_TEMPLATE_NAME")

    issue_type = (ticket.get("issuetype") or "").lower()
    summary = (ticket.get("summary") or "").lower()
    labels = [l.lower() for l in ticket.get("labels", [])]

    # Example logic
    if "production" in labels:
        return {
            "executor": "awx",
            "context": {
                "template_name": default_awx_template
            }
        }

    if "release" in summary:
        return {
            "executor": "rundeck",
            "context": {
                "project": default_rundeck_project
            }
        }

    if issue_type == "bug":
        return {
            "executor": default_executor,
            "context": {}
        }

    return {
        "executor": default_executor,
        "context": {}
    }
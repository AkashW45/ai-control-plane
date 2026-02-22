import os


def route_job(ticket: dict) -> dict:
    """
    Dynamically determine Rundeck project from Jira metadata.
    """

    default_project = os.getenv("RUNDECK_DEFAULT_PROJECT")

    issue_type = (ticket.get("issue_type") or "").lower()
    summary = (ticket.get("summary") or "").lower()
    labels = [l.lower() for l in ticket.get("labels", [])]

    # Release-based routing
    if "release" in summary:
        return {"project": default_project, "job_id": None}

    # Database routing
    if "db" in summary or "database" in summary or "db" in labels:
        return {"project": default_project, "job_id": None}

    # Bug routing
    if issue_type == "bug":
        return {"project": default_project, "job_id": None}

    # Fallback
    return {"project": default_project, "job_id": None}
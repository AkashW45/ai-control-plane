import os

# Map job types to Rundeck projects + predefined job IDs
JOB_ROUTES = {
    "release": {
        "project": "ms-runbook-poc",
        "job_id": os.getenv("RUNDECK_JOB_ID")  # existing release job
    },
    "database": {
        "project": "db-automation",
        "job_id": None  # dynamic only
    }
}


def route_job(plan: dict) -> dict:
    job_type = plan.get("job_type")

    route = JOB_ROUTES.get(job_type)

    if route:
        return {
            "project": route["project"],
            "job_id": route["job_id"]
        }

    # fallback
    return {
        "project": os.getenv("RUNDECK_DEFAULT_PROJECT"),
        "job_id": None
    }

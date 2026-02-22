import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE = os.getenv("JIRA_BASE_URL")
EMAIL = os.getenv("JIRA_EMAIL")
TOKEN = os.getenv("JIRA_API_TOKEN")


def extract_text_from_adf(adf):
    if not adf:
        return ""
    try:
        return adf["content"][0]["content"][0]["text"]
    except Exception:
        return ""


def get_ticket(ticket_id: str):
    url = f"{JIRA_BASE}/rest/api/3/issue/{ticket_id}?expand=names,changelog"
    response = requests.get(
        url,
        auth=(EMAIL, TOKEN),
        headers={"Accept": "application/json"}
    )
    response.raise_for_status()

    data = response.json()
    fields = data["fields"]

    description = extract_text_from_adf(fields.get("description"))

    version = None
    if fields.get("fixVersions"):
        version = fields["fixVersions"][0]["name"]

    return {
        "key": data["key"],
        "summary": fields.get("summary", ""),
        "description": description,
        "priority": fields.get("priority", {}).get("name", "Medium"),
        "status": fields.get("status", {}).get("name", ""),
        "issuetype": fields.get("issuetype", {}).get("name", ""),
        "project": fields.get("project", {}).get("key", ""),
        "fixVersion": version or "auto"
    }
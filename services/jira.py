import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE = os.getenv("JIRA_BASE_URL")
EMAIL = os.getenv("JIRA_EMAIL")
TOKEN = os.getenv("JIRA_API_TOKEN")

def get_ticket(ticket_id: str):
    url = f"{JIRA_BASE}/rest/api/3/issue/{ticket_id}"
    response = requests.get(
        url,
        auth=(EMAIL, TOKEN),
        headers={"Accept": "application/json"}
    )
    response.raise_for_status()
    data = response.json()
    fields = data["fields"]

    return {
        "key": data["key"],
        "summary": fields.get("summary", ""),
        "description": fields.get("description", ""),
        "priority": fields.get("priority", {}).get("name", "Medium"),
        "status": fields.get("status", {}).get("name", ""),
        "issuetype": fields.get("issuetype", {}).get("name", "")
    }

import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

base = os.getenv("JIRA_BASE_URL")
email = os.getenv("JIRA_EMAIL")
token = os.getenv("JIRA_API_TOKEN")

issue_key = "DEV-1"

url = f"{base}/rest/api/3/issue/{issue_key}"

print("URL:", url)

response = requests.get(
    url,
    auth=HTTPBasicAuth(email, token),
    headers={"Accept": "application/json"}
)

print("Status Code:", response.status_code)
print("Response:", response.text)

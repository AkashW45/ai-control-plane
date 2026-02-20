import requests
import os
from dotenv import load_dotenv

load_dotenv()

RUNDECK_BASE_URL = os.getenv("RUNDECK_BASE_URL")
RUNDECK_API_TOKEN = os.getenv("RUNDECK_API_TOKEN")
RUNDECK_JOB_ID = os.getenv("RUNDECK_JOB_ID")

print("BASE:", RUNDECK_BASE_URL)
print("JOB:", RUNDECK_JOB_ID)

url = f"{RUNDECK_BASE_URL}/api/47/job/{RUNDECK_JOB_ID}/run"

headers = {
    "X-Rundeck-Auth-Token": RUNDECK_API_TOKEN,
    "Content-Type": "application/json"
}

payload = {
    "argString": "-env qa"
}

response = requests.post(url, headers=headers, json=payload)

print("Status:", response.status_code)
print("Response:", response.text)

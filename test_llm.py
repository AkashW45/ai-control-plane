import requests
import json

OLLAMA_URL = "http://localhost:11434/api/generate"

payload = {
    "model": "llama3",
    "format": "json",
    "prompt": """
You are an automation translator.

Convert the following Jira request into a Rundeck execution plan.

Return ONLY this JSON schema:

{
  "job_name": "",
  "environment": "",
  "rundeck_job_id": "",
  "parameters": {}
}

Jira Request:
Release 1.0 to QA
""",
    "stream": False
}




response = requests.post(
    OLLAMA_URL,
    json=payload
)

print("Status:", response.status_code)
print("Raw:", response.text)

data = response.json()
print("Model Response:", data["response"])

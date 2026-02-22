import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("CEREBRAS_BASE_URL")
API_KEY = os.getenv("CEREBRAS_API_KEY")
MODEL = os.getenv("CEREBRAS_MODEL")


def analyze_ticket(ticket: dict) -> dict:
    prompt = f"""
You are a DevOps automation planner.

Return JSON only.

Schema:

{{
  "steps": [
    {{
      "description": "...",
      "commands": [
        "shell command",
        "shell command"
      ]
    }}
  ]
}}

Rules:
- Exactly 4 steps
- /bin/sh compatible
- Allowed: echo, mkdir, touch, ls, date, whoami
- All paths must start with:
  ${{option.environment}}/releases/${{option.version}}
- No absolute paths
- No sudo/systemctl/docker
- Each command separate string

Jira Metadata:
Project: {ticket["project"]}
Issue Type: {ticket["issuetype"]}
Priority: {ticket["priority"]}
Status: {ticket["status"]}
Version: {ticket["fixVersion"]}
Summary: {ticket["summary"]}
Description: {ticket["description"]}
"""

    response = requests.post(
        BASE_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        },
        timeout=120
    )

    response.raise_for_status()

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    return json.loads(content)
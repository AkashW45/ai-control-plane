import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("CEREBRAS_BASE_URL")
API_KEY = os.getenv("CEREBRAS_API_KEY")
MODEL = os.getenv("CEREBRAS_MODEL")


# -------------------------
# 1️⃣ Create Jira Execution Brief
# -------------------------
def build_execution_brief(ticket: dict) -> str:
    summary = ticket.get("summary", "")
    description = ticket.get("description", "")
    version = ticket.get("fixVersion", "")
    priority = ticket.get("priority", "")

    return f"""
Deploy version {version} related to:
{summary}

Details:
{description}

Priority: {priority}
""".strip()


# -------------------------
# 2️⃣ Build Internal Prompt (Hidden)
# -------------------------
def build_internal_prompt(final_user_prompt: str) -> str:
    return f"""
You are a DevOps automation planner.

Return JSON only.

Schema:
{{
  "steps": [
    {{
      "description": "...",
      "commands": [
        "shell command"
        
      ]
    }}
  ]
}}

Rules:
- Exactly 4 steps
- /bin/sh compatible
- Allowed: echo, mkdir, touch, ls, date, whoami
- Use placeholders:
    {{environment}}
    {{version}}
- Example path:
    {{environment}}/releases/{{version}}
- No absolute paths
- No sudo/systemctl/docker
- Each command must be a separate string
- Every step must include visible logging using echo

- The final step must print a completion message using echo

Execution Intent:
{final_user_prompt}
"""


# -------------------------
# 3️⃣ Analyze Ticket
# -------------------------
def analyze_ticket(ticket: dict, user_prompt: str) -> dict:

    internal_prompt = build_internal_prompt(user_prompt)

    response = requests.post(
        BASE_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": internal_prompt}],
            "temperature": 0.2
        },
        timeout=120
    )

    response.raise_for_status()

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    return json.loads(content)
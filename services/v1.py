import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL")
MODEL = os.getenv("OLLAMA_MODEL", "llama3")


def analyze_ticket(ticket: dict) -> dict:
    """
    Generate stable, container-safe runbook workflow.
    No conditional logic.
    """

    prompt = f"""
You are a senior DevOps automation engineer.

Generate a structured runbook workflow in JSON.

STRICT RULES:
- Return ONLY valid JSON.
- Generate exactly 4 steps.
- Each step must contain:
  - description
  - exec (multi-line shell script)
- Scripts must be compatible with /bin/sh.
- No if conditions.
- No export.
- No systemctl, service, sudo, docker, git.
- Allowed commands: echo, sleep, mkdir, touch, ls, date, whoami.
- Each step must reference:
    ${{option.environment}}
    ${{option.version}}
    ${{option.dry_run}}
- Each command must be on its own line.

Schema:

{{
  "name": "{ticket.get("key")}",
  "description": "{ticket.get("summary")}",
  "sequence": {{
    "commands": [
      {{
        "description": "Step description",
        "exec": "multi-line shell script"
      }}
    ]
  }}
}}

Jira Ticket:
Key: {ticket.get("key")}
Summary: {ticket.get("summary")}
Description: {ticket.get("description")}
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "format": "json",
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    response.raise_for_status()

    raw_output = response.json().get("response", "").strip()

    if not raw_output:
        raise ValueError("LLM returned empty response")

    return json.loads(raw_output)

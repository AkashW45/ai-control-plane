import os
import requests
import yaml
import re
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("RUNDECK_BASE_URL")
TOKEN = os.getenv("RUNDECK_API_TOKEN")
PROJECT = os.getenv("RUNDECK_PROJECT")

HEADERS = {
    "X-Rundeck-Auth-Token": TOKEN,
    "Content-Type": "application/yaml",
    "Accept": "application/json"
}


def validate_step(exec_script: str) -> str:
    """
    Validate and auto-fix unsafe or non-idempotent commands.
    """

    lines = exec_script.split("\n")
    fixed_lines = []

    for line in lines:
        stripped = line.strip()

        # 🔒 Block absolute paths anywhere
        if re.search(r"\s/+", stripped) or stripped.startswith("/"):
            raise ValueError("Unsafe script: absolute paths are not allowed.")

        # 🔒 Block dangerous commands
        blocked = ["sudo", "systemctl", "service", "docker", "rm -rf /"]
        for word in blocked:
            if word in stripped:
                raise ValueError(f"Unsafe script: contains blocked command '{word}'.")

        # 🔧 Auto-fix mkdir to mkdir -p
        if stripped.startswith("mkdir ") and "-p" not in stripped:
            line = line.replace("mkdir ", "mkdir -p ", 1)

        fixed_lines.append(line)

    return "\n".join(fixed_lines)



def create_dynamic_job(ai_definition: dict) -> dict:

    commands = ai_definition.get("sequence", {}).get("commands", [])

    if not commands:
        return {"error": True, "message": "No workflow steps generated."}

    steps = [{
    "description": "Initialize release directory",
    "exec": "mkdir -p ${option.environment}/releases/${option.version}"
    }]


    for step in commands:
        exec_script = step.get("exec", "").strip()
        if not exec_script:
            continue

        # 🔒 Validate before sending
        exec_script = validate_step(exec_script)


        steps.append({
            "description": step.get("description", "Step"),
            "exec": exec_script
        })

    job_yaml = [{
        "name": ai_definition.get("name", "AI Runbook"),
        "project": PROJECT,
        "description": ai_definition.get("description", ""),
        "loglevel": "INFO",
        "executionEnabled": True,
        "scheduleEnabled": False,
        "nodeFilterEditable": False,

        "nodefilters": {
            "dispatch": {
                "threadcount": 1,
                "keepgoing": False
            },
            "filter": "name: .*"
        },

        "options": [
            {
                "name": "environment",
                "description": "Target deployment environment",
                "required": True,
                "defaultValue": "QA"
            },
            {
                "name": "version",
                "description": "Release version",
                "required": True,
                "defaultValue": "1.0"
            },
            {
                "name": "dry_run",
                "description": "Simulate execution only",
                "required": True,
                "defaultValue": "false"
            }
        ],

        "sequence": {
            "keepgoing": False,
            "strategy": "node-first",
            "commands": steps
        }
    }]

    yaml_payload = yaml.dump(job_yaml, sort_keys=False)

    url = f"{BASE}/api/47/project/{PROJECT}/jobs/import?format=yaml&dupeOption=update"

    response = requests.post(url, headers=HEADERS, data=yaml_payload)

    return response.json()

import os
import requests
import yaml
import time
from dotenv import load_dotenv
from yaml.representer import SafeRepresenter

load_dotenv()

BASE    = os.getenv("RUNDECK_BASE_URL")
TOKEN   = os.getenv("RUNDECK_API_TOKEN")
PROJECT = os.getenv("RUNDECK_PROJECT")

HEADERS_YAML = {
    "X-Rundeck-Auth-Token": TOKEN,
    "Content-Type": "application/yaml",
    "Accept": "application/json"
}

HEADERS_JSON = {
    "X-Rundeck-Auth-Token": TOKEN,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# Bare commands that produce noisy useless output
_NOISE = {"ls", "date", "whoami", "pwd"}

def _is_noise(cmd: str) -> bool:
    return cmd.strip() in _NOISE

def _resolve_vars(cmd: str, environment: str, version: str) -> str:
    cmd = cmd.replace("${option.environment}", environment)
    cmd = cmd.replace("${option.version}",     version)
    cmd = cmd.replace("{{ environment }}",      environment)
    cmd = cmd.replace("{{ version }}",          version)
    cmd = cmd.replace("{environment}",          environment)
    cmd = cmd.replace("{version}",              version)
    return cmd


class LiteralString(str):
    pass

def literal_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")

yaml.add_representer(LiteralString, literal_representer)


def build_job_yaml(ticket: dict, plan: dict, commands=None):

    environment = ticket.get("environment", "QA")
    version     = ticket.get("fixVersion",  "auto")
    plan_steps  = plan.get("steps", [])
    rundeck_steps = []

    if commands:
        # Executor already resolved vars — distribute back per step
        cmd_iter = iter(commands)
        for step in plan_steps:
            count     = len(step.get("commands", []))
            step_cmds = []
            for _ in range(count):
                try:
                    step_cmds.append(next(cmd_iter))
                except StopIteration:
                    break
            clean = [c for c in step_cmds if not _is_noise(c) and c.strip()]
            if clean:
                rundeck_steps.append({
                    "description": step.get("description", "Step"),
                    "script":      LiteralString("\n".join(clean))
                })
        # Any remaining
        remaining = [c for c in cmd_iter if not _is_noise(c) and c.strip()]
        if remaining:
            rundeck_steps.append({
                "description": "Additional Steps",
                "script":      LiteralString("\n".join(remaining))
            })
    else:
        # Resolve vars here — one script block per step
        for step in plan_steps:
            clean = [
                _resolve_vars(cmd, environment, version)
                for cmd in step.get("commands", [])
                if not _is_noise(cmd) and cmd.strip()
            ]
            if clean:
                rundeck_steps.append({
                    "description": step.get("description", "Step"),
                    "script":      LiteralString("\n".join(clean))
                })

    if not rundeck_steps:
        rundeck_steps.append({
            "description": "No commands",
            "script":      LiteralString('echo "No commands to execute"')
        })

    job_yaml = [{
        "name":             ticket["key"],
        "description":      ticket.get("summary", ""),
        "project":          PROJECT,
        "loglevel":         "INFO",
        "executionEnabled": True,
        "scheduleEnabled":  False,
        "nodeFilterEditable":     False,
        "nodesSelectedByDefault": True,
        "nodefilters": {
            "dispatch": {
                "threadcount": 1,
                "keepgoing":   False,
                "rankOrder":   "ascending"
            },
            "filter": "name: .*"
        },
        "options": [
            {"name": "environment", "required": True, "value": environment},
            {"name": "version",     "required": True, "value": version},
            {"name": "dry_run",     "required": True, "value": "false"}
        ],
        "sequence": {
            "strategy":  "node-first",
            "keepgoing": False,
            "commands": [
                {"description": s["description"], "script": s["script"]}
                for s in rundeck_steps
            ]
        }
    }]

    return yaml.dump(job_yaml, sort_keys=False)


def import_job(yaml_payload):
    url = f"{BASE}/api/47/project/{PROJECT}/jobs/import?format=yaml&dupeOption=update"
    response = requests.post(url, headers=HEADERS_YAML, data=yaml_payload)
    response.raise_for_status()
    return response.json()


def run_job(job_id, options=None):
    url = f"{BASE}/api/47/job/{job_id}/run"
    response = requests.post(url, headers=HEADERS_JSON, json={"options": options or {}})
    response.raise_for_status()
    return response.json()


def get_execution_state(execution_id):
    url = f"{BASE}/api/47/execution/{execution_id}/state"
    response = requests.get(url, headers=HEADERS_JSON)
    response.raise_for_status()
    return response.json()


def get_execution_output(execution_id, last_lines=200):
    url = f"{BASE}/api/41/execution/{execution_id}/output"
    response = requests.get(
        url,
        headers={"X-Rundeck-Auth-Token": TOKEN},
        params={"format": "json", "lastlines": last_lines}
    )
    response.raise_for_status()
    data = response.json()
    data["entries"] = [
        e for e in data.get("entries", [])
        if e.get("log", "").strip()
        and e.get("type") == "log"
        and e.get("stepctx")
    ]
    return data
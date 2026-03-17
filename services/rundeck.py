import os
import requests
import yaml
from dotenv import load_dotenv

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

# Execution order for group types
GROUP_ORDER = {
    "migration":  1,
    "bugfix":     2,
    "testing":    3,
    "feature":    4,
    "deployment": 5,
}

# Bare commands that produce noisy output
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


# ─────────────────────────────────────────────────────────
# Build job YAML for a single group
# job_name = ticket_key + group type e.g. DEV-1-migration
# ─────────────────────────────────────────────────────────
def build_group_job_yaml(ticket: dict, group: dict, options: dict) -> str:

    environment = options.get("environment", ticket.get("environment", "QA"))
    version     = options.get("version",     ticket.get("fixVersion",  "auto"))

    ticket_key  = ticket.get("key", "JOB")
    group_type  = group.get("type", "deployment")
    group_name  = group.get("name", group_type)
    job_name    = f"{ticket_key}-{group_type}"

    rundeck_steps = []

    # Pre-check step
    pre_checks = group.get("pre_checks", [])
    if pre_checks:
        lines = [f"echo 'PRE-CHECK: {c}'" for c in pre_checks]
        rundeck_steps.append({
            "description": f"Pre-checks — {group_name}",
            "script":      LiteralString("\n".join(lines))
        })

    # One script block per step in the group
    for step in group.get("steps", []):
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

    # Validation step
    validation = group.get("validation", [])
    if validation:
        lines = [f"echo 'VALIDATE: {v}'" for v in validation]
        rundeck_steps.append({
            "description": f"Validation — {group_name}",
            "script":      LiteralString("\n".join(lines))
        })

    if not rundeck_steps:
        rundeck_steps.append({
            "description": "No commands",
            "script":      LiteralString('echo "No commands for this group"')
        })

    job_yaml = [{
        "name":             job_name,
        "description":      f"{group_name} | Tickets: {', '.join(group.get('tickets', []))}",
        "project":          PROJECT,
        "loglevel":         "INFO",
        "executionEnabled": True,
        "scheduleEnabled":  False,
        "nodeFilterEditable":     False,
        "nodesSelectedByDefault": True,
        "nodefilters": {
            "dispatch": {"threadcount": 1, "keepgoing": False, "rankOrder": "ascending"},
            "filter":   "name: .*"
        },
        "options": [
            {"name": "environment", "required": True, "value": environment},
            {"name": "version",     "required": True, "value": version},
            {"name": "dry_run",     "required": True, "value": "false"}
        ],
        "sequence": {
            "strategy":  "node-first",
            "keepgoing": False,
            "commands":  [
                {"description": s["description"], "script": s["script"]}
                for s in rundeck_steps
            ]
        }
    }]

    return yaml.dump(job_yaml, sort_keys=False)


# ─────────────────────────────────────────────────────────
# Build post-deployment validation job
# Runs after ALL groups succeed
# ─────────────────────────────────────────────────────────
def build_validation_job_yaml(ticket: dict, plan: dict, options: dict) -> str:

    environment = options.get("environment", "QA")
    version     = options.get("version",     "auto")
    ticket_key  = ticket.get("key", "JOB")
    job_name    = f"{ticket_key}-post-validation"

    lines = [f"echo '=== POST-DEPLOYMENT VALIDATION ==='"]

    # Global validation from plan
    for v in plan.get("validation", []):
        lines.append(f"echo 'CHECK: {v}'")

    # Per-group validation
    for group in plan.get("groups", []):
        gname = group.get("name", "")
        for v in group.get("validation", []):
            lines.append(f"echo '[{gname}] VALIDATE: {v}'")

    lines.append(f"echo 'Validation complete for {environment} v{version}'")

    job_yaml = [{
        "name":             job_name,
        "description":      f"Post-deployment validation — {ticket.get('summary', '')}",
        "project":          PROJECT,
        "loglevel":         "INFO",
        "executionEnabled": True,
        "scheduleEnabled":  False,
        "nodeFilterEditable":     False,
        "nodesSelectedByDefault": True,
        "nodefilters": {
            "dispatch": {"threadcount": 1, "keepgoing": False, "rankOrder": "ascending"},
            "filter":   "name: .*"
        },
        "options": [
            {"name": "environment", "required": True, "value": environment},
            {"name": "version",     "required": True, "value": version}
        ],
        "sequence": {
            "strategy":  "node-first",
            "keepgoing": True,
            "commands": [{
                "description": "Post-deployment validation checks",
                "script":      LiteralString("\n".join(lines))
            }]
        }
    }]

    return yaml.dump(job_yaml, sort_keys=False)


# ─────────────────────────────────────────────────────────
# Original build_job_yaml — preserved for single-ticket flow
# ─────────────────────────────────────────────────────────
def build_job_yaml(ticket: dict, plan: dict, commands=None):

    environment = ticket.get("environment", "QA")
    version     = ticket.get("fixVersion",  "auto")
    plan_steps  = plan.get("steps", [])
    rundeck_steps = []

    if commands:
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
        remaining = [c for c in cmd_iter if not _is_noise(c) and c.strip()]
        if remaining:
            rundeck_steps.append({
                "description": "Additional Steps",
                "script":      LiteralString("\n".join(remaining))
            })
    else:
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
            "dispatch": {"threadcount": 1, "keepgoing": False, "rankOrder": "ascending"},
            "filter":   "name: .*"
        },
        "options": [
            {"name": "environment", "required": True, "value": environment},
            {"name": "version",     "required": True, "value": version},
            {"name": "dry_run",     "required": True, "value": "false"}
        ],
        "sequence": {
            "strategy":  "node-first",
            "keepgoing": False,
            "commands":  [
                {"description": s["description"], "script": s["script"]}
                for s in rundeck_steps
            ]
        }
    }]

    return yaml.dump(job_yaml, sort_keys=False)


# ─────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────
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
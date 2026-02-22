import os
import requests
import yaml
import time
from dotenv import load_dotenv
from yaml.representer import SafeRepresenter

load_dotenv()

BASE = os.getenv("RUNDECK_BASE_URL")
TOKEN = os.getenv("RUNDECK_API_TOKEN")
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


class LiteralString(str):
    pass


def literal_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralString, literal_representer)


def build_job_yaml(ticket: dict, plan: dict):

    steps = []

    for step in plan["steps"]:
        script = "\n".join(step["commands"])

        steps.append({
            "description": step["description"],
            "exec": LiteralString(script)
        })

    job_yaml = [{
        "name": ticket["key"],
        "description": ticket["summary"],
        "project": PROJECT,
        "loglevel": "INFO",
        "executionEnabled": True,
        "scheduleEnabled": False,
        "nodeFilterEditable": False,
        "nodesSelectedByDefault": True,
        "nodefilters": {
            "dispatch": {
                "threadcount": 1,
                "keepgoing": False,
                "rankOrder": "ascending"
            },
            "filter": "name: .*"
        },
        "options": [
            {
                "name": "environment",
                "required": True,
                "value": "QA"
            },
            {
                "name": "version",
                "required": True,
                "value": ticket["fixVersion"]
            },
            {
                "name": "dry_run",
                "required": True,
                "value": "false"
            }
        ],
        "sequence": {
            "strategy": "node-first",
            "keepgoing": False,
            "commands": steps
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

    payload = {
        "options": options or {}
    }

    response = requests.post(url, headers=HEADERS_JSON, json=payload)
    response.raise_for_status()
    return response.json()


def get_execution_state(execution_id):
    url = f"{BASE}/api/47/execution/{execution_id}/state"
    response = requests.get(url, headers=HEADERS_JSON)
    response.raise_for_status()
    return response.json()
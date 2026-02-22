from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import requests
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ==============================
# CONFIGURATION
# ==============================

RUNDECK_URL = "http://localhost"
RUNDECK_PROJECT = "ms-runbook"
RUNDECK_API_VERSION = "47"
RUNDECK_TOKEN = os.getenv("RUNDECK_TOKEN")  # Set this in environment


# ==============================
# MOCK AI GENERATOR
# ==============================

def generate_job_from_prompt(prompt: str):
    return {
        "name": "AI Generated Job",
        "description": prompt,
        "commands": [
            "mkdir -p /tmp/test",
            "echo Hello World",
            "ls -l"
        ]
    }


# ==============================
# RUNDECK JOB CREATION
# ==============================

def create_rundeck_job(job_name, description, commands):
    url = f"{RUNDECK_URL}/api/{RUNDECK_API_VERSION}/project/{RUNDECK_PROJECT}/jobs/import?format=json&dupeOption=create"

    headers = {
        "X-Rundeck-Auth-Token": RUNDECK_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = [
        {
            "name": job_name,
            "project": RUNDECK_PROJECT,
            "description": description,
            "loglevel": "INFO",
            "sequence": {
                "keepgoing": False,
                "strategy": "node-first",
                "commands": [{"exec": cmd} for cmd in commands]
            },
            "nodefilters": {
                "filter": ".*"
            }
        }
    ]

    response = requests.post(url, json=payload, headers=headers)

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)

    return response.json()


# ==============================
# ROUTES
# ==============================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/fetch-jira", response_class=HTMLResponse)
def fetch_jira(request: Request, jira_key: str = Form(...)):
    # MOCK JIRA RESPONSE
    mock_prompt = f"Release version 2.1.0 for issue {jira_key} to QA environment."

    return templates.TemplateResponse("index.html", {
        "request": request,
        "prefill_prompt": mock_prompt
    })


@app.post("/generate", response_class=HTMLResponse)
def generate(request: Request, prompt: str = Form(...)):
    job_data = generate_job_from_prompt(prompt)

    return templates.TemplateResponse("preview.html", {
        "request": request,
        "name": job_data["name"],
        "description": job_data["description"],
        "commands": job_data["commands"]
    })


@app.post("/create-job")
def create_job(name: str = Form(...),
               description: str = Form(...),
               commands: str = Form(...)):

    command_list = commands.split("|||")

    result = create_rundeck_job(name, description, command_list)

    if "error" in result:
        return result

    if "succeeded" not in result or not result["succeeded"]:
       return {"error": result}

    job_id = result["succeeded"][0]["id"]

    return RedirectResponse(
        url=f"{RUNDECK_URL}/project/{RUNDECK_PROJECT}/job/show/{job_id}",
        status_code=303
    )
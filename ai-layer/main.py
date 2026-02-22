from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# MOCK Jira fetch
@app.post("/fetch-jira", response_class=HTMLResponse)
async def fetch_jira(request: Request, jira_key: str = Form(...)):

    # Fake Jira data
    mock_description = f"Release version 2.1.0 for issue {jira_key} to QA environment."

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "prefill_prompt": mock_description,
            "jira_key": jira_key
        }
    )


@app.post("/generate", response_class=HTMLResponse)
async def generate(request: Request, prompt: str = Form(...)):

    preview = {
        "name": "AI Generated Job",
        "description": prompt,
        "steps": [
            {"description": "Create directory", "command": "mkdir -p /tmp/test"},
            {"description": "Echo message", "command": "echo Hello World"},
            {"description": "List files", "command": "ls -l"}
        ]
    }

    return templates.TemplateResponse(
        "preview.html",
        {"request": request, "preview": preview}
    )
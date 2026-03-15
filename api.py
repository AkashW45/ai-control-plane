from fastapi import FastAPI
from services.jira import get_ticket
from services.llm import analyze_ticket
from services.rundeck_executor import RundeckExecutor

app = FastAPI()

executor = RundeckExecutor()


@app.post("/generate-runbook")
def generate_runbook(issue_key: str):

    ticket = get_ticket(issue_key)

    user_prompt = f"""
Create an execution runbook for this Jira ticket.

Summary: {ticket['summary']}
Description: {ticket['description']}
Priority: {ticket['priority']}
"""

    plan = analyze_ticket(ticket, user_prompt)

    return {
        "ticket": ticket,
        "plan": plan
    }


@app.post("/execute-runbook")
def execute_runbook(ticket: dict, plan: dict):

    execution = executor.run(
        ticket,
        plan,
        options={
            "environment": "QA",
            "version": ticket["fixVersion"],
            "dry_run": "false"
        },
        context={}
    )

    execution_id = execution["id"]
    execution_url = executor.get_execution_url(execution_id)

    return {
        "execution_id": execution_id,
        "execution_url": execution_url
    }
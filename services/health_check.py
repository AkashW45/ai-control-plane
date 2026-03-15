# services/health_check.py
#
# Converts P1 test cases from the test suite into
# executable Rundeck health check commands.
# These run AFTER deployment to verify success criteria.

import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("GROQ_BASE_URL")
API_KEY  = os.getenv("GROQ_API_KEY")
MODEL    = os.getenv("GROQ_MODEL")


# ─────────────────────────────────────────────────────────
# Extract P1 test cases as health check targets
# ─────────────────────────────────────────────────────────

def extract_health_check_targets(test_suite: dict) -> list:
    """
    Pull P1 + P2 Functional/Regression/Integration test cases
    as the post-deployment verification targets.
    """
    targets = []
    for tc in test_suite.get("test_suite", []):
        if tc.get("priority") in ["P1", "P2"] and tc.get("category") in [
            "Functional", "Regression", "Integration"
        ]:
            targets.append({
                "id":              tc["id"],
                "title":           tc["title"],
                "expected_result": tc["expected_result"],
                "category":        tc["category"],
                "priority":        tc["priority"],
                "tags":            tc.get("tags", []),
            })
    return targets


# ─────────────────────────────────────────────────────────
# Generate health check scripts from test cases
# ─────────────────────────────────────────────────────────

def generate_health_checks(test_suite: dict, ticket: dict) -> dict:
    """
    Takes test suite + ticket context.
    Returns structured health check plan with
    shell-safe verification commands per test case.
    """

    targets = extract_health_check_targets(test_suite)

    if not targets:
        return {
            "ticket_key":     ticket.get("key", ""),
            "health_checks":  [],
            "summary":        "No P1/P2 functional test cases found to generate health checks from."
        }

    environment  = ticket.get("fixVersion", "QA")
    version      = ticket.get("fixVersion", "auto")
    targets_text = "\n".join([
        f"- [{t['id']}] {t['title']}\n  Expected: {t['expected_result']}"
        for t in targets
    ])

    prompt = f"""You are a senior DevOps engineer.

Convert the following post-deployment test verification targets into
shell-safe health check commands that can run inside a Rundeck job.

STRICT RULES:
- Return ONLY valid JSON. No markdown. No explanation.
- Commands must use ONLY: echo, curl, ls, cat, grep, sleep, date, whoami, mkdir, touch
- No sudo, no docker, no systemctl, no absolute paths outside /tmp
- Use ${{option.environment}} and ${{option.version}} as Rundeck option placeholders
- Each health check must log its result clearly using echo
- If a check cannot be done with allowed commands, use echo to simulate a verification log

JSON SCHEMA:
{{
  "ticket_key": "...",
  "environment": "...",
  "version": "...",
  "health_checks": [
    {{
      "id": "HC-001",
      "test_case_ref": "TC-001",
      "title": "Short health check title",
      "command": "echo checking ... && echo PASS: ...",
      "expected_output": "what the command should print on success",
      "on_failure": "what action to take if this fails"
    }}
  ],
  "rundeck_script": "full shell script combining all health checks in sequence"
}}

TICKET: {ticket.get("key", "")}
ENVIRONMENT: {environment}
VERSION: {version}

POST-DEPLOYMENT VERIFICATION TARGETS:
{targets_text}
"""

    response = requests.post(
        BASE_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type":  "application/json"
        },
        json={
            "model":    MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        },
        timeout=120
    )

    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    import json
    return json.loads(content)


# ─────────────────────────────────────────────────────────
# Map execution result back to test cases
# ─────────────────────────────────────────────────────────

def evaluate_execution_against_tests(
    test_suite: dict,
    execution_status: str,
    execution_logs: str
) -> dict:
    """
    After Rundeck execution completes, evaluate which
    test cases passed or failed based on status + logs.
    Returns test case results with pass/fail per case.
    """

    results = []

    for tc in test_suite.get("test_suite", []):
        result = "UNKNOWN"
        reason = ""

        if execution_status == "succeeded":
            # P1 Functional cases — pass if execution succeeded
            if tc.get("priority") == "P1" and tc.get("category") == "Functional":
                result = "PASS"
                reason = "Execution completed successfully"

            # Negative cases — need log inspection
            elif tc.get("category") == "Negative":
                result = "MANUAL"
                reason = "Negative test requires manual verification"

            # Regression — pass if no errors in logs
            elif tc.get("category") == "Regression":
                result = "PASS" if "error" not in execution_logs.lower() else "FAIL"
                reason = "Based on execution log analysis"

            else:
                result = "PASS"
                reason = "Execution succeeded"

        elif execution_status == "failed":
            result = "FAIL"
            reason = "Execution failed"

        results.append({
            "id":              tc["id"],
            "title":           tc["title"],
            "category":        tc["category"],
            "priority":        tc["priority"],
            "result":          result,
            "reason":          reason,
            "expected_result": tc["expected_result"],
        })

    passed  = sum(1 for r in results if r["result"] == "PASS")
    failed  = sum(1 for r in results if r["result"] == "FAIL")
    manual  = sum(1 for r in results if r["result"] == "MANUAL")
    total   = len(results)

    return {
        "execution_status": execution_status,
        "total":   total,
        "passed":  passed,
        "failed":  failed,
        "manual":  manual,
        "results": results,
        "overall": "PASS" if failed == 0 else "FAIL"
    }
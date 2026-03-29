import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("GROQ_BASE_URL")
API_KEY  = os.getenv("GROQ_API_KEY")
MODEL    = os.getenv("GROQ_MODEL")


def build_execution_brief(ticket: dict) -> str:
    return f"Deploy version {ticket.get('fixVersion','')} related to:\n{ticket.get('summary','')}\n\nDetails:\n{ticket.get('description','')}\n\nPriority: {ticket.get('priority','')}".strip()


def detect_ticket_groups(tickets_context: list) -> list:
    if not tickets_context or len(tickets_context) < 2:
        return []

    summaries = []
    for t in tickets_context:
        summaries.append({
            "key":         t.get("key", ""),
            "summary":     t.get("summary", ""),
            "issue_type":  t.get("issue_type", ""),
            "description": (t.get("description", "") or "")[:200],
            "labels":      t.get("labels", []),
            "components":  t.get("components", []),
            "priority":    t.get("priority", ""),
            "fix_version": t.get("fixVersion", ""),
            "linked_to":   [l.get("key","") for l in (t.get("linked_tickets") or [])[:3]],
            "sprint":      t.get("sprint", {}).get("name", "") if isinstance(t.get("sprint"), dict) else "",
        })

    prompt = f"""You are a DevOps engineer planning a sprint deployment runbook.
Group these Jira tickets by their nature of work.

Grouping criteria (use ALL available signals):
1. Issue type (Bug=bugfix, Story/Epic=feature, Task=migration/deployment/testing)
2. Summary keywords (migrate/schema/db → migration, fix/bug/error → bugfix, deploy/release/qa → deployment, implement/add/new → feature)
3. Labels and components (shared labels/components = likely same group)
4. Linked tickets (linked tickets often belong together)
5. Description content (what the ticket actually does)
6. Fix version (same version = may be related)

Group types: migration | bugfix | feature | deployment | testing

Return ONLY a valid JSON array. No markdown.

SCHEMA:
[
  {{
    "name": "Descriptive group name based on actual work",
    "type": "migration|bugfix|feature|deployment|testing",
    "tickets": ["DEV-XXX", "DEV-YYY"],
    "reason": "Specific reason why these tickets are grouped — what they have in common"
  }}
]

Rules:
- Every ticket must appear in exactly one group
- Max 4 groups, min 1 group
- Tickets with similar purpose/domain/labels should be in same group
- Single-ticket groups are fine if the work type is clearly different from all others
- Group name should reflect the actual work, not just the type

TICKETS WITH FULL CONTEXT:
{json.dumps(summaries, indent=2)}
"""

    r = requests.post(BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
        timeout=60)
    if not r.ok:
        print("Groq status:", r.status_code)
        print("Groq body:", r.text[:2000])
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"): content = content[4:]
    return json.loads(content.strip())


def analyze_ticket(ticket: dict, user_prompt: str,
                   confluence_context: str = "",
                   ticket_groups: list = None) -> dict:

    groups_instruction = ""
    if ticket_groups:
        groups_instruction = "\n\nTICKET GROUPS — each group MUST get its own section in the runbook:\n"
        for g in ticket_groups:
            groups_instruction += f"\nGroup: {g['name']} | Type: {g['type']} | Tickets: {', '.join(g['tickets'])}"
            groups_instruction += f"\n  → This group needs specific pre-checks, steps, validation and rollback for its work type"

    confluence_section = f"\n\nCONFLUENCE DOCUMENTATION (use for context):\n{confluence_context}" if confluence_context else ""

    groups_schema = ""
    if ticket_groups:
        groups_schema = """,
  "groups": [
    {
      "name": "Group name e.g. DB Migration",
      "type": "migration|bugfix|feature|deployment",
      "tickets": ["DEV-XXX"],
      "pre_checks": ["Specific pre-check for THIS group's work type"],
      "steps": [{"description": "Step title", "commands": ["command1", "command2"]}],
      "validation": ["Specific validation for THIS group"],
      "rollback": "Concrete rollback steps specific to this group's changes"
    }
  ]"""

    prompt = f"""You are a senior DevOps engineer writing a professional operational runbook.

This is ONE runbook covering multiple tickets in a sprint. It has:
- Global sections (apply to entire deployment)
- Group sections (specific to each ticket group's work type)

Return ONLY valid JSON. No markdown fences.

JSON SCHEMA:
{{
  "summary": "One paragraph describing ALL tickets and what this deployment achieves",
  "probable_cause": "Why all these changes are needed together in this sprint",
  "pre_checks": [
    "Global pre-check that applies before any group runs"
  ],
  "steps": [
    {{
      "description": "Global step title",
      "commands": ["command1", "command2", "command3"]
    }}
  ]{groups_schema},
  "validation": ["Global validation after all groups complete"],
  "escalation": "Specific person/team, contact method, and action to take if deployment fails",
  "rollback": "Global rollback procedure if the entire deployment needs to be reverted"
}}

IMPORTANT RULES:
- summary must mention all tickets and their purpose
- Global steps = high-level orchestration (4 steps minimum)
- Each group section = work-type-specific (migration needs DB backup check, bugfix needs reproduction check, etc.)
- Commands: /bin/sh compatible, allowed: echo, mkdir, touch, ls, date, whoami
- Use {{environment}} and {{version}} placeholders
- NO absolute paths, NO sudo, NO docker, NO systemctl
- Every step must echo its progress
- escalation must be concrete (not "contact team")
- rollback must be concrete steps (not "revert changes")
- Each group's rollback must be DIFFERENT and specific to that group's work type

DEPLOYMENT CONTEXT:
{user_prompt}{groups_instruction}{confluence_section}
"""

    r = requests.post(BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
        timeout=120)
    r.raise_for_status()

    content = r.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"): content = content[4:]
    return json.loads(content.strip())





def generate_go_no_go(plan: dict, test_cases: dict, sprint_summaries: list = None, runtime_metrics: dict = None) -> dict:
    groups     = plan.get("groups", [])
    all_tests  = test_cases.get("test_suite", [])
    p1_cases   = [t for t in all_tests if t.get("priority") == "P1"]
    p2_cases   = [t for t in all_tests if t.get("priority") == "P2"]
    qa_notes   = test_cases.get("qa_notes", "")
    risk_level = test_cases.get("risk_level", "Medium")
    total      = len(all_tests)
    p1_count   = len(p1_cases)
    p2_count   = len(p2_cases)
    neg_count  = len([t for t in all_tests if t.get("category") == "Negative"])
    has_migration = any(g.get("type") == "migration" for g in groups)
    has_bugfix    = any(g.get("type") == "bugfix"    for g in groups)

    groups_lines = []
    for g in groups:
        groups_lines.append("  - " + g["name"] + " (" + g["type"] + ") tickets: " + ", ".join(g.get("tickets",[])))
        groups_lines.append("    Rollback: " + g.get("rollback","NOT DEFINED"))
    groups_text = chr(10).join(groups_lines)

    p1_lines = []
    for t in p1_cases:
        p1_lines.append("  [" + t["id"] + "] " + t["title"] + " -> MUST PASS: " + t["expected_result"])
    p1_text = chr(10).join(p1_lines)

    sprint_text = ""
    if sprint_summaries:
        sprint_text = "Sprint: " + ", ".join([s["key"] + " (" + s.get("issue_type","Task") + ")" for s in sprint_summaries])

    prompt = (
        "You are a senior release manager making a Go/No-Go deployment decision.\n\n"
        "Return ONLY valid JSON. No markdown.\n\n"
        "{\n"
        '  "verdict": "GO or PAUSE or ROLLBACK",\n'
        '  "confidence": 0.0,\n'
        '  "summary": "one sentence verdict explanation",\n'
        '  "metrics_evaluated": {\n'
        '    "total_test_cases": ' + str(total) + ',\n'
        '    "p1_cases": ' + str(p1_count) + ',\n'
        '    "p2_cases": ' + str(p2_count) + ',\n'
        '    "negative_cases": ' + str(neg_count) + ',\n'
        '    "risk_level": "' + risk_level + '",\n'
        '    "groups_count": ' + str(len(groups)) + ',\n'
        '    "has_migration_group": ' + str(has_migration).lower() + ',\n'
        '    "has_bugfix_group": ' + str(has_bugfix).lower() + ',\n'
        '    "pods_ready_percent": "evaluate: 100% expected for GO",\n'
        '    "error_rate_percent": "evaluate: <1% for GO, 1-3% for PAUSE, >3% ROLLBACK",\n'
        '    "latency_p95_ms": "evaluate: <500ms for GO, 500-800ms for PAUSE, >800ms ROLLBACK"\n'
        "  },\n"
        '  "release_constraints_checked": ["Constraint: PASS or FAIL"],\n'
        '  "reasons": ["specific reason referencing actual ticket or group"],\n'
        '  "risks": ["specific risk identified"],\n'
        '  "conditions": ["what must be resolved before proceeding — empty array if GO"],\n'
        '  "deployment_sequence": ["recommended execution order for groups"]\n'
        "}\n\n"
        "VERDICT RULES:\n"
        "- GO: P1 cases well-defined, rollback exists for every group, no critical blockers\n"
        "- PAUSE: Vague P1 results, missing rollback, unresolved QA dependencies\n"
        "- ROLLBACK: No P1 cases, no rollback defined, migration has no backup\n\n"
        "RELEASE CONSTRAINTS TO CHECK:\n"
        "1. Every group must have a defined rollback procedure\n"
        "2. Migration groups must run before deployment groups\n"
        "3. P1 cases must have specific measurable expected results\n"
        "4. QA notes must not have unresolved blocking dependencies\n"
        "5. High or Critical risk requires at least 5 P1 cases\n\n"
        "METRICS:\n"
        "  Test Coverage: total=" + str(total) + " p1=" + str(p1_count) +
        " p2=" + str(p2_count) + " negative=" + str(neg_count) + " risk=" + risk_level + "\n"
        "  Ticket Groups: count=" + str(len(groups)) + " migration=" + str(has_migration) +
        " bugfix=" + str(has_bugfix) + "\n"
        "  Runtime Health Metrics:\n"
        "    pods_ready_percent=" + str((runtime_metrics or {}).get("pods_ready_percent", "not provided")) +
        " (threshold: 100% = GO, <100% = PAUSE)\n"
        "    error_rate_percent=" + str((runtime_metrics or {}).get("error_rate_percent", "not provided")) +
        " (threshold: <1% = GO, 1-3% = PAUSE, >3% = ROLLBACK)\n"
        "    latency_p95_ms=" + str((runtime_metrics or {}).get("latency_p95_ms", "not provided")) +
        " (threshold: <500ms = GO, 500-800ms = PAUSE, >800ms = ROLLBACK)\n\n"
        "RUNBOOK SUMMARY: " + plan.get("summary","") + "\n"
        "ESCALATION: " + plan.get("escalation","") + "\n\n"
        "GROUPS WITH ROLLBACKS:\n" + groups_text + "\n\n"
        + sprint_text + "\n\n"
        "P1 TEST CASES:\n" + p1_text + "\n\n"
        "QA NOTES:\n" + qa_notes
    )

    r = requests.post(BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
        timeout=60)
    r.raise_for_status()

    txt = r.json()["choices"][0]["message"]["content"].strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.startswith("json"): txt = txt[4:]
    return json.loads(txt.strip())
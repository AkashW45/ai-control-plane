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
# services/test_case_generator.py
#
# Generates structured functional test cases from full Jira context.
# Uses whatever the developer wrote — no assumptions, no fabrication.
# Test case quality scales naturally with ticket quality.

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("GROQ_BASE_URL")
API_KEY  = os.getenv("GROQ_API_KEY")
MODEL    = os.getenv("GROQ_MODEL")


# ─────────────────────────────────────────────────────────
# Context → Structured Prompt Block
# Every field that has content gets included.
# Empty fields are silently skipped — no noise.
# ─────────────────────────────────────────────────────────

def format_context_for_prompt(ctx: dict) -> str:
    lines = []

    # ── Ticket identity ───────────────────────────────────
    lines.append(f"TICKET:    {ctx['key']}")
    lines.append(f"TYPE:      {ctx['issue_type']}")
    lines.append(f"PRIORITY:  {ctx['priority']}")
    lines.append(f"STATUS:    {ctx['status']}")
    lines.append(f"PROJECT:   {ctx['project']}")

    if ctx.get("assignee") and ctx["assignee"] != "Unassigned":
        lines.append(f"ASSIGNEE:  {ctx['assignee']}")
    if ctx.get("reporter"):
        lines.append(f"REPORTER:  {ctx['reporter']}")
    if ctx.get("team"):
        lines.append(f"TEAM:      {ctx['team']}")
    if ctx.get("story_points"):
        lines.append(f"STORY POINTS: {ctx['story_points']}")
    if ctx.get("flagged"):
        lines.append("⚠️  FLAGGED: This ticket is flagged — treat as elevated risk")

    # ── Versioning ────────────────────────────────────────
    if ctx.get("fix_versions"):
        lines.append(f"FIX VERSION:     {', '.join(ctx['fix_versions'])}")
    if ctx.get("affects_versions"):
        lines.append(f"AFFECTS VERSION: {', '.join(ctx['affects_versions'])}")

    # ── Classification ────────────────────────────────────
    if ctx.get("labels"):
        lines.append(f"LABELS:     {', '.join(ctx['labels'])}")
    if ctx.get("components"):
        lines.append(f"COMPONENTS: {', '.join(ctx['components'])}")

    # ── Environment (critical for bug reports) ────────────
    if ctx.get("environment"):
        lines.append(f"\nENVIRONMENT (OS/Browser/Version):\n{ctx['environment']}")

    # ── Summary ───────────────────────────────────────────
    lines.append(f"\nSUMMARY:\n{ctx['summary']}")

    # ── Description — primary context source ─────────────
    # Contains whatever developer wrote:
    # user story, acceptance criteria, reproduction steps,
    # technical notes, figma links, API contracts, etc.
    if ctx.get("description"):
        lines.append(f"\nDESCRIPTION:\n{ctx['description']}")

    # ── Goals ─────────────────────────────────────────────
    if ctx.get("goals"):
        lines.append("\nGOALS:")
        for g in ctx["goals"]:
            lines.append(f"  - {g}")

    # ── Sprint context ────────────────────────────────────
    sprint = ctx.get("sprint", {})
    if sprint.get("name"):
        lines.append(f"\nSPRINT:  {sprint['name']}  [{sprint.get('state', '').upper()}]")
        if sprint.get("goal"):
            lines.append(f"SPRINT GOAL: {sprint['goal']}")
        if sprint.get("end_date"):
            lines.append(f"SPRINT END:  {sprint['end_date']}")

    # ── Parent ────────────────────────────────────────────
    parent = ctx.get("parent", {})
    if parent.get("summary"):
        lines.append(
            f"\nPARENT {parent.get('type','').upper()}: "
            f"[{parent['key']}] {parent['summary']} ({parent.get('status', '')})"
        )

    # ── Linked tickets ────────────────────────────────────
    linked = ctx.get("linked_tickets", [])
    if linked:
        lines.append("\nLINKED TICKETS:")
        for lt in linked:
            lines.append(
                f"  [{lt['key']}] {lt['summary']} "
                f"— {lt['type']} | {lt['status']} | {lt['link_type']}"
            )

    # ── Subtasks ──────────────────────────────────────────
    subtasks = ctx.get("subtasks", [])
    if subtasks:
        lines.append("\nSUBTASKS:")
        for s in subtasks:
            lines.append(f"  [{s['key']}] {s['summary']} ({s['status']})")

    # ── Attachments — signal only, not content ────────────
    attachments = ctx.get("attachments", [])
    if attachments:
        lines.append("\nATTACHMENTS (evidence provided by developer):")
        for a in attachments:
            lines.append(f"  - {a['filename']} ({a['mimeType']}, {a['size']} bytes) by {a['author']}")

    # ── Comments — full team discussion ───────────────────
    comments = ctx.get("comments", [])
    if comments:
        lines.append("\nTEAM DISCUSSION:")
        for c in comments:
            # Include full comment body — developer may have added AC in comments
            lines.append(f"\n  [{c['author']}] ({c['date'][:10]}):")
            lines.append(f"  {c['body']}")

    # ── Changelog — what changed and when ─────────────────
    changes = ctx.get("changelog", [])
    if changes:
        lines.append("\nCHANGE HISTORY:")
        for ch in changes[:6]:
            lines.append(
                f"  {ch['author']} changed [{ch['field']}]: "
                f"{ch['from'] or 'empty'} → {ch['to'] or 'empty'}"
            )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# Issue-type aware instructions
# Bug reports need reproduction steps
# Stories need AC coverage
# Spikes need investigation checkpoints
# ─────────────────────────────────────────────────────────

def get_type_specific_rules(issue_type: str) -> str:
    issue_type = (issue_type or "").lower()

    if issue_type == "bug":
        return """
ISSUE TYPE IS BUG — apply these additional rules:
- Include test cases that reproduce the exact bug using the steps in description
- Include a test case verifying the fix does not regress adjacent functionality
- Include negative cases: what happens with invalid/edge inputs near the bug area
- If environment info is provided, test cases must reference that specific environment
- P1 must include: reproduce bug, verify fix, verify no regression
"""
    elif issue_type in ("story", "user story"):
        return """
ISSUE TYPE IS USER STORY — apply these additional rules:
- Map every acceptance criteria point to at least one test case
- Include the happy path (user completes the intended action successfully)
- Include at least 2 negative paths (user does something wrong or unexpected)
- Include boundary/edge cases for any numeric or text input fields mentioned
- Test cases should follow the "As a user I..." perspective where relevant
"""
    elif issue_type == "epic":
        return """
ISSUE TYPE IS EPIC — apply these additional rules:
- Generate high-level integration test cases covering the epic scope
- Focus on cross-functional flows described in the epic description
- Include test cases for each major capability mentioned
- Include end-to-end scenario test cases
"""
    elif issue_type in ("spike", "research"):
        return """
ISSUE TYPE IS SPIKE — apply these additional rules:
- Generate investigation checkpoints as test cases
- Each test case should verify a specific assumption being investigated
- Include a test case confirming the spike outcome is documented
"""
    else:
        return """
ISSUE TYPE IS TASK — apply these additional rules:
- Focus on functional verification of the deliverable
- Include at least one test case per stated requirement or dependency
- Include integration test if external systems are mentioned
"""


# ─────────────────────────────────────────────────────────
# Master Prompt Builder
# ─────────────────────────────────────────────────────────

def build_prompt(context_block: str, issue_type: str) -> str:
    type_rules = get_type_specific_rules(issue_type)

    return f"""You are a senior QA engineer at a financial institution.

Your job is to generate precise, professional, domain-aware functional test cases
from the Jira ticket context provided below.

Use ONLY what is in the context. Do not invent requirements.
If context is sparse, generate fewer but accurate test cases.
If context is rich, generate comprehensive coverage.

RETURN ONLY valid JSON. No markdown. No explanation. No code fences.

JSON SCHEMA:
{{
  "ticket_key": "...",
  "summary": "...",
  "issue_type": "...",
  "risk_level": "Low | Medium | High | Critical",
  "test_suite": [
    {{
      "id": "TC-001",
      "category": "Functional | Edge Case | Negative | Integration | Regression | Reproduction",
      "title": "Short, specific test title",
      "preconditions": "Exact state required before test runs",
      "steps": [
        "Step 1: specific action",
        "Step 2: specific action",
        "Step 3: verify specific outcome"
      ],
      "expected_result": "Specific, measurable, verifiable outcome",
      "priority": "P1 | P2 | P3",
      "tags": ["fix-version", "component", "label", "environment"]
    }}
  ],
  "coverage_summary": {{
    "total_cases": 0,
    "functional": 0,
    "edge_cases": 0,
    "negative": 0,
    "integration": 0,
    "regression": 0,
    "reproduction": 0
  }},
  "qa_notes": "Key risks, dependencies, environment needs, and anything QA must know before testing"
}}

UNIVERSAL QUALITY RULES:
- Generate between 6 and 15 test cases based on context richness
- Steps must be concrete actions — not vague like "verify the system works"
- Expected results must be specific and measurable — not "it should work"
- At least 2 Negative test cases always required
- At least 1 Regression test case always required
- P1 = must pass before any release, P2 = important, P3 = nice to have
- Tags must include fix version, labels, and issue type from the context
- If attachments are mentioned, reference them in relevant preconditions
- If comments contain requirements or decisions, honour them in test cases
- If linked tickets exist, include at least 1 Integration test case

{type_rules}

JIRA CONTEXT:
{context_block}
"""


# ─────────────────────────────────────────────────────────
# Main Generator — called from Streamlit
# ─────────────────────────────────────────────────────────

def generate_test_cases(jira_context: dict) -> dict:
    """
    Input:  full context dict from jira_context.build_full_ticket_context()
    Output: structured test suite dict ready for Streamlit display
    """

    context_block = format_context_for_prompt(jira_context)
    issue_type    = jira_context.get("issue_type", "Task")
    prompt        = build_prompt(context_block, issue_type)

    response = requests.post(
        BASE_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type":  "application/json"
        },
        json={
            "model":    MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        },
        timeout=120
    )

    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if model wraps output
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    return json.loads(content)
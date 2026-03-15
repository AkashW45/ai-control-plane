# services/jira_context.py
#
# Pulls every possible context from a Jira ticket for LLM test case generation.
# Confirmed field map — wissen-team-tqg48t7b.atlassian.net:
#
#   summary           → ticket title
#   description       → ADF doc (contains user story, AC, technical notes, links)
#   issuetype         → Task / Bug / Story / Epic / Spike
#   status            → To Do / In Progress / Done etc
#   priority          → High / Medium / Low
#   labels            → string array
#   components        → component array
#   fixVersions       → version array
#   environment       → OS/browser/version context (critical for bug reports)
#   issuelinks        → blocked by / relates to / duplicates
#   subtasks          → child tasks
#   parent            → parent epic or story
#   comment           → all team discussion
#   attachment        → file metadata (name, size — content not fetched)
#   changelog         → full field change history
#   customfield_10020 → Sprint (name, goal, state, dates)
#   customfield_10016 → Story point estimate
#   customfield_10015 → Start date
#   customfield_10001 → Team
#   customfield_10021 → Flagged
#   customfield_10028 → Goals

import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE = os.getenv("JIRA_BASE_URL")
EMAIL     = os.getenv("JIRA_EMAIL")
TOKEN     = os.getenv("JIRA_API_TOKEN")

AUTH    = (EMAIL, TOKEN)
HEADERS = {"Accept": "application/json"}

FIELDS_TO_FETCH = ",".join([
    "summary",
    "description",
    "issuetype",
    "status",
    "priority",
    "project",
    "assignee",
    "reporter",
    "creator",
    "labels",
    "components",
    "fixVersions",
    "versions",           # affects versions
    "duedate",
    "created",
    "updated",
    "environment",        # OS/browser/version — key for bug reports
    "issuelinks",         # blocked by, relates to, duplicates
    "subtasks",
    "parent",
    "comment",
    "attachment",         # file metadata — name + size
    "customfield_10020",  # Sprint
    "customfield_10016",  # Story point estimate
    "customfield_10015",  # Start date
    "customfield_10001",  # Team
    "customfield_10021",  # Flagged
    "customfield_10028",  # Goals
])


# ─────────────────────────────────────────────────────────
# HTTP helper
# ─────────────────────────────────────────────────────────

def _get(url: str) -> dict:
    r = requests.get(url, auth=AUTH, headers=HEADERS)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# ADF Text Extractor
# Handles full Atlassian Document Format recursively
# Preserves list structure, headings, and inline text
# ─────────────────────────────────────────────────────────

def extract_adf_text(node, depth=0) -> str:
    if not node:
        return ""

    parts = []

    if isinstance(node, dict):
        node_type = node.get("type", "")

        if node_type == "text":
            text = node.get("text", "")
            # Preserve marks (bold, italic) as plain text
            parts.append(text)

        elif node_type == "hardBreak":
            parts.append("\n")

        elif node_type in ("paragraph", "heading"):
            children = "".join(extract_adf_text(c) for c in node.get("content", []))
            parts.append(children.strip())

        elif node_type == "bulletList":
            for item in node.get("content", []):
                item_text = extract_adf_text(item).strip()
                if item_text:
                    parts.append(f"• {item_text}")

        elif node_type == "orderedList":
            for i, item in enumerate(node.get("content", []), 1):
                item_text = extract_adf_text(item).strip()
                if item_text:
                    parts.append(f"{i}. {item_text}")

        elif node_type == "listItem":
            children = " ".join(
                extract_adf_text(c).strip()
                for c in node.get("content", [])
            )
            parts.append(children)

        elif node_type == "blockquote":
            children = extract_adf_text({"content": node.get("content", [])})
            parts.append(f"> {children.strip()}")

        elif node_type == "codeBlock":
            children = "".join(extract_adf_text(c) for c in node.get("content", []))
            parts.append(f"[CODE: {children.strip()}]")

        elif node_type == "inlineCard":
            url = node.get("attrs", {}).get("url", "")
            if url:
                parts.append(f"[link: {url}]")

        elif node_type == "mention":
            display = node.get("attrs", {}).get("text", "")
            if display:
                parts.append(display)

        else:
            # Fallback — recurse into any content children
            for child in node.get("content", []):
                parts.append(extract_adf_text(child, depth + 1))

    elif isinstance(node, list):
        for item in node:
            parts.append(extract_adf_text(item, depth))

    return "\n".join(p for p in parts if p)


# ─────────────────────────────────────────────────────────
# Sprint Extractor — customfield_10020
# ─────────────────────────────────────────────────────────

def extract_sprint(fields: dict) -> dict:
    raw = fields.get("customfield_10020")
    if not raw:
        return {}
    sprint = raw[-1] if isinstance(raw, list) else raw
    return {
        "name":       sprint.get("name", ""),
        "goal":       sprint.get("goal", ""),
        "state":      sprint.get("state", ""),
        "start_date": sprint.get("startDate", ""),
        "end_date":   sprint.get("endDate", ""),
    }


# ─────────────────────────────────────────────────────────
# Goals Extractor — customfield_10028
# ─────────────────────────────────────────────────────────

def extract_goals(fields: dict) -> list:
    raw = fields.get("customfield_10028")
    if not raw or not isinstance(raw, list):
        return []
    return [g.get("name") or g.get("title") or str(g) for g in raw if g]


# ─────────────────────────────────────────────────────────
# Linked Tickets — issuelinks
# Captures: blocked by, relates to, duplicates, is cloned by
# ─────────────────────────────────────────────────────────

def extract_linked_tickets(fields: dict) -> list:
    result = []
    for link in fields.get("issuelinks", []):
        link_type = link.get("type", {}).get("name", "")
        for direction in ["inwardIssue", "outwardIssue"]:
            issue = link.get(direction)
            if issue:
                result.append({
                    "key":       issue.get("key", ""),
                    "summary":   issue.get("fields", {}).get("summary", ""),
                    "status":    issue.get("fields", {}).get("status", {}).get("name", ""),
                    "type":      issue.get("fields", {}).get("issuetype", {}).get("name", ""),
                    "link_type": link_type,
                })
    return result


# ─────────────────────────────────────────────────────────
# Subtasks
# ─────────────────────────────────────────────────────────

def extract_subtasks(fields: dict) -> list:
    return [
        {
            "key":     s.get("key", ""),
            "summary": s.get("fields", {}).get("summary", ""),
            "status":  s.get("fields", {}).get("status", {}).get("name", ""),
        }
        for s in fields.get("subtasks", [])
    ]


# ─────────────────────────────────────────────────────────
# Parent — next-gen project parent field
# ─────────────────────────────────────────────────────────

def extract_parent(fields: dict) -> dict:
    parent = fields.get("parent")
    if not parent:
        return {}
    pf = parent.get("fields", {})
    return {
        "key":     parent.get("key", ""),
        "summary": pf.get("summary", ""),
        "type":    pf.get("issuetype", {}).get("name", ""),
        "status":  pf.get("status", {}).get("name", ""),
    }


# ─────────────────────────────────────────────────────────
# Comments — full discussion thread
# Extracts all comments with author + body
# ─────────────────────────────────────────────────────────

def extract_comments(fields: dict) -> list:
    comments = fields.get("comment", {}).get("comments", [])
    result = []
    for c in comments:
        body   = extract_adf_text(c.get("body"))
        author = c.get("author", {}).get("displayName", "Unknown")
        date   = c.get("created", "")
        if body.strip():
            result.append({
                "author": author,
                "date":   date,
                "body":   body.strip()
            })
    return result


# ─────────────────────────────────────────────────────────
# Attachments — file metadata only (not content)
# Useful as signal: "has logs", "has screenshots", "has design file"
# ─────────────────────────────────────────────────────────

def extract_attachments(fields: dict) -> list:
    result = []
    for a in fields.get("attachment", []):
        result.append({
            "filename": a.get("filename", ""),
            "size":     a.get("size", 0),
            "mimeType": a.get("mimeType", ""),
            "created":  a.get("created", ""),
            "author":   a.get("author", {}).get("displayName", ""),
        })
    return result


# ─────────────────────────────────────────────────────────
# Changelog — full field change history
# Shows version bumps, status transitions, priority changes
# ─────────────────────────────────────────────────────────

def extract_changelog(changelog: dict) -> list:
    events = []
    for history in changelog.get("histories", []):
        author = history.get("author", {}).get("displayName", "")
        date   = history.get("created", "")
        for item in history.get("items", []):
            events.append({
                "author": author,
                "date":   date,
                "field":  item.get("field", ""),
                "from":   item.get("fromString", ""),
                "to":     item.get("toString", ""),
            })
    return events


# ─────────────────────────────────────────────────────────
# MASTER CONTEXT BUILDER
# Single entry point — returns everything available
# ─────────────────────────────────────────────────────────

def build_full_ticket_context(ticket_key: str) -> dict:
    """
    Pulls every available field from a Jira ticket.
    Whatever the developer wrote — we capture it.
    Nothing is assumed or fabricated.
    Quality of test cases scales with quality of ticket.
    """

    url = (
        f"{JIRA_BASE}/rest/api/3/issue/{ticket_key}"
        f"?expand=names,changelog"
        f"&fields={FIELDS_TO_FETCH}"
    )

    data      = _get(url)
    fields    = data.get("fields", {})
    changelog = data.get("changelog", {})

    # ── Core identity ─────────────────────────────────────
    summary    = fields.get("summary", "")
    issue_type = fields.get("issuetype", {}).get("name", "")
    project    = fields.get("project", {}).get("key", "")
    status     = fields.get("status", {}).get("name", "")
    priority   = fields.get("priority", {}).get("name", "Medium")

    # ── Content — whatever developer wrote ────────────────
    # Description contains: user story, AC, technical notes,
    # reproduction steps, external links — all as free text
    description = extract_adf_text(fields.get("description"))
    environment = fields.get("environment") or ""  # bug reports: OS/browser/version

    # ── Classification ────────────────────────────────────
    labels      = fields.get("labels", [])
    components  = [c.get("name", "") for c in fields.get("components", [])]
    fix_versions= [v.get("name", "") for v in fields.get("fixVersions", [])]
    affects_versions = [v.get("name", "") for v in fields.get("versions", [])]

    # ── People ────────────────────────────────────────────
    assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
    reporter = (fields.get("reporter") or {}).get("displayName", "")
    creator  = (fields.get("creator")  or {}).get("displayName", "")

    # ── Dates & estimates ─────────────────────────────────
    due_date     = fields.get("duedate", "")
    created      = fields.get("created", "")
    updated      = fields.get("updated", "")
    story_points = fields.get("customfield_10016")   # number or None
    start_date   = fields.get("customfield_10015", "")
    flagged      = bool(fields.get("customfield_10021"))

    # ── Team ──────────────────────────────────────────────
    team = ""
    raw_team = fields.get("customfield_10001")
    if isinstance(raw_team, dict):
        team = raw_team.get("name") or raw_team.get("title") or ""

    return {
        # Identity
        "key":        ticket_key,
        "summary":    summary,
        "issue_type": issue_type,
        "project":    project,
        "status":     status,
        "priority":   priority,

        # Everything developer wrote
        "description":       description,
        "environment":       environment,
        "labels":            labels,
        "components":        components,
        "fix_versions":      fix_versions,
        "affects_versions":  affects_versions,

        # Planning context
        "goals":        extract_goals(fields),
        "sprint":       extract_sprint(fields),
        "story_points": story_points,
        "start_date":   start_date,
        "due_date":     due_date,
        "flagged":      flagged,
        "team":         team,

        # People
        "assignee": assignee,
        "reporter": reporter,
        "creator":  creator,

        # Relationships — what this ticket connects to
        "parent":          extract_parent(fields),
        "linked_tickets":  extract_linked_tickets(fields),
        "subtasks":        extract_subtasks(fields),

        # Discussion & history
        "comments":    extract_comments(fields),
        "attachments": extract_attachments(fields),
        "changelog":   extract_changelog(changelog),

        # Timestamps
        "created": created,
        "updated": updated,
    }
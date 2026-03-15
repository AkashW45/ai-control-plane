# services/jira_search.py
#
# Smart multi-keyword search + relationship expander.
# Splits input into individual keywords, searches each,
# then expands every found ticket via all relationship types:
#   - Issue links (blocks, relates, duplicates)
#   - Same epic (parent)
#   - Same label
#   - Same fix version
#   - Same sprint
#   - Same component

import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE = os.getenv("JIRA_BASE_URL")
EMAIL     = os.getenv("JIRA_EMAIL")
TOKEN     = os.getenv("JIRA_API_TOKEN")

AUTH    = (EMAIL, TOKEN)
HEADERS = {"Accept": "application/json"}

SEARCH_FIELDS = [
    "summary", "issuetype", "status", "priority",
    "labels", "assignee", "fixVersions", "issuelinks",
    "customfield_10020", "parent", "components",
]

# Stop words — don't search these as individual keywords
STOP_WORDS = {
    "the","a","an","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could",
    "should","may","might","shall","can","need","dare","ought",
    "and","or","but","if","in","on","at","to","for","of","with",
    "by","from","up","about","into","through","during","before",
    "after","above","below","between","out","off","over","under",
    "again","then","once","here","there","when","where","why",
    "how","all","both","each","few","more","most","other","some",
    "such","no","not","only","same","so","than","too","very",
    "just","that","this","these","those","i","we","you","he",
    "she","it","they","what","which","who","whom","ticket","jira",
}


# ─────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────

def _post_search(jql: str, max_results: int = 30) -> list:
    """Run a JQL search via POST, return raw issue list."""
    url = f"{JIRA_BASE}/rest/api/3/search/jql"
    payload = {
        "jql":        jql,
        "maxResults": max_results,
        "fields":     SEARCH_FIELDS,
    }
    r = requests.post(
        url, auth=AUTH,
        headers={**HEADERS, "Content-Type": "application/json"},
        json=payload
    )
    if r.status_code != 200:
        return []
    return r.json().get("issues", [])


def _get_issue(key: str) -> dict:
    """Fetch a single issue by key."""
    url = f"{JIRA_BASE}/rest/api/3/issue/{key}"
    params = {"fields": ",".join(SEARCH_FIELDS)}
    r = requests.get(url, auth=AUTH, headers=HEADERS, params=params)
    if r.status_code != 200:
        return {}
    return r.json()


# ─────────────────────────────────────────────────────────
# Parse a raw issue into a ticket card
# ─────────────────────────────────────────────────────────

def _parse_ticket(issue: dict) -> dict:
    f = issue.get("fields", {})

    sprint_name = ""
    sprint_raw  = f.get("customfield_10020")
    if sprint_raw and isinstance(sprint_raw, list):
        sprint_name = sprint_raw[-1].get("name", "")

    version = ""
    if f.get("fixVersions"):
        version = f["fixVersions"][0].get("name", "")

    components = [c["name"] for c in f.get("components", [])]

    parent_key = ""
    if f.get("parent"):
        parent_key = f["parent"].get("key", "")

    links = []
    for lnk in f.get("issuelinks", []):
        if lnk.get("inwardIssue"):
            links.append({
                "key":       lnk["inwardIssue"]["key"],
                "summary":   lnk["inwardIssue"].get("fields", {}).get("summary", ""),
                "link_type": lnk["type"].get("inward", "relates to"),
                "direction": "inward",
            })
        if lnk.get("outwardIssue"):
            links.append({
                "key":       lnk["outwardIssue"]["key"],
                "summary":   lnk["outwardIssue"].get("fields", {}).get("summary", ""),
                "link_type": lnk["type"].get("outward", "relates to"),
                "direction": "outward",
            })

    return {
        "key":        issue["key"],
        "summary":    f.get("summary", ""),
        "issue_type": f.get("issuetype", {}).get("name", ""),
        "status":     f.get("status",   {}).get("name", ""),
        "priority":   f.get("priority", {}).get("name", "Medium"),
        "labels":     f.get("labels",   []),
        "assignee":   (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "version":    version,
        "sprint":     sprint_name,
        "components": components,
        "parent_key": parent_key,
        "raw_links":  links,
        "link_count": len(links),
    }


# ─────────────────────────────────────────────────────────
# Multi-keyword JQL builder
# ─────────────────────────────────────────────────────────

def _split_keywords(text: str) -> list:
    """
    Split input into meaningful individual keywords.
    "payment timeout migration" → ["payment", "timeout", "migration"]
    """
    words = text.lower().replace(",", " ").replace(";", " ").split()
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]


def _build_multi_keyword_jql(project: str, keywords: list, sprint: str = "") -> str:
    """
    Build JQL that matches ANY keyword in summary OR description.
    Each keyword is an OR clause so multi-word input finds multiple tickets.
    """
    if not keywords:
        clauses = [f"project = {project}"]
    else:
        kw_parts = []
        for kw in keywords:
            kw_parts.append(f'summary ~ "{kw}"')
            kw_parts.append(f'description ~ "{kw}"')
        kw_jql = " OR ".join(kw_parts)
        clauses = [f"project = {project}", f"({kw_jql})"]

    if sprint:
        clauses.append(f'sprint = "{sprint}"')

    return " AND ".join(clauses) + " ORDER BY priority ASC, created DESC"


# ─────────────────────────────────────────────────────────
# Relationship expander
# ─────────────────────────────────────────────────────────

def _expand_relationships(
    direct_tickets: list,
    project: str,
    seen_keys: set
) -> dict:
    """
    For each directly found ticket, discover all related tickets via:
    1. Issue links (blocks, relates, duplicates)
    2. Same parent/epic
    3. Same label
    4. Same fix version
    5. Same sprint
    6. Same component
    Returns dict of discovered tickets grouped by how they were found.
    """
    discovered = {}  # key → {ticket, found_via}

    for ticket in direct_tickets:
        key = ticket["key"]

        # ── 1. Issue links ─────────────────────────────
        for link in ticket.get("raw_links", []):
            lkey = link["key"]
            if lkey not in seen_keys and lkey not in discovered:
                issue = _get_issue(lkey)
                if issue:
                    t = _parse_ticket(issue)
                    discovered[lkey] = {
                        "ticket":   t,
                        "found_via": f"🔗 Link from {key} ({link['link_type']})"
                    }

        # ── 2. Same parent/epic ────────────────────────
        if ticket.get("parent_key"):
            pkey = ticket["parent_key"]
            if pkey not in seen_keys and pkey not in discovered:
                issue = _get_issue(pkey)
                if issue:
                    t = _parse_ticket(issue)
                    discovered[pkey] = {
                        "ticket":   t,
                        "found_via": f"👆 Parent epic of {key}"
                    }

            # Also find siblings — other tickets with same parent
            try:
                siblings = _post_search(
                    f'project = {project} AND "Epic Link" = {pkey}', 10
                )
                for s in siblings:
                    skey = s["key"]
                    if skey not in seen_keys and skey not in discovered and skey != key:
                        t = _parse_ticket(s)
                        discovered[skey] = {
                            "ticket":   t,
                            "found_via": f"👥 Same epic as {key} ({pkey})"
                        }
            except Exception:
                pass

        # ── 3. Same labels ────────────────────────────
        for label in ticket.get("labels", []):
            try:
                label_issues = _post_search(
                    f'project = {project} AND labels = "{label}"', 10
                )
                for li in label_issues:
                    lkey = li["key"]
                    if lkey not in seen_keys and lkey not in discovered and lkey != key:
                        t = _parse_ticket(li)
                        discovered[lkey] = {
                            "ticket":   t,
                            "found_via": f"🏷️ Same label '{label}' as {key}"
                        }
            except Exception:
                pass

        # ── 4. Same fix version ───────────────────────
        if ticket.get("version"):
            ver = ticket["version"]
            try:
                ver_issues = _post_search(
                    f'project = {project} AND fixVersion = "{ver}"', 10
                )
                for vi in ver_issues:
                    vkey = vi["key"]
                    if vkey not in seen_keys and vkey not in discovered and vkey != key:
                        t = _parse_ticket(vi)
                        if vkey not in discovered:
                            discovered[vkey] = {
                                "ticket":   t,
                                "found_via": f"📦 Same fix version '{ver}' as {key}"
                            }
            except Exception:
                pass

        # ── 5. Same sprint ────────────────────────────
        if ticket.get("sprint"):
            sprint_name = ticket["sprint"]
            try:
                sprint_issues = _post_search(
                    f'project = {project} AND sprint = "{sprint_name}"', 15
                )
                for si in sprint_issues:
                    skey = si["key"]
                    if skey not in seen_keys and skey not in discovered and skey != key:
                        t = _parse_ticket(si)
                        discovered[skey] = {
                            "ticket":   t,
                            "found_via": f"🏃 Same sprint '{sprint_name}' as {key}"
                        }
            except Exception:
                pass

        # ── 6. Same component ─────────────────────────
        for comp in ticket.get("components", []):
            try:
                comp_issues = _post_search(
                    f'project = {project} AND component = "{comp}"', 10
                )
                for ci in comp_issues:
                    ckey = ci["key"]
                    if ckey not in seen_keys and ckey not in discovered and ckey != key:
                        t = _parse_ticket(ci)
                        if ckey not in discovered:
                            discovered[ckey] = {
                                "ticket":   t,
                                "found_via": f"🔧 Same component '{comp}' as {key}"
                            }
            except Exception:
                pass

    return discovered


# ─────────────────────────────────────────────────────────
# MAIN ENTRY POINT — smart_search
# ─────────────────────────────────────────────────────────

def smart_search(
    project:     str,
    keyword:     str  = "",
    sprint:      str  = "",
    max_results: int  = 20,
    expand_relations: bool = True
) -> dict:
    """
    Full smart search:
    1. Split keywords → multi-keyword JQL
    2. Find direct matches
    3. Expand via all relationship types
    4. Return grouped results with how each was found
    """

    # Step 1 — split keywords
    keywords = _split_keywords(keyword) if keyword else []
    jql      = _build_multi_keyword_jql(project, keywords, sprint)

    # Step 2 — direct search
    raw_issues     = _post_search(jql, max_results)
    direct_tickets = [_parse_ticket(i) for i in raw_issues]
    direct_keys    = {t["key"] for t in direct_tickets}

    # Step 3 — relationship expansion
    discovered = {}
    if expand_relations and direct_tickets:
        discovered = _expand_relationships(direct_tickets, project, direct_keys)

    # Remove any discovered tickets that ended up in direct results
    for key in list(discovered.keys()):
        if key in direct_keys:
            del discovered[key]

    # Step 4 — build response
    return {
        "jql":              jql,
        "keywords_used":    keywords,
        "total_direct":     len(direct_tickets),
        "total_discovered": len(discovered),
        "total_found":      len(direct_tickets) + len(discovered),
        "direct_tickets":   direct_tickets,
        "discovered":       discovered,   # key → {ticket, found_via}
        # flat list for backwards compat
        "tickets": direct_tickets + [v["ticket"] for v in discovered.values()],
        "returned": len(direct_tickets) + len(discovered),
    }


def get_project_sprints(project_key: str) -> list:
    board_url = f"{JIRA_BASE}/rest/agile/1.0/board"
    r = requests.get(board_url, auth=AUTH, headers=HEADERS,
                     params={"projectKeyOrId": project_key})
    if r.status_code != 200:
        return []
    boards = r.json().get("values", [])
    if not boards:
        return []
    board_id = boards[0]["id"]
    sprint_url = f"{JIRA_BASE}/rest/agile/1.0/board/{board_id}/sprint"
    r2 = requests.get(sprint_url, auth=AUTH, headers=HEADERS,
                      params={"state": "active,future,closed"})
    if r2.status_code != 200:
        return []
    return [
        {"id": s["id"], "name": s["name"],
         "state": s["state"], "goal": s.get("goal", "")}
        for s in r2.json().get("values", [])
    ]
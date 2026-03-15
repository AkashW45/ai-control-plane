# services/confluence_search.py
#
# Searches Confluence SD space by keywords.
# Returns page titles + content excerpts for runbook context.

import os
import requests
from dotenv import load_dotenv

load_dotenv()

CONFLUENCE_BASE = os.getenv("JIRA_BASE_URL", "").replace(".atlassian.net", ".atlassian.net/wiki")
EMAIL           = os.getenv("JIRA_EMAIL")
TOKEN           = os.getenv("JIRA_API_TOKEN")
SPACE_KEY       = "SD"

AUTH    = (EMAIL, TOKEN)
HEADERS = {"Accept": "application/json"}


def search_confluence(keywords: list, max_results: int = 5) -> list:
    """
    Search Confluence SD space by keywords.
    Returns list of relevant pages with title + excerpt + url.
    """
    if not keywords:
        return []

    # Build CQL query — search title + text for any keyword
    kw_clauses = []
    for kw in keywords[:5]:  # limit to 5 keywords
        kw_clauses.append(f'text ~ "{kw}"')
        kw_clauses.append(f'title ~ "{kw}"')

    cql = f'space = "{SPACE_KEY}" AND ({" OR ".join(kw_clauses)}) ORDER BY lastmodified DESC'

    url = f"{CONFLUENCE_BASE}/rest/api/search"
    params = {
        "cql":   cql,
        "limit": max_results,
        "expand": "content.body.view"
    }

    try:
        r = requests.get(url, auth=AUTH, headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return []

    results = []
    for item in data.get("results", []):
        content = item.get("content", {})
        excerpt = item.get("excerpt", "").strip()

        # Also fetch page body for richer context
        page_id   = content.get("id", "")
        page_body = _fetch_page_body(page_id) if page_id else ""

        results.append({
            "id":      page_id,
            "title":   content.get("title", "Untitled"),
            "excerpt": excerpt or page_body[:300],
            "body":    page_body[:800],
            "url":     f"{CONFLUENCE_BASE}{item.get('url', '')}",
            "space":   SPACE_KEY,
        })

    return results


def _fetch_page_body(page_id: str) -> str:
    """Fetch plain text body of a Confluence page."""
    url = f"{CONFLUENCE_BASE}/rest/api/content/{page_id}"
    params = {"expand": "body.storage"}
    try:
        r = requests.get(url, auth=AUTH, headers=HEADERS, params=params, timeout=8)
        r.raise_for_status()
        data   = r.json()
        body   = data.get("body", {}).get("storage", {}).get("value", "")
        # Strip HTML tags simply
        import re
        clean = re.sub(r"<[^>]+>", " ", body)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean
    except Exception:
        return ""


def format_confluence_context(docs: list) -> str:
    """
    Format Confluence docs as a context block for the LLM prompt.
    """
    if not docs:
        return ""

    lines = ["CONFLUENCE DOCUMENTATION CONTEXT:"]
    for doc in docs:
        lines.append(f"\n[{doc['title']}]")
        if doc.get("body"):
            lines.append(doc["body"][:600])
        elif doc.get("excerpt"):
            lines.append(doc["excerpt"])

    return "\n".join(lines)
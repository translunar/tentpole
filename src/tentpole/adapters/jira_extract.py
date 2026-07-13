"""Jira Cloud extract adapter (spec sections 3 and 8; open question 2).
Fetch and dump -- no analysis lives here. Cloud-first: POST
/rest/api/3/search/jql with token pagination; epic relationship via
`parent` (Epic Link is retired on Cloud)."""
from __future__ import annotations

import base64

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError, request

BASE_FIELDS = ["summary", "issuetype", "status", "assignee",
               "timetracking", "parent", "fixVersions", "labels",
               "issuelinks"]

_CATEGORY = {"new": "todo", "indeterminate": "in_progress",
             "done": "done"}


def _headers(cfg: JiraConfig) -> dict:
    cred = base64.b64encode(f"{cfg.email}:{cfg.token}".encode()).decode()
    return {"Authorization": f"Basic {cred}"}


def _call(cfg, method, path, *, params=None, body=None, http=request):
    return http(method, cfg.base_url + path, _headers(cfg),
                params=params, body=body)


def _search_pages(cfg, jql, fields, *, expand=None, http=request):
    token = None
    while True:
        body = {"jql": jql, "maxResults": 100, "fields": fields}
        if expand:
            body["expand"] = expand
        if token:
            body["nextPageToken"] = token
        page = _call(cfg, "POST", "/rest/api/3/search/jql", body=body,
                     http=http)
        yield from page.get("issues", [])
        token = page.get("nextPageToken")
        if not token:
            return


def fetch_status_categories(cfg, http=request) -> dict[str, str]:
    statuses = _call(cfg, "GET", "/rest/api/3/status", http=http)
    return {s["name"]: _CATEGORY[s["statusCategory"]["key"]]
            for s in statuses}


def _days(seconds, hours_per_day):
    if seconds is None:
        return None
    return round(seconds / 3600.0 / hours_per_day, 2)


def _sprint_id(value):
    # The sprint custom field is a list of sprint objects; the last is
    # the issue's current placement.
    if not value:
        return None
    last = value[-1]
    return last.get("id") if isinstance(last, dict) else None


def _cycle_dates(changelog, categories):
    first_in_progress, done_at = None, None
    histories = sorted((changelog or {}).get("histories", []),
                       key=lambda h: h.get("created", ""))
    for h in histories:
        when = h.get("created", "")[:10]
        for item in h.get("items", []):
            if item.get("field") != "status":
                continue
            cat = categories.get(item.get("toString"))
            if cat == "in_progress" and first_in_progress is None:
                first_in_progress = when
            if cat == "done":
                done_at = when
            elif cat is not None:
                done_at = None   # moved back out of done: date is stale
    return first_in_progress, done_at


def parse_issue(raw: dict, cfg: JiraConfig, categories: dict[str, str],
                programs: dict[str, str],
                external: bool = False) -> dict:
    f = raw["fields"]
    status_category = _CATEGORY[f["status"]["statusCategory"]["key"]]
    tt = f.get("timetracking") or {}
    parent = f.get("parent")
    epic_key = parent["key"] if parent else None
    links = []
    for link in f.get("issuelinks", []):
        if "outwardIssue" in link:
            links.append({"type": link["type"]["name"],
                          "direction": "outward",
                          "other_key": link["outwardIssue"]["key"]})
        elif "inwardIssue" in link:
            links.append({"type": link["type"]["name"],
                          "direction": "inward",
                          "other_key": link["inwardIssue"]["key"]})
    first_in_progress, done_at = _cycle_dates(raw.get("changelog"),
                                              categories)
    if status_category != "done":
        done_at = None   # reopened issues must not keep a done date
    assignee = f.get("assignee") or {}
    return {
        "key": raw["key"],
        "summary": f.get("summary") or "",
        "issue_type": f["issuetype"]["name"],
        "status_category": status_category,
        "assignee": assignee.get("displayName"),
        "original_estimate_days": _days(
            tt.get("originalEstimateSeconds"), cfg.hours_per_day),
        "remaining_estimate_days": _days(
            tt.get("remainingEstimateSeconds"), cfg.hours_per_day),
        "epic_key": epic_key,
        "fix_versions": [v["name"] for v in f.get("fixVersions", [])],
        "sprint_id": _sprint_id(f.get(cfg.sprint_field)),
        "labels": f.get("labels", []),
        "links": links,
        "program": programs.get(raw["key"]) or programs.get(epic_key),
        "first_in_progress": first_in_progress,
        "done_at": done_at,
        "external": external,
    }


def _stub_external(key: str) -> dict:
    return {"key": key, "summary": "", "issue_type": "Unknown",
            "status_category": "todo", "assignee": None,
            "original_estimate_days": None,
            "remaining_estimate_days": None, "epic_key": None,
            "fix_versions": [], "sprint_id": None, "labels": [],
            "links": [], "program": None, "first_in_progress": None,
            "done_at": None, "external": True}


def fetch_issues(cfg, categories, programs, http=request) -> list[dict]:
    fields = BASE_FIELDS + [cfg.sprint_field]
    issues = [parse_issue(r, cfg, categories, programs)
              for r in _search_pages(cfg, cfg.scope_jql, fields,
                                     expand="changelog", http=http)]
    known = {i["key"] for i in issues}
    linked = sorted({link["other_key"] for i in issues
                     for link in i["links"]} - known)
    if not linked:
        return issues
    jql = "key in (" + ",".join(linked) + ")"
    try:
        external = [parse_issue(r, cfg, categories, programs,
                                external=True)
                    for r in _search_pages(cfg, jql, fields, http=http)]
    except HttpError:
        # No read access to (some of) the linked projects: keep the
        # dependency edges visible with status-unknown stubs rather
        # than failing the whole extract (spec section 2: cross-team
        # read access is an open question).
        external = [_stub_external(k) for k in linked]
    return issues + external

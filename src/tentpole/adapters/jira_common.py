"""Deployment-independent Jira extract logic, shared by the Cloud
adapter (jira_extract) and the Data Center / Server adapter
(jira_extract_dc).

Only *fetching* differs between deployments: the auth header, the search
pagination primitive, the REST API version, and where an issue's epic key
lives. Everything else -- parsing an issue into the bundle contract, the
changelog cycle dates, the external-issue stubbing, and the fetch loops
themselves -- is identical and lives here, so both adapters emit the same
bundle and a bug fixed once is fixed for both.

The pagination seam is part of that boundary: fetch_issues AND
fetch_hygiene both drive search, so each adapter passes in its own
`search_pages` generator rather than forking the loops."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import quote

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError, request

# Deployment-independent fields. Each adapter appends its sprint field and
# its epic-key field (Cloud: "parent"; Data Center: cfg.epic_link_field).
BASE_FIELDS = ["summary", "issuetype", "status", "assignee",
               "timetracking", "fixVersions", "labels", "issuelinks"]

_CATEGORY = {"new": "todo", "indeterminate": "in_progress",
             "done": "done", "undefined": "todo"}

# Legacy Server/DC serialization:
# com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c[id=123,...]
# Field order varies across versions, so search for the id key itself.
# Case-sensitive on purpose: it must not match `rapidViewId=7`.
_LEGACY_SPRINT_ID = re.compile(r"\bid=(\d+)")


def _status_category(key: str) -> str:
    try:
        return _CATEGORY[key]
    except KeyError:
        # Fail loudly but actionably: a genuinely unknown statusCategory
        # key must still stop the extract (silently guessing would hide a
        # broken sync), but name the offending key rather than let a bare
        # KeyError surface.
        raise KeyError(
            f"unknown Jira statusCategory key {key!r}; known keys are "
            f"{sorted(_CATEGORY)} -- update tentpole's _CATEGORY map"
        ) from None


def headers(cfg: JiraConfig) -> dict:
    # Deployment implies auth: Data Center / Server takes a Bearer
    # personal access token (no email); Cloud takes Basic email:token.
    # .reveal() is called here and nowhere else.
    if cfg.deployment == "datacenter":
        return {"Authorization": f"Bearer {cfg.token.reveal()}"}
    cred = base64.b64encode(
        f"{cfg.email}:{cfg.token.reveal()}".encode()).decode()
    return {"Authorization": f"Basic {cred}"}


def api_version(cfg: JiraConfig) -> str:
    return "2" if cfg.deployment == "datacenter" else "3"


def call(cfg, method, path, *, params=None, body=None, http=request):
    return http(method, cfg.base_url + path, headers(cfg),
                params=params, body=body)


def fetch_status_categories(cfg, http=request) -> dict[str, str]:
    statuses = call(cfg, "GET", f"/rest/api/{api_version(cfg)}/status",
                    http=http)
    return {s["name"]: _status_category(s["statusCategory"]["key"])
            for s in statuses}


def _days(seconds, hours_per_day):
    if seconds is None:
        return None
    return round(seconds / 3600.0 / hours_per_day, 2)


def _sprint_id(value):
    """The sprint custom field is a list; the last entry is the issue's
    current placement. Modern Jira serializes each entry as an object;
    older Server/DC serializes it as a
    `...Sprint@1a2b3c[id=123,...]` toString() dump. Anything else
    raises: returning None for an unrecognized non-empty value would
    silently drop the sprint from every issue on the instance and make a
    broken sync look healthy."""
    if not value:
        return None
    last = value[-1]
    if isinstance(last, dict):
        if "id" in last:
            sprint_id = last["id"]
            # A genuine int is the only acceptable id: None is
            # indistinguishable from "no sprint" downstream, a string
            # never matches an int Sprint.id, and bool is a subclass of
            # int in Python but not a meaningful sprint count. Any of
            # these must fall through to the raise below rather than
            # silently pass through and drop the issue from its bucket.
            if isinstance(sprint_id, int) and not isinstance(sprint_id, bool):
                return sprint_id
    elif isinstance(last, str):
        match = _LEGACY_SPRINT_ID.search(last)
        if match:
            return int(match.group(1))
    raise ValueError(
        f"unrecognized sprint custom-field value {last!r}: expected a "
        f"sprint object with an 'id', or the legacy "
        f"'...Sprint@...[id=123,...]' string form -- check that "
        f"sprint_field names this instance's sprint custom field "
        f"(GET /rest/api/2/field)")


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
                programs: dict[str, str], *, epic_key: str | None,
                external: bool = False) -> dict:
    """The bundle contract. `epic_key` is resolved by the caller because
    it is the one field whose location is deployment-specific."""
    f = raw["fields"]
    status_category = _status_category(f["status"]["statusCategory"]["key"])
    tt = f.get("timetracking") or {}
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


def fetch_issues(cfg, categories, programs, *, search_pages, fields,
                 epic_key_of, http=request) -> list[dict]:
    issues = [parse_issue(r, cfg, categories, programs,
                          epic_key=epic_key_of(r["fields"]))
              for r in search_pages(cfg, cfg.scope_jql, fields,
                                    expand="changelog", http=http)]
    known = {i["key"] for i in issues}
    linked = sorted({link["other_key"] for i in issues
                     for link in i["links"]} - known)
    if not linked:
        return issues
    jql = "key in (" + ",".join(linked) + ")"
    try:
        external = [parse_issue(r, cfg, categories, programs,
                                epic_key=epic_key_of(r["fields"]),
                                external=True)
                    for r in search_pages(cfg, jql, fields, http=http)]
    except HttpError as err:
        if err.status not in (403, 404):
            # Anything other than "not visible" (403) or "not found"
            # (404) is a real infrastructure failure -- an expired
            # token (401), an exhausted-retries 5xx, etc. Silently
            # stubbing those would hide a broken sync, so let it
            # propagate and fail the extract loudly.
            raise
        # No read access to (some of) the linked projects, or they no
        # longer exist: keep the dependency edges visible with
        # status-unknown stubs rather than failing the whole extract.
        external = [_stub_external(k) for k in linked]
    return issues + external


def fetch_sprints(cfg, http=request) -> list[dict]:
    # Agile REST 1.0 is identical on Cloud and Data Center / Server.
    if cfg.board_id is None:
        return []
    out, start = [], 0
    while True:
        page = call(cfg, "GET",
                    f"/rest/agile/1.0/board/{cfg.board_id}/sprint",
                    params={"startAt": start,
                            "state": "active,future"},
                    http=http)
        values = page.get("values", [])
        for s in values:
            if s.get("startDate") and s.get("endDate"):
                out.append({"id": s["id"], "name": s["name"],
                            "start": s["startDate"][:10],
                            "end": s["endDate"][:10]})
        if page.get("isLast", True):
            return out
        start += len(values)


def fetch_versions(cfg, http=request) -> list[dict]:
    out = []
    for project in cfg.projects:
        for v in call(cfg, "GET",
                      f"/rest/api/{api_version(cfg)}/project/"
                      f"{quote(project, safe='')}/versions",
                      http=http):
            out.append({"name": v["name"],
                        "release_date": v.get("releaseDate"),
                        "released": v.get("released", False)})
    return out


def fetch_hygiene(cfg, rules, *, search_pages,
                  http=request) -> dict[str, list[str]]:
    # Jira itself evaluates each rule's JQL at extract time, scoped to
    # the in-scope set; the core only joins membership. This rides the
    # adapter's own search pagination, which is why search_pages is a
    # parameter rather than a Cloud-only import.
    out = {}
    for rule in rules:
        if rule.jql is None:
            continue
        jql = f"({cfg.scope_jql}) AND ({rule.jql})"
        out[rule.name] = [r["key"]
                          for r in search_pages(cfg, jql, ["id"], http=http)]
    return out


def write_bundle(out_dir: Path, *, as_of: str, issues, sprints,
                 versions, hygiene, config=None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "meta.json").write_text(json.dumps({"as_of": as_of}))
    (out_dir / "issues.json").write_text(json.dumps(issues, indent=2))
    (out_dir / "sprints.json").write_text(json.dumps(sprints, indent=2))
    (out_dir / "fix_versions.json").write_text(
        json.dumps(versions, indent=2))
    (out_dir / "hygiene.json").write_text(json.dumps(hygiene, indent=2))
    if config is not None:
        (out_dir / "config.json").write_text(json.dumps(config, indent=2))

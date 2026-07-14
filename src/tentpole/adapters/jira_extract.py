"""Jira Cloud extract adapter (spec sections 3 and 8; open question 2).
Fetch and dump -- no analysis lives here. Cloud-specific surface: POST
/rest/api/3/search/jql with a nextPageToken cursor, Basic email:token
auth, and the epic relationship via `parent` (Epic Link is retired on
Cloud). Everything else -- parsing, the fetch loops, the bundle writer --
is shared with the Data Center adapter via jira_common."""
from __future__ import annotations

from tentpole.adapters import jira_common
from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import request
from tentpole.adapters.jira_common import (      # noqa: F401  (re-exported)
    BASE_FIELDS, call, fetch_sprints, fetch_status_categories,
    fetch_versions, headers, write_bundle,
)

# Re-exported under its historical name: jira_write now imports `headers`
# from jira_common directly, but tests/test_adapter_config.py still
# imports `_headers` from this module, so the alias is retained for it.
_headers = headers


def _fields(cfg: JiraConfig) -> list[str]:
    return BASE_FIELDS + ["parent", cfg.sprint_field]


def _epic_key(fields: dict) -> str | None:
    # Cloud: the epic IS the parent (Epic Link is retired).
    parent = fields.get("parent")
    return parent["key"] if parent else None


def search_pages(cfg, jql, fields, *, expand=None, http=request):
    """Cloud search pagination: an opaque nextPageToken cursor."""
    token = None
    while True:
        body = {"jql": jql, "maxResults": 100, "fields": fields}
        if expand:
            body["expand"] = expand
        if token:
            body["nextPageToken"] = token
        page = call(cfg, "POST", "/rest/api/3/search/jql", body=body,
                    http=http)
        yield from page.get("issues", [])
        token = page.get("nextPageToken")
        if not token:
            return


def parse_issue(raw: dict, cfg: JiraConfig, categories: dict[str, str],
                programs: dict[str, str],
                external: bool = False) -> dict:
    return jira_common.parse_issue(
        raw, cfg, categories, programs,
        epic_key=_epic_key(raw["fields"]), external=external)


def fetch_issues(cfg, categories, programs, http=request) -> list[dict]:
    return jira_common.fetch_issues(
        cfg, categories, programs, search_pages=search_pages,
        fields=_fields(cfg), epic_key_of=_epic_key, http=http)


def fetch_hygiene(cfg, rules, http=request) -> dict[str, list[str]]:
    return jira_common.fetch_hygiene(cfg, rules,
                                     search_pages=search_pages, http=http)

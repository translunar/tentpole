"""Jira Data Center / Server extract adapter.

Emits the identical bundle the Cloud adapter emits -- the core cannot
tell which adapter produced it. Only the fetch surface differs:

  auth        Bearer <PAT> (no email)         [jira_common.headers]
  search      POST /rest/api/2/search, offset paging via
              startAt / maxResults / total (there is no nextPageToken
              cursor here)
  epic key    an instance-specific custom field (cfg.epic_link_field);
              Data Center has no `parent` for epics
  status      GET /rest/api/2/status          [jira_common]
  versions    GET /rest/api/2/project/{k}/versions   [jira_common]
  sprints     GET /rest/agile/1.0/board/{id}/sprint  [same as Cloud]

Everything else is jira_common."""
from __future__ import annotations

from tentpole.adapters import jira_common
from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import request
from tentpole.adapters.jira_common import (     # noqa: F401  (re-exported)
    BASE_FIELDS, call, fetch_sprints, fetch_status_categories,
    fetch_versions, headers, write_bundle,
)


def _fields(cfg: JiraConfig) -> list[str]:
    return BASE_FIELDS + [cfg.epic_link_field, cfg.sprint_field]


def _epic_key_of(cfg: JiraConfig):
    """Data Center reads the epic key from a configured custom field.
    The id is instance-specific, so it is required config and never
    hardcoded."""
    def _epic_key(fields: dict) -> str | None:
        value = fields.get(cfg.epic_link_field)
        if not value:
            return None                  # genuinely not in an epic
        if isinstance(value, str):
            return value                 # the usual Epic Link shape
        if isinstance(value, dict) and "key" in value:
            return value["key"]
        raise ValueError(
            f"epic_link_field {cfg.epic_link_field!r} holds {value!r}, "
            f"which is neither an issue-key string nor an object with a "
            f"'key' -- check that epic_link_field names this instance's "
            f"Epic Link field (GET /rest/api/2/field)")
    return _epic_key


def search_pages(cfg, jql, fields, *, expand=None, http=request):
    """Data Center search pagination: startAt / maxResults / total
    offsets. Stop once we have seen `total` issues -- including when the
    final page is exactly full -- and stop on an empty page so a stale
    `total` cannot spin this loop forever."""
    start = 0
    while True:
        body = {"jql": jql, "startAt": start, "maxResults": 100,
                "fields": fields}
        if expand:
            body["expand"] = [expand]      # v2 search takes a list
        page = call(cfg, "POST", "/rest/api/2/search", body=body, http=http)
        issues = page.get("issues", [])
        yield from issues
        start += len(issues)
        if not issues:
            return
        if "total" not in page:
            # A missing `total` would make start >= page.get("total", 0)
            # true after the very first page, silently truncating the
            # sync to it with no error -- the same "looks healthy but
            # isn't" failure this codebase refuses to allow.
            raise ValueError(
                f"Data Center search response is missing 'total' "
                f"(keys: {sorted(page)}) -- cannot page reliably; check "
                f"that /rest/api/2/search on this instance/proxy returns "
                f"a 'total' count")
        if start >= page["total"]:
            return


def parse_issue(raw: dict, cfg: JiraConfig, categories: dict[str, str],
                programs: dict[str, str],
                external: bool = False) -> dict:
    return jira_common.parse_issue(
        raw, cfg, categories, programs,
        epic_key=_epic_key_of(cfg)(raw["fields"]), external=external)


def fetch_issues(cfg, categories, programs, http=request) -> list[dict]:
    return jira_common.fetch_issues(
        cfg, categories, programs, search_pages=search_pages,
        fields=_fields(cfg), epic_key_of=_epic_key_of(cfg), http=http)


def fetch_hygiene(cfg, rules, http=request) -> dict[str, list[str]]:
    return jira_common.fetch_hygiene(cfg, rules,
                                     search_pages=search_pages, http=http)

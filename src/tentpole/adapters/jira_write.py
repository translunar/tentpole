"""Allowlisted Jira writes for the human-invoked `fix apply` command
(spec sections 3 and 5). Never called by the scheduled sync. The
allowlist is structural: these three field edits are the module's
entire surface -- no transition or delete code path exists. Writes run
as, and are attributed to, the invoking human's token."""
from __future__ import annotations

from urllib.parse import quote

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import request
from tentpole.adapters.jira_extract import _headers

ALLOWED_ACTIONS = ("set_fix_version", "set_parent", "add_link")


def _call(cfg, method, path, *, body, http=request):
    return http(method, cfg.base_url + path, _headers(cfg), body=body)


def _issue_path(key: str) -> str:
    return f"/rest/api/3/issue/{quote(key, safe='')}"


def set_fix_version(cfg: JiraConfig, key: str, version: str,
                    http=request) -> None:
    _call(cfg, "PUT", _issue_path(key),
          body={"update": {"fixVersions": [{"add": {"name": version}}]}},
          http=http)


def set_parent(cfg: JiraConfig, key: str, parent_key: str,
               http=request) -> None:
    _call(cfg, "PUT", _issue_path(key),
          body={"fields": {"parent": {"key": parent_key}}}, http=http)


def add_link(cfg: JiraConfig, key: str, other_key: str,
             link_type: str = "Blocks", http=request) -> None:
    # `key` blocks `other_key` (outward side of the link).
    _call(cfg, "POST", "/rest/api/3/issueLink",
          body={"type": {"name": link_type},
                "outwardIssue": {"key": key},
                "inwardIssue": {"key": other_key}}, http=http)


def apply_action(cfg: JiraConfig, action: str, issue: str, value: str,
                 http=request) -> None:
    if action == "set_fix_version":
        set_fix_version(cfg, issue, value, http=http)
    elif action == "set_parent":
        set_parent(cfg, issue, value, http=http)
    elif action == "add_link":
        add_link(cfg, issue, value, http=http)
    else:
        raise ValueError(
            f"action {action!r} is not in the fix-apply allowlist "
            f"{ALLOWED_ACTIONS}")

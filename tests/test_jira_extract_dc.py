import base64

import pytest

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError
from tentpole.adapters.jira_common import headers
from tentpole.adapters.jira_extract_dc import (fetch_hygiene, fetch_issues,
                                               fetch_sprints,
                                               fetch_status_categories,
                                               fetch_versions, parse_issue)
from tentpole.hygiene import Rule

DC = JiraConfig(base_url="https://jira.internal", email=None, token="pat",
                scope_jql="project = ABC", projects=("ABC",), board_id=7,
                deployment="datacenter",
                epic_link_field="customfield_10014")
CLOUD = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                   scope_jql="project = ABC")
CATS = {"To Do": "todo", "In Progress": "in_progress", "Done": "done"}


def _raw(key, status="To Do", **fields):
    base = {"summary": "s", "issuetype": {"name": "Task"},
            "status": {"statusCategory": {"key": {
                "To Do": "new", "In Progress": "indeterminate",
                "Done": "done"}[status]}}}
    base.update(fields)
    return {"key": key, "fields": base}


def _page(issues, start, total):
    return {"issues": issues, "startAt": start, "maxResults": 2,
            "total": total}


def test_headers_datacenter_uses_bearer_pat_without_email():
    assert headers(DC) == {"Authorization": "Bearer pat"}


def test_headers_cloud_uses_basic_email_and_token():
    cred = base64.b64encode(b"a@b.c:t").decode()
    assert headers(CLOUD) == {"Authorization": f"Basic {cred}"}


def test_fetch_status_categories_uses_api_2(fake_http):
    fake_http.add("GET", "/rest/api/2/status", [
        {"name": "To Do", "statusCategory": {"key": "new"}},
        {"name": "Done", "statusCategory": {"key": "done"}},
    ])
    assert fetch_status_categories(DC, http=fake_http) == {
        "To Do": "todo", "Done": "done"}


def test_offset_pagination_pages_until_total(fake_http):
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-1"), _raw("A-2")], 0, 3))
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-3")], 2, 3))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1", "A-2", "A-3"]
    assert fake_http.calls[0]["body"]["startAt"] == 0
    assert fake_http.calls[1]["body"]["startAt"] == 2
    assert len(fake_http.calls) == 2


def test_offset_pagination_stops_on_exact_full_final_page(fake_http):
    """The boundary: total is an exact multiple of the page size, so the
    final page is full. startAt + len == total must terminate -- asking
    for a startAt == total page would be a wasted request, and on a
    server whose total lags it would loop."""
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-1"), _raw("A-2")], 0, 4))
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-3"), _raw("A-4")], 2, 4))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1", "A-2", "A-3", "A-4"]
    assert len(fake_http.calls) == 2


def test_offset_pagination_terminates_on_empty_page(fake_http):
    """A stale/oversized `total` must not spin the loop: an empty page
    ends it."""
    fake_http.add("POST", "/rest/api/2/search", _page([_raw("A-1")], 0, 9))
    fake_http.add("POST", "/rest/api/2/search", _page([], 1, 9))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1"]
    assert len(fake_http.calls) == 2


def test_fetch_issues_requests_epic_and_sprint_fields(fake_http):
    fake_http.add("POST", "/rest/api/2/search", _page([], 0, 0))
    fetch_issues(DC, CATS, {}, http=fake_http)
    body = fake_http.calls[0]["body"]
    assert "customfield_10014" in body["fields"]     # epic_link_field
    assert "customfield_10020" in body["fields"]     # sprint_field
    assert "parent" not in body["fields"]            # no parent on DC
    assert body["expand"] == ["changelog"]
    assert body["jql"] == "project = ABC"


def test_epic_key_read_from_configured_field():
    out = parse_issue(_raw("A-1", customfield_10014="E-7"), DC, CATS,
                      {"E-7": "prog-a"})
    assert out["epic_key"] == "E-7"
    assert out["program"] == "prog-a"     # inherited via the epic key


def test_epic_key_missing_field_is_none():
    assert parse_issue(_raw("A-1"), DC, CATS, {})["epic_key"] is None


def test_epic_key_unrecognized_shape_raises():
    with pytest.raises(ValueError, match="epic_link_field"):
        parse_issue(_raw("A-1", customfield_10014=[{"key": "E-7"}]),
                    DC, CATS, {})


def test_fetch_versions_uses_api_2(fake_http):
    fake_http.add("GET", "/rest/api/2/project/ABC/versions", [
        {"name": "R1", "releaseDate": "2026-09-01", "released": False},
    ])
    assert fetch_versions(DC, http=fake_http) == [
        {"name": "R1", "release_date": "2026-09-01", "released": False}]


def test_fetch_sprints_uses_agile_1_0(fake_http):
    fake_http.add("GET", "/rest/agile/1.0/board/7/sprint", {
        "values": [{"id": 1, "name": "S1",
                    "startDate": "2026-07-13T00:00:00.000Z",
                    "endDate": "2026-07-24T00:00:00.000Z"}],
        "isLast": True})
    assert fetch_sprints(DC, http=fake_http) == [
        {"id": 1, "name": "S1", "start": "2026-07-13",
         "end": "2026-07-24"}]


def test_fetch_hygiene_scopes_rule_jql_over_dc_search(fake_http):
    rules = [Rule(name="unanchored", severity="red", message="m",
                  jql="fixVersion is EMPTY")]
    fake_http.add("POST", "/rest/api/2/search",
                  _page([{"key": "A-1"}], 0, 1))
    assert fetch_hygiene(DC, rules, http=fake_http) == {
        "unanchored": ["A-1"]}
    assert fake_http.calls[0]["body"]["jql"] == (
        "(project = ABC) AND (fixVersion is EMPTY)")


def test_external_linked_issues_stubbed_on_403(fake_http):
    linked = _raw("A-7", issuelinks=[
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "Z-1"}}])
    fake_http.add("POST", "/rest/api/2/search", _page([linked], 0, 1))
    fake_http.add("POST", "/rest/api/2/search",
                  HttpError(403, "https://jira.internal", "forbidden"))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    ext = [i for i in issues if i["external"]]
    assert [i["key"] for i in ext] == ["Z-1"]
    assert ext[0]["status_category"] == "todo"
    assert fake_http.calls[1]["body"]["jql"] == "key in (Z-1)"


def test_search_pages_raises_on_missing_total(fake_http):
    """A response missing 'total' must not silently truncate the sync to
    the first page: start >= page.get("total", 0) would treat start >= 0
    as already-done and return only the issues seen so far, with no
    error."""
    fake_http.add("POST", "/rest/api/2/search",
                  {"issues": [_raw("A-1")], "startAt": 0, "maxResults": 2})
    with pytest.raises((ValueError, KeyError), match="total"):
        fetch_issues(DC, CATS, {}, http=fake_http)


def test_external_linked_issues_propagate_on_500(fake_http):
    """Only 403/404 may become a status-unknown stub. A 500 that already
    exhausted its retries is a real infrastructure failure -- silently
    stubbing it would make a broken sync look benign."""
    linked = _raw("A-9", issuelinks=[
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "Z-2"}}])
    fake_http.add("POST", "/rest/api/2/search", _page([linked], 0, 1))
    fake_http.add("POST", "/rest/api/2/search",
                  HttpError(500, "https://jira.internal", "boom"))
    with pytest.raises(HttpError):
        fetch_issues(DC, CATS, {}, http=fake_http)

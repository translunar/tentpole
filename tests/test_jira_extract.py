from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError
from tentpole.adapters.jira_extract import (fetch_issues,
                                            fetch_status_categories,
                                            parse_issue)

CFG = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                 scope_jql="project = ABC")
CATS = {"To Do": "todo", "In Progress": "in_progress", "Done": "done"}


def _raw(key, status="To Do", **fields):
    base = {"summary": "s", "issuetype": {"name": "Task"},
            "status": {"statusCategory": {"key": {
                "To Do": "new", "In Progress": "indeterminate",
                "Done": "done"}[status]}}}
    base.update(fields)
    return {"key": key, "fields": base}


def test_status_categories_fetched(fake_http):
    fake_http.add("GET", "/rest/api/3/status", [
        {"name": "To Do", "statusCategory": {"key": "new"}},
        {"name": "Done", "statusCategory": {"key": "done"}},
    ])
    assert fetch_status_categories(CFG, http=fake_http) == {
        "To Do": "todo", "Done": "done"}


def test_pagination_follows_next_page_token(fake_http):
    fake_http.add("POST", "/rest/api/3/search/jql",
                  {"issues": [_raw("A-1")], "nextPageToken": "tok2"})
    fake_http.add("POST", "/rest/api/3/search/jql",
                  {"issues": [_raw("A-2")]})
    issues = fetch_issues(CFG, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1", "A-2"]
    assert fake_http.calls[1]["body"]["nextPageToken"] == "tok2"
    assert fake_http.calls[0]["body"]["jql"] == "project = ABC"
    assert "changelog" in fake_http.calls[0]["body"]["expand"]


def test_parse_issue_maps_fields():
    raw = _raw(
        "A-3", status="In Progress",
        assignee={"displayName": "ada"},
        timetracking={"originalEstimateSeconds": 8 * 3600 * 2,
                      "remainingEstimateSeconds": 8 * 3600},
        parent={"key": "E-1"},
        fixVersions=[{"name": "R1"}], labels=["overhead"],
        issuelinks=[
            {"type": {"name": "Blocks"},
             "outwardIssue": {"key": "X-9"}},
            {"type": {"name": "Blocks"},
             "inwardIssue": {"key": "X-8"}},
        ],
        customfield_10020=[{"id": 4, "name": "S4"}],
    )
    out = parse_issue(raw, CFG, CATS, {"E-1": "prog-a"})
    assert out["key"] == "A-3"
    assert out["status_category"] == "in_progress"
    assert out["assignee"] == "ada"
    assert out["original_estimate_days"] == 2.0
    assert out["remaining_estimate_days"] == 1.0
    assert out["epic_key"] == "E-1"
    assert out["fix_versions"] == ["R1"]
    assert out["sprint_id"] == 4
    assert out["labels"] == ["overhead"]
    assert out["links"] == [
        {"type": "Blocks", "direction": "outward", "other_key": "X-9"},
        {"type": "Blocks", "direction": "inward", "other_key": "X-8"}]
    assert out["program"] == "prog-a"       # inherited from epic key
    assert out["done_at"] is None
    assert out["external"] is False


def test_cycle_dates_from_changelog():
    raw = _raw("A-4", status="Done")
    raw["changelog"] = {"histories": [
        {"created": "2026-07-02T10:00:00.000+0000", "items": [
            {"field": "status", "toString": "In Progress"}]},
        {"created": "2026-07-01T09:00:00.000+0000", "items": [
            {"field": "status", "toString": "In Progress"}]},
        {"created": "2026-07-05T15:00:00.000+0000", "items": [
            {"field": "status", "toString": "Done"}]},
    ]}
    out = parse_issue(raw, CFG, CATS, {})
    assert out["first_in_progress"] == "2026-07-01"   # sorted, not given order
    assert out["done_at"] == "2026-07-05"


def test_reopened_issue_nulls_done_at():
    raw = _raw("A-5", status="In Progress")
    raw["changelog"] = {"histories": [
        {"created": "2026-07-01T09:00:00.000+0000", "items": [
            {"field": "status", "toString": "Done"}]},
        {"created": "2026-07-03T09:00:00.000+0000", "items": [
            {"field": "status", "toString": "In Progress"}]},
    ]}
    out = parse_issue(raw, CFG, CATS, {})
    assert out["done_at"] is None


def test_done_at_null_when_current_status_not_done():
    # Changelog ends in Done but the live status says otherwise (e.g.
    # reopened via a workflow the changelog page missed): trust status.
    raw = _raw("A-6", status="To Do")
    raw["changelog"] = {"histories": [
        {"created": "2026-07-01T09:00:00.000+0000", "items": [
            {"field": "status", "toString": "Done"}]},
    ]}
    assert parse_issue(raw, CFG, CATS, {})["done_at"] is None


def test_external_linked_issues_stubbed_on_http_error(fake_http):
    linked = _raw("A-7", issuelinks=[
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "Z-1"}}])
    fake_http.add("POST", "/rest/api/3/search/jql", {"issues": [linked]})
    fake_http.add("POST", "/rest/api/3/search/jql",
                  HttpError(403, "https://x.net", "forbidden"))
    issues = fetch_issues(CFG, CATS, {}, http=fake_http)
    ext = [i for i in issues if i["external"]]
    assert [i["key"] for i in ext] == ["Z-1"]
    assert ext[0]["status_category"] == "todo"
    assert "key in (Z-1)" == fake_http.calls[1]["body"]["jql"]


def test_zero_seconds_remaining_yields_zero_days_not_none():
    """Mandatory fix: 0 seconds remaining must convert to 0.0 days, not None.

    This pins the bug fix in _days(): using `if not seconds:` conflates
    an explicit 0 with an absent field (None). Downstream, demand.estimate_of()
    falls back to original_estimate_days whenever remaining_estimate_days is None,
    silently overstating demand.
    """
    raw = _raw(
        "A-8", status="In Progress",
        timetracking={"originalEstimateSeconds": 8 * 3600 * 3,
                      "remainingEstimateSeconds": 0}
    )
    out = parse_issue(raw, CFG, CATS, {})
    assert out["remaining_estimate_days"] == 0.0
    assert out["original_estimate_days"] == 3.0
    # Verify that this does NOT get None (which would cause fallback)
    assert out["remaining_estimate_days"] is not None

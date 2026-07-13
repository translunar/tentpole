from datetime import date

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.jira_extract import (fetch_hygiene, fetch_sprints,
                                            fetch_versions, write_bundle)
from tentpole.hygiene import Rule
from tentpole.model import load_bundle

CFG = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                 scope_jql="project = ABC", projects=("ABC",),
                 board_id=7)


def test_fetch_sprints_pages_and_skips_undated(fake_http):
    fake_http.add("GET", "/rest/agile/1.0/board/7/sprint", {
        "values": [
            {"id": 1, "name": "S1",
             "startDate": "2026-07-13T00:00:00.000Z",
             "endDate": "2026-07-24T00:00:00.000Z"},
            {"id": 2, "name": "future-no-dates"},
        ],
        "isLast": False})
    fake_http.add("GET", "/rest/agile/1.0/board/7/sprint", {
        "values": [
            {"id": 3, "name": "S3",
             "startDate": "2026-07-27T00:00:00.000Z",
             "endDate": "2026-08-07T00:00:00.000Z"},
        ],
        "isLast": True})
    out = fetch_sprints(CFG, http=fake_http)
    assert out == [
        {"id": 1, "name": "S1", "start": "2026-07-13",
         "end": "2026-07-24"},
        {"id": 3, "name": "S3", "start": "2026-07-27",
         "end": "2026-08-07"}]
    assert fake_http.calls[1]["params"]["startAt"] == 2


def test_fetch_sprints_without_board_returns_empty(fake_http):
    cfg = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                     scope_jql="project = ABC")
    assert fetch_sprints(cfg, http=fake_http) == []
    assert fake_http.calls == []


def test_fetch_versions_across_projects(fake_http):
    fake_http.add("GET", "/rest/api/3/project/ABC/versions", [
        {"name": "R1", "releaseDate": "2026-09-01", "released": False},
        {"name": "R0", "released": True},
    ])
    assert fetch_versions(CFG, http=fake_http) == [
        {"name": "R1", "release_date": "2026-09-01", "released": False},
        {"name": "R0", "release_date": None, "released": True}]


def test_fetch_hygiene_scopes_rule_jql(fake_http):
    rules = [
        Rule(name="unanchored", severity="red", message="m",
             jql="fixVersion is EMPTY"),
        Rule(name="derived-only", severity="yellow", message="m",
             derived="inherits_no_fixversion"),
    ]
    fake_http.add("POST", "/rest/api/3/search/jql",
                  {"issues": [{"key": "A-1"}, {"key": "A-2"}]})
    out = fetch_hygiene(CFG, rules, http=fake_http)
    assert out == {"unanchored": ["A-1", "A-2"]}
    sent = fake_http.calls[0]["body"]["jql"]
    assert sent == "(project = ABC) AND (fixVersion is EMPTY)"


def test_write_bundle_round_trips_through_load_bundle(tmp_path):
    issues = [{"key": "A-1", "summary": "s", "issue_type": "Task",
               "status_category": "todo"}]
    sprints = [{"id": 1, "name": "S1", "start": "2026-07-13",
                "end": "2026-07-24"}]
    versions = [{"name": "R1", "release_date": "2026-09-01",
                 "released": False}]
    write_bundle(tmp_path / "b", as_of="2026-07-12", issues=issues,
                 sprints=sprints, versions=versions,
                 hygiene={"unanchored": ["A-1"]},
                 config={"team": ["ada"]})
    bundle = load_bundle(tmp_path / "b")
    assert bundle.as_of == date(2026, 7, 12)
    assert bundle.issues[0].key == "A-1"
    assert bundle.sprints[0].start == date(2026, 7, 13)
    assert bundle.fix_versions[0].name == "R1"
    assert bundle.hygiene_memberships == {"unanchored": ["A-1"]}
    assert bundle.config.team == ["ada"]

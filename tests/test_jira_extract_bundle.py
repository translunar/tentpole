import json
import urllib.request
from datetime import date

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.jira_extract import (fetch_hygiene, fetch_sprints,
                                            fetch_versions, write_bundle)
from tentpole.cli import main
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


class _FakeUrlopenResponse:
    """Mimics the object urllib.request.urlopen(...) hands back to
    urllib_transport: a context manager with .status/.headers/.read()."""

    def __init__(self, status, payload):
        self.status = status
        self.headers = {}
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def _fake_urlopen(routes):
    # routes: list of (method, path_substring, json_payload), consumed by
    # matching against the real urllib.request.Request the adapter built.
    def _urlopen(req, *args, **kwargs):
        method = req.get_method()
        url = req.full_url
        for want_method, want_path, payload in routes:
            if want_method == method and want_path in url:
                return _FakeUrlopenResponse(200, payload)
        raise AssertionError(f"unexpected request: {method} {url}")
    return _urlopen


def test_cli_extract_end_to_end(tmp_path, monkeypatch):
    # Drives the real `tentpole extract ...` entry point (argparse ->
    # adapters/cli.dispatch -> _extract -> jira_extract -> write_bundle)
    # so a wiring bug -- a typo'd args.<attr>, a swapped positional in
    # write_bundle(...), a mis-routed dispatch -- fails this test instead
    # of surfacing only on the user's first real invocation. No network:
    # the fake sits at urllib.request.urlopen, the one seam that is a
    # live attribute lookup rather than a bound default, so no
    # production code changes were needed to inject it.
    monkeypatch.setenv("JIRA_TOKEN", "secret-token")
    config_path = tmp_path / "tentpole.yaml"
    config_path.write_text(
        "jira:\n"
        "  base_url: https://example.atlassian.net\n"
        "  email: a@b.c\n"
        "  token_env: JIRA_TOKEN\n"
        "  scope_jql: project = ABC\n"
        "core:\n"
        "  team: [ada]\n"
    )
    out_dir = tmp_path / "bundle"

    routes = [
        ("GET", "/rest/api/3/status", [
            {"name": "To Do", "statusCategory": {"key": "new"}},
            {"name": "Done", "statusCategory": {"key": "done"}},
        ]),
        ("POST", "/rest/api/3/search/jql", {"issues": [{
            "key": "ABC-1",
            "fields": {
                "summary": "Do the thing",
                "issuetype": {"name": "Task"},
                "status": {"name": "To Do",
                          "statusCategory": {"key": "new"}},
                "assignee": None,
                "timetracking": {},
                "parent": None,
                "fixVersions": [],
                "labels": [],
                "issuelinks": [],
                "customfield_10020": None,
            },
            "changelog": {"histories": []},
        }]}),
    ]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))

    exit_code = main(["extract", "--config", str(config_path),
                      "--out", str(out_dir)])

    assert exit_code == 0
    bundle = load_bundle(out_dir)
    assert [i.key for i in bundle.issues] == ["ABC-1"]
    assert bundle.issues[0].status_category == "todo"
    assert bundle.sprints == []
    assert bundle.fix_versions == []
    assert bundle.hygiene_memberships == {}
    assert bundle.config.team == ["ada"]
    # date.today() is stamped by the adapter edge; assert the bundle
    # carries a well-formed date rather than pinning a literal value
    # (keeps the test off the real clock).
    meta = json.loads((out_dir / "meta.json").read_text())
    date.fromisoformat(meta["as_of"])

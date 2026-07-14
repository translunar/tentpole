import json
import urllib.request

from tentpole.adapters import jira_extract, jira_extract_dc
from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError
from tentpole.cli import main
from tentpole.hygiene import Rule
from tentpole.model import load_bundle

CLOUD = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                   scope_jql="project = ABC", projects=("ABC",),
                   board_id=7)
DC = JiraConfig(base_url="https://jira.internal", email=None, token="pat",
                scope_jql="project = ABC", projects=("ABC",), board_id=7,
                deployment="datacenter",
                epic_link_field="customfield_10014",
                sprint_field="customfield_10020")

STATUSES = [{"name": "To Do", "statusCategory": {"key": "new"}},
            {"name": "In Progress",
             "statusCategory": {"key": "indeterminate"}},
            {"name": "Done", "statusCategory": {"key": "done"}}]
SPRINT_PAGE = {"values": [{"id": 4, "name": "S4",
                           "startDate": "2026-07-13T00:00:00.000Z",
                           "endDate": "2026-07-24T00:00:00.000Z"}],
               "isLast": True}
VERSIONS = [{"name": "R1", "releaseDate": "2026-09-01",
             "released": False}]
CHANGELOG = {"histories": [
    {"created": "2026-07-02T10:00:00.000+0000",
     "items": [{"field": "status", "toString": "In Progress"}]}]}
RULES = [Rule(name="unanchored", severity="red", message="m",
              jql="fixVersion is EMPTY")]
LEGACY_SPRINT = ("com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c["
                 "rapidViewId=7,state=ACTIVE,name=S4,id=4]")


def _shared_fields():
    return {
        "summary": "Do the thing",
        "issuetype": {"name": "Task"},
        "status": {"statusCategory": {"key": "indeterminate"}},
        "assignee": {"displayName": "ada"},
        "timetracking": {"originalEstimateSeconds": 8 * 3600 * 2,
                         "remainingEstimateSeconds": 8 * 3600},
        "fixVersions": [{"name": "R1"}],
        "labels": ["backend"],
        "issuelinks": [{"type": {"name": "Blocks"},
                        "inwardIssue": {"key": "ZZ-1"}}],
    }


CLOUD_ISSUE = {"key": "ABC-1",
               "fields": {**_shared_fields(),
                          "parent": {"key": "ABC-9"},
                          "customfield_10020": [{"id": 4, "name": "S4"}]},
               "changelog": CHANGELOG}
DC_ISSUE = {"key": "ABC-1",
            "fields": {**_shared_fields(),
                       "customfield_10014": "ABC-9",
                       "customfield_10020": [LEGACY_SPRINT]},
            "changelog": CHANGELOG}


def _extract_to(adapter, cfg, http, out_dir):
    categories = adapter.fetch_status_categories(cfg, http=http)
    adapter.write_bundle(
        out_dir,
        as_of="2026-07-12",
        issues=adapter.fetch_issues(cfg, categories, {}, http=http),
        sprints=adapter.fetch_sprints(cfg, http=http),
        versions=adapter.fetch_versions(cfg, http=http),
        hygiene=adapter.fetch_hygiene(cfg, RULES, http=http),
        config={"team": ["ada"]})


def test_dc_and_cloud_emit_identical_bundles(tmp_path, make_http):
    """THE load-bearing test. Both adapters see the same logical issue in
    their own REST dialect -- Cloud's parent + sprint objects and token
    cursor, Data Center's epic custom field + legacy sprint string and
    offset paging -- and must produce byte-identical bundles, including
    the 403 status-unknown stub for the linked issue."""
    cloud_http = make_http()
    cloud_http.add("GET", "/rest/api/3/status", STATUSES)
    cloud_http.add("POST", "/rest/api/3/search/jql",
                   {"issues": [CLOUD_ISSUE]})
    cloud_http.add("POST", "/rest/api/3/search/jql",
                   HttpError(403, "https://x.net", "forbidden"))
    cloud_http.add("GET", "/rest/agile/1.0/board/7/sprint", SPRINT_PAGE)
    cloud_http.add("GET", "/rest/api/3/project/ABC/versions", VERSIONS)
    cloud_http.add("POST", "/rest/api/3/search/jql",
                   {"issues": [{"key": "ABC-1"}]})

    dc_http = make_http()
    dc_http.add("GET", "/rest/api/2/status", STATUSES)
    dc_http.add("POST", "/rest/api/2/search",
                {"issues": [DC_ISSUE], "startAt": 0, "maxResults": 100,
                 "total": 1})
    dc_http.add("POST", "/rest/api/2/search",
                HttpError(403, "https://jira.internal", "forbidden"))
    dc_http.add("GET", "/rest/agile/1.0/board/7/sprint", SPRINT_PAGE)
    dc_http.add("GET", "/rest/api/2/project/ABC/versions", VERSIONS)
    dc_http.add("POST", "/rest/api/2/search",
                {"issues": [{"key": "ABC-1"}], "startAt": 0,
                 "maxResults": 100, "total": 1})

    cloud_dir, dc_dir = tmp_path / "cloud", tmp_path / "dc"
    _extract_to(jira_extract, CLOUD, cloud_http, cloud_dir)
    _extract_to(jira_extract_dc, DC, dc_http, dc_dir)

    for name in ("meta.json", "issues.json", "sprints.json",
                 "fix_versions.json", "hygiene.json", "config.json"):
        assert (cloud_dir / name).read_text() == (dc_dir / name).read_text(), name

    # Guard against a false pass on two empty bundles: the DC issue really
    # did resolve its epic and its legacy sprint string.
    issues = json.loads((dc_dir / "issues.json").read_text())
    assert [i["key"] for i in issues] == ["ABC-1", "ZZ-1"]
    assert issues[0]["epic_key"] == "ABC-9"
    assert issues[0]["sprint_id"] == 4
    assert issues[0]["original_estimate_days"] == 2.0
    assert issues[0]["first_in_progress"] == "2026-07-02"
    assert issues[1]["external"] is True


def test_cloud_and_dc_request_the_same_fields():
    """FakeHttp (conftest.FakeHttp) matches on method + URL substring and
    ignores the request body entirely, so test_dc_and_cloud_emit_identical_
    bundles's byte-equal bundles do NOT prove the two adapters asked Jira
    for the same fields -- the canned responses hand back timetracking,
    labels, fixVersions etc. regardless of what each adapter's _fields()
    actually requested. Concretely: dropping "timetracking" from
    jira_extract_dc._fields leaves the whole suite green, including the
    byte-equality test, while a live Data Center instance would silently
    lose every issue's estimate. This assertion closes that hole directly."""
    assert (set(jira_extract._fields(CLOUD)) - {"parent"}
            == set(jira_extract_dc._fields(DC)) - {"customfield_10014"})
    # The subtraction above makes "parent" disappearing from Cloud's
    # requested fields invisible to this assertion -- it would simply
    # subtract nothing on both sides and still pass. Pin it directly:
    # a live Cloud instance with no "parent" in the request means
    # _epic_key always returns None, gutting every epic/program rollup.
    assert "parent" in jira_extract._fields(CLOUD)


class _FakeUrlopenResponse:
    """Mimics what urllib.request.urlopen(...) hands urllib_transport."""

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


class _Recorder:
    def __init__(self, routes):
        self.routes = routes
        self.seen = []          # (method, url, headers)

    def __call__(self, req, *args, **kwargs):
        method, url = req.get_method(), req.full_url
        self.seen.append((method, url, dict(req.headers)))
        for want_method, want_path, payload in self.routes:
            if want_method == method and want_path in url:
                return _FakeUrlopenResponse(200, payload)
        raise AssertionError(f"unexpected request: {method} {url}")


def test_cli_extract_routes_datacenter_config_to_the_dc_adapter(
        tmp_path, monkeypatch):
    """Drives the real `tentpole extract` entry point with a datacenter
    config: argparse -> adapters/cli._extract -> jira_extract_dc. Proves
    the dispatch, the Bearer header, and the /rest/api/2 surface."""
    monkeypatch.setenv("JIRA_PAT", "dc-pat")
    config_path = tmp_path / "tentpole.yaml"
    config_path.write_text(
        "jira:\n"
        "  base_url: https://jira.internal\n"
        "  deployment: datacenter\n"
        "  token_env_var: JIRA_PAT\n"
        "  epic_link_field: customfield_10014\n"
        "  sprint_field: customfield_10020\n"
        "  scope_jql: project = ABC\n"
        "core:\n"
        "  team: [ada]\n")
    routes = [
        ("GET", "/rest/api/2/status", STATUSES),
        ("POST", "/rest/api/2/search",
         {"issues": [{"key": "ABC-1",
                      "fields": {**_shared_fields(),
                                 "issuelinks": [],
                                 "customfield_10014": "ABC-9",
                                 "customfield_10020": [LEGACY_SPRINT]},
                      "changelog": CHANGELOG}],
          "startAt": 0, "maxResults": 100, "total": 1}),
    ]
    recorder = _Recorder(routes)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    out_dir = tmp_path / "bundle"

    assert main(["extract", "--config", str(config_path),
                 "--out", str(out_dir)]) == 0

    bundle = load_bundle(out_dir)
    assert [i.key for i in bundle.issues] == ["ABC-1"]
    assert bundle.issues[0].epic_key == "ABC-9"
    assert bundle.issues[0].sprint_id == 4
    assert bundle.config.team == ["ada"]
    # Bearer PAT on every call, and never a Cloud endpoint.
    assert [h["Authorization"] for _, _, h in recorder.seen] == [
        "Bearer dc-pat", "Bearer dc-pat"]
    assert all("/rest/api/3" not in url for _, url, _ in recorder.seen)

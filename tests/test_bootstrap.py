import pytest

from tentpole.adapters.config import SmartsheetConfig
from tentpole.adapters.smartsheet_load import bootstrap
from tentpole.schema import SCHEMAS


def _queue_all(fake_http, path):
    for i, name in enumerate(SCHEMAS):
        fake_http.add("POST", path,
                      {"message": "SUCCESS",
                       "result": {"id": 1000 + i,
                                  "name": f"tentpole {name}"}})


def test_bootstrap_creates_all_sheets_with_mapped_columns(fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    _queue_all(fake_http, "/sheets")
    created = bootstrap(cfg, http=fake_http)
    assert set(created) == set(SCHEMAS)
    issues_body = fake_http.calls[list(SCHEMAS).index("issues")]["body"]
    assert issues_body["name"] == "tentpole issues"
    by_title = {c["title"]: c for c in issues_body["columns"]}
    assert by_title["Key"]["primary"] is True
    assert by_title["Key"]["type"] == "TEXT_NUMBER"
    assert by_title["Original Est"]["type"] == "TEXT_NUMBER"
    assert by_title["In Progress"]["type"] == "DATE"
    assert by_title["In Jira"]["type"] == "CHECKBOX"


def test_bootstrap_uses_workspace_when_configured(fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=77)
    _queue_all(fake_http, "/workspaces/77/sheets")
    bootstrap(cfg, http=fake_http)
    assert all("/workspaces/77/sheets" in c["url"]
               for c in fake_http.calls)


def test_cli_bootstrap_prints_config_snippet(tmp_path, monkeypatch,
                                             capsys):
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n")
    monkeypatch.setenv("S", "tok")
    import tentpole.adapters.cli as edge_cli
    monkeypatch.setattr(edge_cli.smartsheet_load, "bootstrap",
                        lambda cfg, names=None: {"issues": 1000, "epics": 1001})
    from tentpole.cli import main
    code = main(["bootstrap",
                 "--config", str(tmp_path / "tentpole.yaml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "issues: 1000" in out and "epics: 1001" in out
    assert "SmartsheetGov" in out          # the not-integration-tested warning


def test_bootstrap_subset_creates_only_named(fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    for i, name in enumerate(["issues", "capacity"]):
        fake_http.add("POST", "/sheets",
                      {"result": {"id": 2000 + i, "name": f"tentpole {name}"}})
    created = bootstrap(cfg, http=fake_http, names=["issues", "capacity"])
    assert set(created) == {"issues", "capacity"}
    assert len(fake_http.calls) == 2


def test_bootstrap_subset_rejects_unknown_name(fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    with pytest.raises(ValueError, match="mystery"):
        bootstrap(cfg, http=fake_http, names=["issues", "mystery"])

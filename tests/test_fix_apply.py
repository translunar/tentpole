import json

import pytest

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.jira_write import (add_link, apply_action,
                                          set_fix_version, set_parent)
from tentpole.cli import main

CFG = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                 scope_jql="project = ABC")


def test_set_fix_version_body(fake_http):
    fake_http.add("PUT", "/rest/api/3/issue/T-1", {})
    set_fix_version(CFG, "T-1", "R1", http=fake_http)
    assert fake_http.calls[0]["body"] == {
        "update": {"fixVersions": [{"add": {"name": "R1"}}]}}


def test_set_parent_body(fake_http):
    fake_http.add("PUT", "/rest/api/3/issue/T-1", {})
    set_parent(CFG, "T-1", "E-2", http=fake_http)
    assert fake_http.calls[0]["body"] == {
        "fields": {"parent": {"key": "E-2"}}}


def test_add_link_body(fake_http):
    fake_http.add("POST", "/rest/api/3/issueLink", {})
    add_link(CFG, "T-1", "X-9", http=fake_http)
    assert fake_http.calls[0]["body"] == {
        "type": {"name": "Blocks"},
        "outwardIssue": {"key": "T-1"},
        "inwardIssue": {"key": "X-9"}}


def test_apply_action_rejects_unallowlisted(fake_http):
    with pytest.raises(ValueError, match="allowlist"):
        apply_action(CFG, "transition_to_done", "T-1", "Done",
                     http=fake_http)
    assert fake_http.calls == []


def _setup(tmp_path, monkeypatch, proposals):
    cfg = tmp_path / "tentpole.yaml"
    cfg.write_text("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
                   "  token_env_var: J\n  scope_jql: project = ABC\n")
    monkeypatch.setenv("J", "tok")
    pfile = tmp_path / "proposals.json"
    pfile.write_text(json.dumps(proposals))
    return cfg, pfile


PROPOSALS = [
    {"issue": "T-1", "action": "set_fix_version", "value": "R1",
     "rationale": "r", "confidence": "mechanical", "rule": "u"},
    {"issue": "T-2", "action": "set_fix_version", "value": "R1",
     "rationale": "r", "confidence": "mechanical", "rule": "u"},
    {"issue": "T-3", "action": "set_parent", "value": "E-1",
     "rationale": "r", "confidence": "suggested", "rule": "o"},
]


def test_fix_apply_y_n_q(tmp_path, monkeypatch, capsys):
    cfg, pfile = _setup(tmp_path, monkeypatch, PROPOSALS)
    applied = []
    import tentpole.adapters.cli as edge_cli
    monkeypatch.setattr(
        edge_cli.jira_write, "apply_action",
        lambda c, action, issue, value: applied.append(issue))
    answers = iter(["y", "n", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    code = main(["fix", "apply", "--config", str(cfg),
                 "--proposals", str(pfile)])
    assert code == 0
    assert applied == ["T-1"]
    assert "applied 1, skipped 1" in capsys.readouterr().out


def test_fix_apply_all_batches_mechanical_only(tmp_path, monkeypatch,
                                               capsys):
    cfg, pfile = _setup(tmp_path, monkeypatch, PROPOSALS)
    applied = []
    import tentpole.adapters.cli as edge_cli
    monkeypatch.setattr(
        edge_cli.jira_write, "apply_action",
        lambda c, action, issue, value: applied.append(issue))
    # "all" on the first prompt; the suggested proposal still prompts.
    answers = iter(["all", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    code = main(["fix", "apply", "--config", str(cfg),
                 "--proposals", str(pfile)])
    assert code == 0
    assert applied == ["T-1", "T-2"]
    assert "applied 2, skipped 1" in capsys.readouterr().out


def test_issue_key_is_url_escaped(fake_http):
    fake_http.add("PUT", "/rest/api/3/issue/A%20B%2F1", {})
    set_parent(CFG, "A B/1", "E-2", http=fake_http)
    assert "/rest/api/3/issue/A%20B%2F1" in fake_http.calls[0]["url"]


DC = JiraConfig(base_url="https://jira.internal", email=None, token="pat",
                scope_jql="project = ABC", deployment="datacenter",
                epic_link_field="customfield_10014")


def test_set_fix_version_uses_api_2_on_datacenter(fake_http):
    fake_http.add("PUT", "/rest/api/2/issue/T-1", {})
    set_fix_version(DC, "T-1", "R1", http=fake_http)
    assert "/rest/api/2/issue/T-1" in fake_http.calls[0]["url"]
    # Identical payload across deployments; only the path moves.
    assert fake_http.calls[0]["body"] == {
        "update": {"fixVersions": [{"add": {"name": "R1"}}]}}


def test_set_parent_writes_epic_link_field_on_datacenter(fake_http):
    """The exact mirror of the read side: Data Center has no `parent`, so
    the epic key goes back into the same custom field jira_extract_dc
    reads it from."""
    fake_http.add("PUT", "/rest/api/2/issue/T-1", {})
    set_parent(DC, "T-1", "E-2", http=fake_http)
    assert "/rest/api/2/issue/T-1" in fake_http.calls[0]["url"]
    assert fake_http.calls[0]["body"] == {
        "fields": {"customfield_10014": "E-2"}}


def test_add_link_uses_api_2_on_datacenter(fake_http):
    fake_http.add("POST", "/rest/api/2/issueLink", {})
    add_link(DC, "T-1", "X-9", http=fake_http)
    assert "/rest/api/2/issueLink" in fake_http.calls[0]["url"]
    assert fake_http.calls[0]["body"] == {
        "type": {"name": "Blocks"},
        "outwardIssue": {"key": "T-1"},
        "inwardIssue": {"key": "X-9"}}


def test_cloud_write_paths_stay_on_api_3(fake_http):
    """Regression guard: making the paths version-aware must not move
    Cloud, and Cloud's set_parent must keep the `parent` payload."""
    fake_http.add("PUT", "/rest/api/3/issue/T-1", {})
    fake_http.add("PUT", "/rest/api/3/issue/T-1", {})
    fake_http.add("POST", "/rest/api/3/issueLink", {})
    set_fix_version(CFG, "T-1", "R1", http=fake_http)
    set_parent(CFG, "T-1", "E-2", http=fake_http)
    add_link(CFG, "T-1", "X-9", http=fake_http)
    assert [c["url"] for c in fake_http.calls] == [
        "https://x.net/rest/api/3/issue/T-1",
        "https://x.net/rest/api/3/issue/T-1",
        "https://x.net/rest/api/3/issueLink"]
    assert fake_http.calls[1]["body"] == {
        "fields": {"parent": {"key": "E-2"}}}


def test_apply_action_routes_all_three_on_datacenter(fake_http):
    fake_http.add("PUT", "/rest/api/2/issue/T-1", {})
    fake_http.add("PUT", "/rest/api/2/issue/T-2", {})
    fake_http.add("POST", "/rest/api/2/issueLink", {})
    apply_action(DC, "set_fix_version", "T-1", "R1", http=fake_http)
    apply_action(DC, "set_parent", "T-2", "E-1", http=fake_http)
    apply_action(DC, "add_link", "T-3", "X-9", http=fake_http)
    assert [c["method"] for c in fake_http.calls] == ["PUT", "PUT", "POST"]
    assert fake_http.calls[1]["body"] == {
        "fields": {"customfield_10014": "E-1"}}


def test_issue_key_is_url_escaped_on_datacenter(fake_http):
    fake_http.add("PUT", "/rest/api/2/issue/A%20B%2F1", {})
    set_parent(DC, "A B/1", "E-2", http=fake_http)
    assert "/rest/api/2/issue/A%20B%2F1" in fake_http.calls[0]["url"]

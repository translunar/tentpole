import base64
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from tentpole.adapters.config import (JiraConfig, SmartsheetConfig,
                                      load_config)

FULL = """
jira:
  base_url: https://example.atlassian.net/
  email: juno@example.com
  token_env_var: JIRA_TOKEN
  scope_jql: project = ABC
  projects: [ABC, XYZ]
  board_id: 42
core:
  team: [ada, grace]
smartsheet:
  base_url: https://api.smartsheetgov.com/2.0
  token_env_var: SS_TOKEN
  sheets:
    issues: 111
    epics: 222
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "tentpole.yaml"
    p.write_text(text)
    return p


def test_loads_both_sections_and_core(tmp_path):
    env = {"JIRA_TOKEN": "jt", "SS_TOKEN": "st"}
    cfg = load_config(_write(tmp_path, FULL), env=env)
    assert cfg.jira.base_url == "https://example.atlassian.net"
    assert cfg.jira.token == "jt"
    assert cfg.jira.projects == ("ABC", "XYZ")
    assert cfg.smartsheet.base_url == "https://api.smartsheetgov.com/2.0"
    assert cfg.smartsheet.sheets == {"issues": 111, "epics": 222}
    assert cfg.core == {"team": ["ada", "grace"]}


def test_defaults(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env_var: T\n  scope_jql: project = A\n")
    cfg = load_config(_write(tmp_path, text), env={"T": "tok"})
    assert cfg.jira.sprint_field == "customfield_10020"
    assert cfg.jira.hours_per_day == 8.0
    assert cfg.jira.projects == ()
    assert cfg.smartsheet is None
    assert cfg.core == {}


def test_smartsheet_default_base_url(tmp_path):
    text = ("smartsheet:\n  token_env_var: S\n  sheets:\n    issues: 1\n")
    cfg = load_config(_write(tmp_path, text), env={"S": "tok"})
    assert cfg.smartsheet.base_url == "https://api.smartsheet.com/2.0"
    assert cfg.jira is None


def test_missing_token_env_raises(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env_var: NOPE\n  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="NOPE"):
        load_config(_write(tmp_path, text), env={})


def test_token_not_in_repr(tmp_path):
    """Verify that API tokens are excluded from repr to prevent leaks in
    tracebacks, pytest --showlocals, or print() calls."""
    secret_jira_token = "SUPERSECRET-JIRA-TOKEN-VALUE"
    secret_ss_token = "SUPERSECRET-SS-TOKEN-VALUE"
    env = {"JIRA_TOKEN": secret_jira_token, "SS_TOKEN": secret_ss_token}
    cfg = load_config(_write(tmp_path, FULL), env=env)

    # Verify tokens are NOT in repr of top-level AdapterConfig
    cfg_repr = repr(cfg)
    assert secret_jira_token not in cfg_repr
    assert secret_ss_token not in cfg_repr

    # Verify tokens are NOT in repr of individual config objects
    jira_repr = repr(cfg.jira)
    ss_repr = repr(cfg.smartsheet)
    assert secret_jira_token not in jira_repr
    assert secret_ss_token not in ss_repr

    # Verify useful information IS still in repr (so repr is not empty/useless)
    assert "base_url" in cfg_repr
    assert "https://example.atlassian.net" in jira_repr
    assert "https://api.smartsheetgov.com/2.0" in ss_repr

    # Verify tokens are still accessible as attributes (repr suppression
    # must not break access)
    assert cfg.jira.token == secret_jira_token
    assert cfg.smartsheet.token == secret_ss_token


def test_token_cannot_leak(tmp_path):
    env = {"JIRA_TOKEN": "jt-hunter2", "SS_TOKEN": "st-hunter2"}
    cfg = load_config(_write(tmp_path, FULL), env=env)
    for section in (cfg.jira, cfg.smartsheet):
        assert "hunter2" not in repr(section)
        assert "hunter2" not in str(section)
        assert "hunter2" not in str(asdict(section))
        with pytest.raises(TypeError):
            json.dumps(asdict(section))     # fail closed, never leak


def test_token_equality_and_reveal(tmp_path):
    env = {"JIRA_TOKEN": "jt", "SS_TOKEN": "st"}
    cfg = load_config(_write(tmp_path, FULL), env=env)
    assert cfg.jira.token == "jt"           # str comparison still works
    assert cfg.jira.token.reveal() == "jt"
    assert str(cfg.jira.token) == "Secret('***')"
    assert f"{cfg.jira.token}" == "Secret('***')"


def test_headers_reveal_real_token():
    from tentpole.adapters.jira_extract import _headers as jira_headers
    from tentpole.adapters.smartsheet_load import _headers as ss_headers
    j = JiraConfig(base_url="https://x.net", email="a@b.c", token="tok",
                   scope_jql="q")
    expected = base64.b64encode(b"a@b.c:tok").decode()
    assert jira_headers(j) == {"Authorization": f"Basic {expected}"}
    s = SmartsheetConfig(base_url="https://x/2.0", token="tok")
    assert ss_headers(s) == {"Authorization": "Bearer tok"}


def test_old_token_env_key_gets_actionable_rename_error(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env: T\n  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="token_env_var"):
        load_config(_write(tmp_path, text), env={"T": "tok"})


def test_missing_token_env_var_key_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="token_env_var"):
        load_config(_write(tmp_path, text), env={})


DC_YAML = """
jira:
  base_url: https://jira.internal.example.com
  deployment: datacenter
  token_env_var: JIRA_PAT
  epic_link_field: customfield_10014
  scope_jql: project = ABC
  projects: [ABC]
  board_id: 7
"""


def test_deployment_defaults_to_cloud(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env_var: T\n  scope_jql: project = A\n")
    cfg = load_config(_write(tmp_path, text), env={"T": "tok"})
    assert cfg.jira.deployment == "cloud"
    assert cfg.jira.epic_link_field is None


def test_datacenter_config_needs_no_email(tmp_path):
    cfg = load_config(_write(tmp_path, DC_YAML), env={"JIRA_PAT": "pat"})
    assert cfg.jira.deployment == "datacenter"
    assert cfg.jira.email is None
    assert cfg.jira.epic_link_field == "customfield_10014"
    assert cfg.jira.token == "pat"


def test_cloud_without_email_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  token_env_var: T\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="email"):
        load_config(_write(tmp_path, text), env={"T": "tok"})


def test_datacenter_without_epic_link_field_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n"
            "  deployment: datacenter\n  token_env_var: T\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="epic_link_field"):
        load_config(_write(tmp_path, text), env={"T": "tok"})


def test_unknown_deployment_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  deployment: onprem\n  token_env_var: T\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="onprem"):
        load_config(_write(tmp_path, text), env={"T": "tok"})

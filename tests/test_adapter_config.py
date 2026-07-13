from pathlib import Path

import pytest

from tentpole.adapters.config import load_config

FULL = """
jira:
  base_url: https://example.atlassian.net/
  email: juno@example.com
  token_env: JIRA_TOKEN
  scope_jql: project = ABC
  projects: [ABC, XYZ]
  board_id: 42
core:
  team: [ada, grace]
smartsheet:
  base_url: https://api.smartsheetgov.com/2.0
  token_env: SS_TOKEN
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
            "  token_env: T\n  scope_jql: project = A\n")
    cfg = load_config(_write(tmp_path, text), env={"T": "tok"})
    assert cfg.jira.sprint_field == "customfield_10020"
    assert cfg.jira.hours_per_day == 8.0
    assert cfg.jira.projects == ()
    assert cfg.smartsheet is None
    assert cfg.core == {}


def test_smartsheet_default_base_url(tmp_path):
    text = ("smartsheet:\n  token_env: S\n  sheets:\n    issues: 1\n")
    cfg = load_config(_write(tmp_path, text), env={"S": "tok"})
    assert cfg.smartsheet.base_url == "https://api.smartsheet.com/2.0"
    assert cfg.jira is None


def test_missing_token_env_raises(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env: NOPE\n  scope_jql: project = A\n")
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

"""Adapter configuration: tentpole.yaml plus tokens from the
environment (never stored in the file). Adapters are the I/O edge
(spec section 3); the core never reads this."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    token: str = field(repr=False)
    scope_jql: str
    projects: tuple[str, ...] = ()
    board_id: int | None = None
    sprint_field: str = "customfield_10020"
    hours_per_day: float = 8.0
    programs_file: str | None = None


@dataclass(frozen=True)
class SmartsheetConfig:
    base_url: str
    token: str = field(repr=False)
    sheets: dict[str, int] = field(default_factory=dict)
    workspace_id: int | None = None


@dataclass(frozen=True)
class AdapterConfig:
    jira: JiraConfig | None
    smartsheet: SmartsheetConfig | None
    core: dict = field(default_factory=dict)


def _token(section: dict, env: dict) -> str:
    var = section["token_env"]
    if var not in env:
        raise ValueError(
            f"environment variable {var!r} (named by token_env) is not "
            f"set")
    return env[var]


def load_config(path: Path, env: dict | None = None) -> AdapterConfig:
    env = dict(os.environ) if env is None else env
    raw = yaml.safe_load(Path(path).read_text()) or {}
    jira = None
    if "jira" in raw:
        j = raw["jira"]
        jira = JiraConfig(
            base_url=j["base_url"].rstrip("/"),
            email=j["email"],
            token=_token(j, env),
            scope_jql=j["scope_jql"],
            projects=tuple(j.get("projects", [])),
            board_id=j.get("board_id"),
            sprint_field=j.get("sprint_field", "customfield_10020"),
            hours_per_day=float(j.get("hours_per_day", 8.0)),
            programs_file=j.get("programs_file"),
        )
    smartsheet = None
    if "smartsheet" in raw:
        s = raw["smartsheet"]
        smartsheet = SmartsheetConfig(
            base_url=s.get("base_url",
                           "https://api.smartsheet.com/2.0").rstrip("/"),
            token=_token(s, env),
            sheets={k: int(v) for k, v in s.get("sheets", {}).items()},
            workspace_id=s.get("workspace_id"),
        )
    return AdapterConfig(jira=jira, smartsheet=smartsheet,
                         core=raw.get("core", {}))

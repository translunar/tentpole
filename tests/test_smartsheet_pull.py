import json
import urllib.request
from pathlib import Path

import pytest

from tentpole.adapters.config import SmartsheetConfig
from tentpole.adapters.smartsheet_load import pull_sheet, pull_state
from tentpole.cli import main

CFG = SmartsheetConfig(base_url="https://api.smartsheetgov.com/2.0",
                       token="t", sheets={"issues": 111})

SHEET = {
    "columns": [
        {"id": 10, "title": "Key", "primary": True},
        {"id": 11, "title": "Summary"},
        {"id": 12, "title": "In Jira"},
    ],
    "rows": [
        {"id": 900, "cells": [
            {"columnId": 10, "value": "E-1"},
            {"columnId": 11, "value": "Epic one"}]},
        {"id": 901, "parentId": 900, "cells": [
            {"columnId": 10, "value": "T-1"},
            {"columnId": 11, "value": "Task"},
            {"columnId": 12, "value": True}]},
        {"id": 902, "cells": [{"columnId": 11, "value": "no key"}]},
    ],
}


def test_pull_sheet_maps_titles_values_and_hierarchy(fake_http):
    fake_http.add("GET", "/sheets/111", SHEET)
    state = pull_sheet(CFG, 111, http=fake_http)
    assert set(state) == {"E-1", "T-1"}          # keyless row skipped
    assert state["E-1"]["Summary"] == "Epic one"
    assert state["E-1"]["_row_id"] == 900
    assert state["E-1"]["_parent"] is None
    assert state["T-1"]["_parent"] == "E-1"
    assert state["T-1"]["In Jira"] is True
    assert "gov" in fake_http.calls[0]["url"]    # configured base URL


def test_pull_state_writes_files(tmp_path, fake_http):
    fake_http.add("GET", "/sheets/111", SHEET)
    pulled = pull_state(CFG, tmp_path, http=fake_http)
    assert pulled == ["issues"]
    on_disk = json.loads((tmp_path / "issues.json").read_text())
    assert on_disk["T-1"]["_parent"] == "E-1"


def test_pull_state_rejects_unknown_sheet_name(tmp_path, fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"mystery": 5})
    with pytest.raises(ValueError, match="mystery"):
        pull_state(cfg, tmp_path, http=fake_http)


def test_pull_sheet_empty_sheet(fake_http):
    fake_http.add("GET", "/sheets/111", {"columns": SHEET["columns"]})
    assert pull_sheet(CFG, 111, http=fake_http) == {}


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


def test_cli_pull_end_to_end(tmp_path, monkeypatch):
    # Drives the real `tentpole pull ...` entry point (argparse ->
    # adapters/cli.dispatch -> _pull -> pull_state -> write JSON)
    # so a wiring bug -- a typo'd args.<attr>, a swapped positional in
    # pull_state(...), a mis-routed dispatch -- fails this test instead
    # of surfacing only on the user's first real invocation. No network:
    # the fake sits at urllib.request.urlopen, the one seam that is a
    # live attribute lookup rather than a bound default, so no
    # production code changes were needed to inject it.
    monkeypatch.setenv("SS_TOKEN", "secret-token")
    config_path = tmp_path / "tentpole.yaml"
    config_path.write_text(
        "smartsheet:\n"
        "  base_url: https://api.smartsheetgov.com/2.0\n"
        "  token_env_var: SS_TOKEN\n"
        "  sheets:\n"
        "    issues: 111\n"
    )
    state_dir = tmp_path / "state"

    routes = [
        ("GET", "/sheets/111", SHEET),
    ]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))

    exit_code = main(["pull", "--config", str(config_path),
                      "--state", str(state_dir)])

    assert exit_code == 0
    on_disk = json.loads((state_dir / "issues.json").read_text())
    assert "E-1" in on_disk
    assert "T-1" in on_disk
    assert on_disk["T-1"]["_parent"] == "E-1"
    assert on_disk["T-1"]["_row_id"] == 901

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
    # Two GETs on /sheets/111: pull_sheet, then _dependencies_enabled.
    fake_http.add("GET", "/sheets/111", SHEET)
    fake_http.add("GET", "/sheets/111", SHEET)
    report = pull_state(CFG, tmp_path, http=fake_http)
    assert report["issues"]["state"] == "SYNCED"
    assert report["issues"]["sheet_id"] == 111
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


def test_pull_sheet_human_qualifies_child_keys(fake_http):
    # A people-shaped sheet: two people each with a "PTO" child. Bare-primary
    # keying would collapse both PTO rows; parent-qualified keying keeps them.
    sheet = {
        "columns": [
            {"id": 1, "title": "Item", "primary": True},
            {"id": 2, "title": "Days"},
        ],
        "rows": [
            {"id": 100, "cells": [{"columnId": 1, "value": "ada"}]},
            {"id": 101, "parentId": 100,
             "cells": [{"columnId": 1, "value": "PTO"},
                       {"columnId": 2, "value": 4}]},
            {"id": 200, "cells": [{"columnId": 1, "value": "grace"}]},
            {"id": 201, "parentId": 200,
             "cells": [{"columnId": 1, "value": "PTO"},
                       {"columnId": 2, "value": 2}]},
        ],
    }
    fake_http.add("GET", "/sheets/55", sheet)
    state = pull_sheet(CFG, 55, http=fake_http, sheet_name="people",
                       human=True)
    assert set(state) == {"ada", "grace", "ada|PTO", "grace|PTO"}
    assert state["ada|PTO"]["Days"] == 4
    assert state["ada|PTO"]["_parent"] == "ada"
    assert state["grace|PTO"]["Days"] == 2


def test_pull_sheet_human_duplicate_key_raises(fake_http):
    # Two roots with the same primary (the filed future_work "Migrate DB" bug).
    sheet = {
        "columns": [{"id": 1, "title": "Title", "primary": True}],
        "rows": [
            {"id": 1, "cells": [{"columnId": 1, "value": "Migrate DB"}]},
            {"id": 2, "cells": [{"columnId": 1, "value": "Migrate DB"}]},
        ],
    }
    fake_http.add("GET", "/sheets/55", sheet)
    with pytest.raises(ValueError, match="Migrate DB"):
        pull_sheet(CFG, 55, http=fake_http, sheet_name="future_work",
                   human=True)


def test_pull_sheet_human_duplicate_child_pair_raises(fake_http):
    # Same (person, item) twice -> duplicate qualified key "ada|PTO".
    sheet = {
        "columns": [{"id": 1, "title": "Item", "primary": True}],
        "rows": [
            {"id": 100, "cells": [{"columnId": 1, "value": "ada"}]},
            {"id": 101, "parentId": 100,
             "cells": [{"columnId": 1, "value": "PTO"}]},
            {"id": 102, "parentId": 100,
             "cells": [{"columnId": 1, "value": "PTO"}]},
        ],
    }
    fake_http.add("GET", "/sheets/55", sheet)
    with pytest.raises(ValueError, match="ada.PTO"):
        pull_sheet(CFG, 55, http=fake_http, sheet_name="people", human=True)


def test_pull_sheet_machine_keys_stay_bare_and_byte_identical(fake_http):
    # Machine sheet (human=False, the default): children keep bare keys so
    # change-planning against issues is unaffected (spec §11).
    fake_http.add("GET", "/sheets/111", SHEET)
    state = pull_sheet(CFG, 111, http=fake_http)
    assert set(state) == {"E-1", "T-1"}          # NOT "E-1|T-1"
    assert state["T-1"]["_parent"] == "E-1"


def test_pull_state_discovers_by_name_and_skips_off(tmp_path, fake_http):
    from tentpole.adapters.smartsheet_load import pull_state
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=999)
    ws = {"sheets": [{"id": 111, "name": "issues"}]}   # only issues present
    fake_http.add("GET", "/workspaces/999", ws)
    # Two GETs on /sheets/111: pull_sheet, then _dependencies_enabled.
    fake_http.add("GET", "/sheets/111", SHEET)
    fake_http.add("GET", "/sheets/111", SHEET)
    report = pull_state(cfg, tmp_path, http=fake_http)
    assert report["issues"]["state"] == "SYNCED"
    assert report["people"]["state"] == "OFF"          # discovered nothing
    assert (tmp_path / "issues.json").exists()
    # OFF human sheets (people, future_work) wrote no state file -> cli
    # falls back to yaml / none.
    assert not (tmp_path / "people.json").exists()


def test_pull_state_off_unlinks_stale_state_file(tmp_path, fake_http):
    # A prior pull wrote people.json while the people sheet existed; the
    # sheet was then renamed/deleted so it now resolves OFF. The stale file
    # must be removed, not left behind to be silently read as authoritative
    # by a later `sync` (the documented OFF -> yaml fallback would otherwise
    # be defeated).
    (tmp_path / "people.json").write_text(json.dumps({"stale": "data"}))
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=999)
    ws = {"sheets": [{"id": 111, "name": "issues"}]}   # only issues present
    fake_http.add("GET", "/workspaces/999", ws)
    # Two GETs on /sheets/111: pull_sheet, then _dependencies_enabled.
    fake_http.add("GET", "/sheets/111", SHEET)
    fake_http.add("GET", "/sheets/111", SHEET)
    report = pull_state(cfg, tmp_path, http=fake_http)
    assert report["people"]["state"] == "OFF"
    assert not (tmp_path / "people.json").exists()


def test_cli_pull_enumerates_off_schemas(tmp_path, monkeypatch, capsys):
    # Spec §2: `pull` prints one line per known schema. A human sheet that
    # goes OFF must say so (it silently switches to the yaml fallback).
    monkeypatch.setenv("SS_TOKEN", "secret-token")
    config_path = tmp_path / "tentpole.yaml"
    config_path.write_text(
        "smartsheet:\n"
        "  base_url: https://api.smartsheetgov.com/2.0\n"
        "  token_env_var: SS_TOKEN\n"
        "  workspace_id: 999\n")
    ws = {"sheets": [{"id": 111, "name": "issues"}]}   # only issues present
    routes = [("GET", "/workspaces/999", ws), ("GET", "/sheets/111", SHEET)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    exit_code = main(["pull", "--config", str(config_path),
                      "--state", str(tmp_path / "state")])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "issues: SYNCED sheet 111" in out
    assert "people: OFF" in out
    assert "falls back to yaml" in out                 # human fallback note


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


def test_pull_state_records_issues_dependencies_flag(tmp_path, fake_http):
    from tentpole.adapters.smartsheet_load import pull_state
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111})
    # Two GETs on /sheets/111: pull_sheet, then _dependencies_enabled.
    sheet = dict(SHEET)
    sheet["dependenciesEnabled"] = True
    fake_http.add("GET", "/sheets/111", sheet)
    fake_http.add("GET", "/sheets/111", sheet)
    pull_state(cfg, tmp_path, http=fake_http)
    settings = json.loads((tmp_path / "settings.json").read_text())
    assert settings["issues"]["dependencies_enabled"] is True


def test_pull_state_off_unlinks_stale_settings_file(tmp_path, fake_http):
    # A prior pull wrote settings.json with dependencies_enabled=True while
    # the issues sheet existed; the sheet was then renamed/deleted so it now
    # resolves OFF. The stale gantt flag must not survive -- otherwise a
    # later `sync` would read gantt=True from a sheet that no longer exists,
    # silently defeating the OFF fallback (same rationale as the stale
    # {name}.json unlink covered above; commit d13f4f7's P6 fail-loud fix).
    (tmp_path / "settings.json").write_text(
        json.dumps({"issues": {"dependencies_enabled": True}}))
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=999)
    ws = {"sheets": []}   # issues absent -> resolves OFF
    fake_http.add("GET", "/workspaces/999", ws)
    report = pull_state(cfg, tmp_path, http=fake_http)
    assert report["issues"]["state"] == "OFF"
    assert not (tmp_path / "settings.json").exists()

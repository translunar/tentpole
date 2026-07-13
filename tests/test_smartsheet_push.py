import json
import urllib.request

import pytest

from tentpole.adapters.config import SmartsheetConfig
from tentpole.adapters.smartsheet_load import push_plan, push_plans
from tentpole.cli import main
from tentpole.schema import SCHEMAS

CFG = SmartsheetConfig(base_url="https://x/2.0", token="t",
                       sheets={"issues": 111})

ISSUES_SCHEMA = SCHEMAS["issues"]

# FINDING 1 fixture correction: this must present a COMPLETE,
# schema-conformant set of columns for the "issues" schema (17 columns),
# not a 3-column subset -- a subset used to let push_plan silently drop
# every cell for the missing columns. "Summary" (11) and "In Jira" (12)
# keep their original ids because several tests below assert those exact
# columnId values.
COLS = {"columns": [
    {"id": 10, "title": "Key", "primary": True},
    {"id": 11, "title": "Summary"},
    {"id": 20, "title": "Type"},
    {"id": 21, "title": "Status"},
    {"id": 22, "title": "Assignee"},
    {"id": 23, "title": "Original Est"},
    {"id": 24, "title": "Remaining Est"},
    {"id": 25, "title": "Epic"},
    {"id": 26, "title": "Fix Versions"},
    {"id": 27, "title": "Sprint"},
    {"id": 28, "title": "Program"},
    {"id": 29, "title": "Blocked By"},
    {"id": 30, "title": "Blocks"},
    {"id": 31, "title": "Hygiene"},
    {"id": 32, "title": "In Progress"},
    {"id": 33, "title": "Done"},
    {"id": 12, "title": "In Jira"},
]}


def _add(key, cells, parent=None):
    return {"op": "add", "key": key, "cells": cells,
            "parent_key": parent}


def test_adds_in_two_waves_parents_first(fake_http):
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("POST", "/sheets/111/rows",
                  {"message": "SUCCESS",
                   "result": [{"id": 900}]})
    fake_http.add("POST", "/sheets/111/rows",
                  {"message": "SUCCESS",
                   "result": [{"id": 901}]})
    changes = [_add("T-1", {"Summary": "t"}, parent="E-1"),
               _add("E-1", {"Summary": "e"})]
    result = push_plan(CFG, 111, changes, {}, ISSUES_SCHEMA, http=fake_http)
    assert result["added"] == 2 and result["failed"] == []
    wave1 = fake_http.calls[1]["body"]
    wave2 = fake_http.calls[2]["body"]
    assert wave1[0]["cells"] == [{"columnId": 11, "value": "e"}]
    assert wave1[0]["toBottom"] is True
    assert wave2[0]["parentId"] == 900       # E-1's new row id
    assert fake_http.calls[1]["params"]["allowPartialSuccess"] == "true"


def test_partial_success_reports_failures(fake_http):
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("POST", "/sheets/111/rows",
                  {"message": "PARTIAL_SUCCESS",
                   "result": [{"id": 900}],
                   "failedItems": [
                       {"index": 1,
                        "error": {"message": "bad value"}}]})
    changes = [_add("A-1", {"Summary": "ok"}),
               _add("A-2", {"Summary": "bad"})]
    result = push_plan(CFG, 111, changes, {}, ISSUES_SCHEMA, http=fake_http)
    assert result["added"] == 1
    assert result["failed"] == [
        {"op": "add", "key": "A-2", "error": "bad value"}]


def test_updates_and_flag_gone_share_bulk_put(fake_http):
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("PUT", "/sheets/111/rows",
                  {"message": "SUCCESS", "result": []})
    state = {"T-1": {"_row_id": 900, "_parent": None},
             "T-2": {"_row_id": 901, "_parent": None}}
    changes = [
        {"op": "update", "key": "T-1", "cells": {"Summary": "new"},
         "parent_key": None},
        {"op": "flag_gone", "key": "T-2",
         "cells": {"In Jira": False}, "parent_key": None},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    assert result["updated"] == 2
    body = fake_http.calls[1]["body"]
    assert body[0] == {"id": 900,
                       "cells": [{"columnId": 11, "value": "new"}]}
    assert body[1] == {"id": 901,
                       "cells": [{"columnId": 12, "value": False}]}


def test_reparent_is_a_separate_put_wave(fake_http):
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("PUT", "/sheets/111/rows",
                  {"message": "SUCCESS", "result": []})
    state = {"T-1": {"_row_id": 900, "_parent": "E-1"},
             "E-2": {"_row_id": 800, "_parent": None},
             "T-9": {"_row_id": 901, "_parent": "E-2"}}
    changes = [
        {"op": "update", "key": "T-1", "cells": {},
         "parent_key": "E-2"},
        {"op": "update", "key": "T-9", "cells": {}, "parent_key": ""},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    body = fake_http.calls[1]["body"]
    assert body == [{"id": 900, "parentId": 800},
                    {"id": 901, "parentId": None}]
    assert result["updated"] == 0            # location-only changes


def test_removes_and_missing_rows(fake_http):
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("DELETE", "/sheets/111/rows", {"message": "SUCCESS"})
    state = {"C-1": {"_row_id": 700, "_parent": None}}
    changes = [
        {"op": "remove", "key": "C-1", "cells": None,
         "parent_key": None},
        {"op": "update", "key": "GHOST", "cells": {"Summary": "x"},
         "parent_key": None},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    assert result["removed"] == 1
    assert fake_http.calls[1]["params"]["ids"] == "700"
    assert result["failed"] == [
        {"op": "update", "key": "GHOST",
         "error": "row not found in sheet state"}]


def test_cli_push_exits_nonzero_on_failures(tmp_path, monkeypatch,
                                            capsys):
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")
    import tentpole.adapters.cli as edge_cli

    def fake_push_plans(cfg, plans, state):
        return {"issues": {"added": 0, "updated": 1, "removed": 0,
                           "failed": [{"op": "add", "key": "A-1",
                                       "error": "boom"}]}}
    monkeypatch.setattr(edge_cli.smartsheet_load, "push_plans",
                        fake_push_plans)
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(tmp_path), "--state", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "A-1" in out and "boom" in out


def test_reparent_put_failure_caught_and_reported(fake_http):
    """Verify that reparent PUT failures are captured in result["failed"]
    and drive a nonzero exit code. This tests the MANDATORY FIX: the
    reparent wave must tally its failures like adds/updates do."""
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("PUT", "/sheets/111/rows",
                  {"message": "PARTIAL_SUCCESS",
                   "result": [],
                   "failedItems": [
                       {"index": 0,
                        "error": {"message": "bad parentId"}}]})
    state = {"T-1": {"_row_id": 900, "_parent": "E-1"},
             "E-99": {"_row_id": 9999, "_parent": None}}
    changes = [
        {"op": "update", "key": "T-1", "cells": {},
         "parent_key": "E-99"},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    # The reparent PUT came back with a failure; it must be in result["failed"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["op"] == "update"
    assert result["failed"][0]["key"] == "T-1"
    assert "bad parentId" in result["failed"][0]["error"]
    # updated should still be 0 (location-only change that failed)
    assert result["updated"] == 0


def test_delete_reports_actual_removed_count(fake_http):
    """FINDING 1: the DELETE wave must report what the API actually
    removed, not the requested count. ignoreRowsNotFound=true means
    rows already absent are silently skipped by Smartsheet -- if the
    API's response says fewer rows were removed than requested, that
    must show up in result["removed"]."""
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("DELETE", "/sheets/111/rows",
                  {"message": "SUCCESS", "result": [700]})
    state = {"C-1": {"_row_id": 700, "_parent": None},
             "C-2": {"_row_id": 701, "_parent": None}}
    changes = [
        {"op": "remove", "key": "C-1", "cells": None,
         "parent_key": None},
        {"op": "remove", "key": "C-2", "cells": None,
         "parent_key": None},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    # Two rows were requested for deletion but the API only reports one
    # actually removed (C-2 was presumably already gone).
    assert result["removed"] == 1


def test_reparent_unresolved_target_not_silently_root(fake_http):
    """FINDING 2: a reparent whose target key does not resolve in
    row_ids must NOT silently fall back to moving the row to root
    (parentId: null). It must be refused and recorded as a failure --
    no PUT may be issued for it."""
    fake_http.add("GET", "/sheets/111", COLS)
    state = {"T-1": {"_row_id": 900, "_parent": "E-1"}}
    changes = [
        {"op": "update", "key": "T-1", "cells": {},
         "parent_key": "GHOST-EPIC"},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    assert result["updated"] == 0
    assert len(result["failed"]) == 1
    assert result["failed"][0]["op"] == "update"
    assert result["failed"][0]["key"] == "T-1"
    assert "GHOST-EPIC" in result["failed"][0]["error"]
    # Only the initial GET (column ids) happened -- no reparent PUT was
    # issued for an unresolvable target. (fake_http raises on any
    # unqueued request, so an issued-but-unexpected PUT would already
    # have failed this test above; this just makes it explicit.)
    assert len(fake_http.calls) == 1


def _fake_urlopen(routes):
    class _Resp:
        def __init__(self, payload):
            self.status = 200
            self.headers = {}
            self._body = json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body

    def _urlopen(req, *args, **kwargs):
        method = req.get_method()
        url = req.full_url
        for want_method, want_path, payload in routes:
            if want_method == method and want_path in url:
                return _Resp(payload)
        raise AssertionError(f"unexpected request: {method} {url}")
    return _urlopen


def test_cli_push_reparent_failure_drives_nonzero_exit(tmp_path,
                                                        monkeypatch,
                                                        capsys):
    """FINDING 2, CLI-level: an unresolvable reparent target must not
    just land in result["failed"] -- it has to reach the real `tentpole
    push` exit code, end to end through the actual push_plan logic (not
    a stubbed push_plans like test_cli_push_exits_nonzero_on_failures
    uses)."""
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")

    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text(json.dumps([
        {"op": "update", "key": "T-1", "cells": {},
         "parent_key": "GHOST-EPIC"},
    ]))
    (state_dir / "issues.json").write_text(json.dumps({
        "T-1": {"_row_id": 900, "_parent": "E-1"},
    }))

    routes = [("GET", "/sheets/1", COLS)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))

    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 1
    assert "T-1" in out
    assert "GHOST-EPIC" in out


def test_remove_missing_row_recorded_as_failure(fake_http):
    """FINDING 3: a `remove` whose key is not in row_ids must record a
    failure, symmetric with update/flag_gone, rather than being
    silently dropped from the DELETE batch."""
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("DELETE", "/sheets/111/rows",
                  {"message": "SUCCESS", "result": [700]})
    state = {"C-1": {"_row_id": 700, "_parent": None}}
    changes = [
        {"op": "remove", "key": "C-1", "cells": None,
         "parent_key": None},
        {"op": "remove", "key": "GHOST", "cells": None,
         "parent_key": None},
    ]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA, http=fake_http)
    assert result["removed"] == 1
    assert result["failed"] == [
        {"op": "remove", "key": "GHOST",
         "error": "row not found in sheet state"}]
    # The DELETE call only referenced the resolvable row.
    assert fake_http.calls[1]["params"]["ids"] == "700"


# --- review round: missing-column and unconfigured-sheet findings -----

def test_push_plan_raises_on_missing_synced_column(fake_http):
    """REVIEW FINDING 1: a column the schema expects (e.g. a human
    typo'd "Remaining Est" while hand-building the sheet from `tentpole
    schema show`) but that is absent from the live sheet must fail
    loudly. Previously `_cells_payload`'s `name in col_ids` guard
    silently dropped every cell for that column on every add/update
    while still tallying the row as a success -- the sync never
    converged and capacity planning silently ran on blanks."""
    bad_cols = {"columns": [c for c in COLS["columns"]
                            if c["title"] != "Remaining Est"]}
    fake_http.add("GET", "/sheets/111", bad_cols)
    with pytest.raises(ValueError, match="Remaining Est"):
        push_plan(CFG, 111, [], {}, ISSUES_SCHEMA, http=fake_http)


def test_cli_push_missing_column_exits_nonzero(tmp_path, monkeypatch,
                                               capsys):
    """REVIEW FINDING 1, CLI-level: the missing-column failure must
    reach the real `tentpole push` exit code end to end, not just show
    up in an intermediate dict."""
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")

    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text(json.dumps([
        {"op": "update", "key": "T-1",
         "cells": {"Remaining Est": 3.0}, "parent_key": None},
    ]))
    (state_dir / "issues.json").write_text(json.dumps({
        "T-1": {"_row_id": 900, "_parent": None},
    }))

    bad_cols = {"columns": [c for c in COLS["columns"]
                            if c["title"] != "Remaining Est"]}
    routes = [("GET", "/sheets/1", bad_cols)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))

    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 1
    assert "issues" in out
    assert "Remaining Est" in out


def test_push_plans_skips_sheet_without_configured_id(tmp_path, fake_http):
    """REVIEW FINDING 2: `sync` writes a plan for every machine sheet,
    but a sheet absent from tentpole.yaml's `sheets:` (e.g. the
    README Quickstart config, which lists only "issues" and "epics")
    must not have its plan silently dropped -- it must show up in the
    report as an explicit failure naming the sheet."""
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111})   # "epics" absent
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    (plans_dir / "epics.json").write_text(json.dumps([
        {"op": "add", "key": "E-1", "cells": {"Summary": "e"},
         "parent_key": None}]))
    fake_http.add("GET", "/sheets/111", COLS)
    report = push_plans(cfg, plans_dir, state_dir, http=fake_http)
    assert "epics" in report
    assert report["epics"]["failed"]
    error = report["epics"]["failed"][0]["error"]
    assert "SKIPPED" in error and "epics" in error


def test_cli_push_missing_sheet_id_exits_nonzero(tmp_path, monkeypatch,
                                                 capsys):
    """REVIEW FINDING 2, CLI-level: a plan for a sheet with no
    configured id must reach the real `tentpole push` exit code, not
    just an intermediate report dict."""
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")

    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    (plans_dir / "epics.json").write_text("[]")

    routes = [("GET", "/sheets/1", COLS)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))

    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 1
    assert "epics" in out
    assert "SKIPPED" in out


def _cols_for(name, drop=None):
    cols = []
    for i, c in enumerate(SCHEMAS[name].columns):
        col = {"id": 500 + i, "title": c.name}
        if c.primary:
            col["primary"] = True
        cols.append(col)
    if drop:
        cols = [c for c in cols if c["title"] != drop]
    return {"columns": cols}


def test_preflight_validates_every_sheet_before_first_write(
        tmp_path, fake_http):
    # issues (first in SCHEMAS order) is valid; epics is missing a
    # column. Without pre-flight, issues would be WRITTEN before the
    # epics mismatch aborted the loop.
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111, "epics": 222})
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("GET", "/sheets/222", _cols_for("epics", drop="Runway"))
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "issues.json").write_text(
        json.dumps([_add("T-1", {"Summary": "s"})]))
    (plans / "epics.json").write_text(
        json.dumps([_add("E-1", {"Summary": "e"})]))
    (tmp_path / "state").mkdir()
    with pytest.raises(ValueError, match="Runway"):
        push_plans(cfg, plans, tmp_path / "state", http=fake_http)
    assert all(c["method"] == "GET" for c in fake_http.calls)

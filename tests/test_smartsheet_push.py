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
    {"id": 34, "title": "Deadline"},
    {"id": 35, "title": "Open Tickets"},
    {"id": 36, "title": "Remaining Days"},
    {"id": 37, "title": "People"},
    {"id": 38, "title": "Runway"},
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
        "smartsheet:\n  token_env_var: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")
    import tentpole.adapters.cli as edge_cli

    def fake_push_plans(cfg, plans, state):
        return {"issues": {"state": "SYNCED", "sheet_id": 1,
                           "added": 0, "updated": 1, "removed": 0,
                           "failed": [{"op": "add", "key": "A-1",
                                       "error": "boom"}]}}
    monkeypatch.setattr(edge_cli.smartsheet_load, "push_plans",
                        fake_push_plans)
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(tmp_path), "--state", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "A-1" in out and "boom" in out


def test_cli_old_token_env_config_prints_actionable_error_not_traceback(
        tmp_path, capsys):
    """FINAL REVIEW FIX: every edge handler calls load_config() outside
    its own try/except, so a 0.2.1 config still using the renamed
    token_env key must not surface as a bare traceback -- dispatch()
    now catches ValueError from load_config the same way _push already
    catches ValueError from push_plans."""
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env: S\n  sheets:\n    issues: 1\n")
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(tmp_path), "--state", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "ERROR:" in out
    assert "token_env_var" in out


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
        "smartsheet:\n  token_env_var: S\n  sheets:\n    issues: 1\n")
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
        "smartsheet:\n  token_env_var: S\n  sheets:\n    issues: 1\n")
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


def test_push_plans_reports_off_for_unresolved_sheet(tmp_path, fake_http):
    # A machine schema with no explicit id and no workspace match resolves
    # OFF -- a normal state printed every run (spec §2), not a failure.
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111})   # no workspace, no fixversions
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    (plans_dir / "fixversions.json").write_text(json.dumps([
        {"op": "add", "key": "v1", "cells": {"Version": "v1"},
         "parent_key": None}]))
    fake_http.add("GET", "/sheets/111", COLS)
    report = push_plans(cfg, plans_dir, state_dir, http=fake_http)
    assert report["issues"]["state"] == "SYNCED"
    assert report["fixversions"]["state"] == "OFF"
    assert report["fixversions"]["failed"] == []


def test_cli_push_off_sheet_exits_zero_and_enumerates(tmp_path, monkeypatch,
                                                      capsys):
    # OFF is exit 0 (spec §2): the old SKIPPED+exit-1 behavior is removed.
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    (plans_dir / "fixversions.json").write_text("[]")
    routes = [("GET", "/sheets/1", COLS)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "fixversions: OFF" in out
    assert "issues: SYNCED" in out


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
    # issues (first in SCHEMAS order) is valid; fixversions is missing a
    # column. Without pre-flight, issues would be WRITTEN before the
    # fixversions mismatch aborted the loop.
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111, "fixversions": 222})
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("GET", "/sheets/222",
                  _cols_for("fixversions", drop="Risk"))
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "issues.json").write_text(
        json.dumps([_add("T-1", {"Summary": "s"})]))
    (plans / "fixversions.json").write_text(
        json.dumps([_add("v1", {"Version": "v1"})]))
    (tmp_path / "state").mkdir()
    with pytest.raises(ValueError, match="Risk"):
        push_plans(cfg, plans, tmp_path / "state", http=fake_http)
    assert all(c["method"] == "GET" for c in fake_http.calls)


# Documented (unverified) shape of GET /workspaces/{id}. The gantt/predecessor
# and this listing shape get a SmartsheetGov smoke before the README drops the
# experimental label (spec §2, §11).
WORKSPACE = {"id": 999, "name": "Planning", "sheets": [
    {"id": 1234, "name": "issues"},
    {"id": 5678, "name": "capacity"},
    {"id": 4321, "name": "dashboard"},        # not a schema name -> ignored
]}


def test_resolve_explicit_id_beats_discovery(fake_http):
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111}, workspace_id=999)
    fake_http.add("GET", "/workspaces/999", WORKSPACE)
    resolved = resolve_sheets(cfg, http=fake_http)
    assert resolved["issues"] == 111          # explicit id wins over 1234
    assert resolved["capacity"] == 5678       # discovered by name
    assert resolved["fixversions"] is None    # OFF


def test_resolve_no_workspace_no_sheets_all_off(fake_http):
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    resolved = resolve_sheets(cfg, http=fake_http)     # no HTTP call at all
    assert set(resolved) == set(SCHEMAS)
    assert all(v is None for v in resolved.values())
    assert fake_http.calls == []


def test_resolve_ambiguous_duplicate_name_raises(fake_http):
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=999)
    ws = {"sheets": [{"id": 1, "name": "issues"},
                     {"id": 2, "name": "issues"}]}
    fake_http.add("GET", "/workspaces/999", ws)
    with pytest.raises(ValueError, match="issues"):
        resolve_sheets(cfg, http=fake_http)


def test_resolve_sheets_rejects_unknown_explicit_key(fake_http):
    # The unknown-explicit-key guard (preserved from pull_state, spec §2/§8):
    # a typo'd key under smartsheet.sheets must raise before any HTTP.
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"mystery": 5})
    with pytest.raises(ValueError, match="mystery"):
        resolve_sheets(cfg, http=fake_http)
    assert fake_http.calls == []          # raised before touching the network


def test_cli_push_expect_miss_exits_nonzero_with_present_names(
        tmp_path, monkeypatch, capsys):
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  workspace_id: 999\n"
        "  expect: [capacity]\n")
    monkeypatch.setenv("S", "tok")
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    # Workspace has issues but NOT capacity -> expect miss.
    ws = {"sheets": [{"id": 1234, "name": "issues"}]}
    routes = [("GET", "/workspaces/999", ws)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 1
    assert "ERROR:" in out
    assert "capacity" in out
    assert "issues" in out          # names the sheets actually present


def test_update_with_cells_and_reparent_rides_both_waves(fake_http):
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("PUT", "/sheets/111/rows",
                  {"message": "SUCCESS", "result": []})
    fake_http.add("PUT", "/sheets/111/rows",
                  {"message": "SUCCESS", "result": []})
    state = {"T-1": {"_row_id": 900, "_parent": "E-1"},
             "E-2": {"_row_id": 800, "_parent": None}}
    changes = [{"op": "update", "key": "T-1",
                "cells": {"Summary": "new"}, "parent_key": "E-2"}]
    result = push_plan(CFG, 111, changes, state, ISSUES_SCHEMA,
                       http=fake_http)
    assert fake_http.calls[1]["body"] == [
        {"id": 900, "cells": [{"columnId": 11, "value": "new"}]}]
    assert fake_http.calls[2]["body"] == [{"id": 900, "parentId": 800}]
    assert result["updated"] == 1          # counted once, not twice
    assert result["failed"] == []


def test_cli_push_prints_epics_fold_hint(tmp_path, monkeypatch, capsys):
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  workspace_id: 999\n"
        "  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    ws = {"sheets": [{"id": 1, "name": "issues"},
                     {"id": 2, "name": "epics"}]}
    routes = [("GET", "/workspaces/999", ws), ("GET", "/sheets/1", COLS)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "folded into issues" in out

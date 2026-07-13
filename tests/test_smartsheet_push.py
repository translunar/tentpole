from tentpole.adapters.config import SmartsheetConfig
from tentpole.adapters.smartsheet_load import push_plan
from tentpole.cli import main

CFG = SmartsheetConfig(base_url="https://x/2.0", token="t",
                       sheets={"issues": 111})

COLS = {"columns": [
    {"id": 10, "title": "Key", "primary": True},
    {"id": 11, "title": "Summary"},
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
    result = push_plan(CFG, 111, changes, {}, http=fake_http)
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
    result = push_plan(CFG, 111, changes, {}, http=fake_http)
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
    result = push_plan(CFG, 111, changes, state, http=fake_http)
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
    result = push_plan(CFG, 111, changes, state, http=fake_http)
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
    result = push_plan(CFG, 111, changes, state, http=fake_http)
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
    result = push_plan(CFG, 111, changes, state, http=fake_http)
    # The reparent PUT came back with a failure; it must be in result["failed"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["op"] == "update"
    assert result["failed"][0]["key"] == "T-1"
    assert "bad parentId" in result["failed"][0]["error"]
    # updated should still be 0 (location-only change that failed)
    assert result["updated"] == 0

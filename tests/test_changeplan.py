import pytest

from tentpole.changeplan import plan_changes
from tentpole.schema import SCHEMAS
from tentpole.sheets import Row, SheetSpec


def _spec(*rows):
    return SheetSpec("issues", list(rows))


def _row(key, **cells):
    cells.setdefault("Key", key)
    cells.setdefault("In Jira", True)
    return Row(key, cells)


def test_adds_updates_and_flag_gone():
    spec = _spec(_row("T-1", Summary="new title", Status="todo"),
                 _row("T-2", Summary="brand new", Status="todo"))
    current = {
        "T-1": {"Key": "T-1", "Summary": "old title", "Status": "todo",
                "In Jira": True},
        "T-9": {"Key": "T-9", "Summary": "vanished", "In Jira": True},
    }
    changes = {(c.op, c.key): c for c in
               plan_changes(spec, current, SCHEMAS["issues"])}
    assert set(changes) == {("update", "T-1"), ("add", "T-2"),
                            ("flag_gone", "T-9")}
    assert changes[("update", "T-1")].cells == {"Summary": "new title"}
    assert changes[("add", "T-2")].cells["Summary"] == "brand new"
    assert changes[("flag_gone", "T-9")].cells == {"In Jira": False}


def test_no_changes_when_state_matches():
    spec = _spec(_row("T-1", Summary="same", Status="todo"))
    current = {"T-1": {"Key": "T-1", "Summary": "same", "Status": "todo",
                       "In Jira": True}}
    assert plan_changes(spec, current, SCHEMAS["issues"]) == []


def test_already_flagged_gone_not_reflagged():
    spec = _spec()
    current = {"T-9": {"Key": "T-9", "In Jira": False}}
    assert plan_changes(spec, current, SCHEMAS["issues"]) == []


def test_non_issues_sheet_removes_instead_of_flagging():
    spec = SheetSpec("capacity", [])
    current = {"ada|sprint:1": {"Cell": "ada|sprint:1", "Load": 1.0}}
    changes = plan_changes(spec, current, SCHEMAS["capacity"])
    assert [(c.op, c.key) for c in changes] == [("remove", "ada|sprint:1")]


def test_refuses_human_owned_sheets():
    with pytest.raises(ValueError, match="human"):
        plan_changes(SheetSpec("future_work", []), {},
                     SCHEMAS["future_work"])


def test_update_ignores_unsynced_columns():
    spec = _spec(_row("T-1", Summary="same"))
    # a human somehow added a note under an unknown column in state:
    current = {"T-1": {"Key": "T-1", "Summary": "same", "In Jira": True,
                       "My Notes": "human scribble"}}
    assert plan_changes(spec, current, SCHEMAS["issues"]) == []

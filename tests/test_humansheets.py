import pytest

from tentpole.humansheets import exceptions_from_sheet, ghosts_from_sheet
from tentpole.model import ExceptionRow, Ghost


def test_ghosts_from_sheet():
    rows = {
        "Cal pipeline": {"Title": "Cal pipeline", "Program": "telemetry",
                         "Owner": "", "Estimate Days": 8,
                         "Target": "plan+1", "Intended Epic": "E-1",
                         "Jira Key": ""},
        "Bare row": {"Title": "Bare row"},
    }
    ghosts = {g.title: g for g in ghosts_from_sheet(rows)}
    cal = ghosts["Cal pipeline"]
    assert cal == Ghost(title="Cal pipeline", estimate_days=8.0,
                        target="plan+1", program="telemetry", owner=None,
                        intended_epic="E-1", jira_key=None)
    bare = ghosts["Bare row"]
    assert bare.target == "unscheduled" and bare.estimate_days == 0.0


def test_exceptions_from_sheet():
    rows = {
        "ada|3": {"Cell": "ada|3", "Person": "ada", "Sprint": 3,
                  "Day Cost": "5"},
        "junk": {"Cell": "junk", "Person": "", "Sprint": 1, "Day Cost": 1},
    }
    assert exceptions_from_sheet(rows) == [
        ExceptionRow(person="ada", sprint_id=3, day_cost=5.0)]


def test_ghosts_from_sheet_bad_estimate_days_raises_actionable_error():
    rows = {"Cal pipeline": {"Title": "Cal pipeline",
                             "Estimate Days": "TBD"}}
    with pytest.raises(ValueError) as exc_info:
        ghosts_from_sheet(rows)
    message = str(exc_info.value)
    assert "future_work" in message
    assert "Cal pipeline" in message
    assert "Estimate Days" in message
    assert "TBD" in message


def test_exceptions_from_sheet_bad_day_cost_raises_actionable_error():
    rows = {"ada|3": {"Cell": "ada|3", "Person": "ada", "Sprint": 3,
                      "Day Cost": "lots"}}
    with pytest.raises(ValueError) as exc_info:
        exceptions_from_sheet(rows)
    message = str(exc_info.value)
    assert "exceptions" in message
    assert "ada" in message
    assert "Day Cost" in message
    assert "lots" in message


def test_ghosts_from_sheet_missing_estimate_days_still_zero():
    rows = {"Bare row": {"Title": "Bare row"}}
    ghosts = ghosts_from_sheet(rows)
    assert ghosts[0].estimate_days == 0.0


def test_target_typo_raises_actionable_error():
    for bad in ["sprint 1", "Sprint:1", "plan+3", "fixversion:", "soon"]:
        rows = {"1": {"Title": "G", "Estimate Days": 3, "Target": bad}}
        with pytest.raises(ValueError) as exc:
            ghosts_from_sheet(rows)
        msg = str(exc.value)
        assert "Target" in msg and "G" in msg and repr(bad) in msg


def test_valid_targets_accepted():
    valid = ["sprint:3", "plan+1", "plan+2", "fixversion:R1", "unscheduled"]
    for i, target in enumerate(valid):
        rows = {"1": {"Title": f"G{i}", "Estimate Days": 1,
                      "Target": target}}
        assert ghosts_from_sheet(rows)[0].target == target


def test_blank_target_still_defaults_unscheduled():
    rows = {"1": {"Title": "G", "Estimate Days": 1, "Target": "  "}}
    assert ghosts_from_sheet(rows)[0].target == "unscheduled"


def test_missing_target_still_defaults_unscheduled():
    rows = {"1": {"Title": "G", "Estimate Days": 1}}
    assert ghosts_from_sheet(rows)[0].target == "unscheduled"


def test_team_from_sheet_orders_and_skips_blanks():
    from tentpole.humansheets import team_from_sheet

    rows = {
        "1": {"Person": "Ada Lovelace", "_row_id": 1},
        "2": {"Person": "  "},
        "3": {"Person": "Grace Hopper", "Notes": "on loan until Q4"},
    }
    assert team_from_sheet(rows) == ["Ada Lovelace", "Grace Hopper"]


def test_team_from_sheet_rejects_duplicates():
    from tentpole.humansheets import team_from_sheet

    rows = {"1": {"Person": "Ada Lovelace"},
            "2": {"Person": "Ada Lovelace"}}
    with pytest.raises(ValueError, match="Ada Lovelace"):
        team_from_sheet(rows)

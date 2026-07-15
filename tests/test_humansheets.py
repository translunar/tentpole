import pytest

from tentpole.humansheets import (ghosts_from_sheet, people_from_sheet)
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


def test_people_roster_recurring_and_oneoff_happy_path():
    ps = people_from_sheet({
        "ada": {"Item": "ada", "_parent": None},
        "ada|team lead": {"Item": "team lead", "Days": 2, "_parent": "ada"},
        "ada|PTO": {"Item": "PTO", "Sprint": 3, "Days": 4, "_parent": "ada"},
        "grace": {"Item": "grace", "_parent": None},
        "grace|ops rotation": {"Item": "ops rotation", "Days": 0.5,
                               "_parent": "grace"},
    })
    assert ps.team == ["ada", "grace"]
    assert ps.recurring_days == {"ada": 2.0, "grace": 0.5}
    assert ps.exceptions == [ExceptionRow(person="ada", sprint_id=3,
                                          day_cost=4.0)]


def test_people_roster_orders_and_skips_blanks_ported():
    # Ported from the retired team_from_sheet test: order preserved, blank
    # rows skipped (0.3.0 team-sheet semantics on the people sheet now).
    ps = people_from_sheet({
        "Ada Lovelace": {"Item": "Ada Lovelace", "_parent": None},
        "blank": {"Item": "  ", "_parent": None},
        "Grace Hopper": {"Item": "Grace Hopper", "Notes": "on loan",
                         "_parent": None},
    })
    assert ps.team == ["Ada Lovelace", "Grace Hopper"]


def test_people_present_but_empty_is_authoritative_empty_roster():
    # Ported semantics: a present-but-empty sheet is an authoritative empty
    # team, not a fallback (the cli wiring in Task 6 relies on this).
    assert people_from_sheet({}).team == []


def test_people_duplicate_root_raises_ported():
    # Ported from team_from_sheet's duplicate test. (Live pulls already
    # raise this at Task 1; the parser guards direct callers too.)
    with pytest.raises(ValueError, match="Ada"):
        people_from_sheet({
            "Ada": {"Item": "Ada", "_parent": None},
            "Ada ": {"Item": "Ada", "_parent": None},   # distinct dict key
        })


def test_people_days_on_root_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({"ada": {"Item": "ada", "Days": 3, "_parent": None}})
    assert "ada" in str(exc.value) and "Days" in str(exc.value)


def test_people_grandchild_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|ops": {"Item": "ops", "Days": 2, "_parent": "ada"},
            "ops|deep": {"Item": "deep", "Days": 1, "_parent": "ops"},
        })
    assert "ops" in str(exc.value) and "grandchild" in str(exc.value)


def test_people_child_missing_days_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|ops": {"Item": "ops", "_parent": "ada"}})
    assert "ops" in str(exc.value) and "Days" in str(exc.value)


def test_people_child_nonnumeric_days_raises():
    with pytest.raises(ValueError, match="lots"):
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|ops": {"Item": "ops", "Days": "lots", "_parent": "ada"}})


def test_people_fractional_sprint_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|PTO": {"Item": "PTO", "Sprint": 3.5, "Days": 4,
                        "_parent": "ada"}})
    assert "Sprint" in str(exc.value) and "3.5" in str(exc.value)


def test_people_multiple_recurring_children_sum():
    ps = people_from_sheet({
        "ada": {"Item": "ada", "_parent": None},
        "ada|ops": {"Item": "ops", "Days": 1.5, "_parent": "ada"},
        "ada|lead": {"Item": "lead", "Days": 0.5, "_parent": "ada"},
    })
    assert ps.recurring_days == {"ada": 2.0}

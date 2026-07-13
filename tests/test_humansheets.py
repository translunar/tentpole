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

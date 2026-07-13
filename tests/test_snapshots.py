from tentpole.model import Issue
from tentpole.snapshots import parse_jsonl, snapshot_records, to_jsonl


def test_snapshot_records_shape(make_bundle):
    b = make_bundle(issues=[
        Issue(key="T-1", summary="t", issue_type="Task",
              status_category="in_progress", assignee="ada", sprint_id=2,
              original_estimate_days=5.0, remaining_estimate_days=3.0),
        Issue(key="E-1", summary="e", issue_type="Epic",
              status_category="todo"),
        Issue(key="X-1", summary="x", issue_type="Task",
              status_category="todo", external=True),
    ])
    records = snapshot_records(b)
    assert records == [{
        "run": "2026-07-12", "key": "T-1", "status": "in_progress",
        "sprint_id": 2, "assignee": "ada", "original": 5.0,
        "remaining": 3.0,
    }]


def test_jsonl_round_trip():
    records = [{"run": "2026-07-12", "key": "T-1"},
               {"run": "2026-07-12", "key": "T-2"}]
    text = to_jsonl(records)
    assert text.endswith("\n") and text.count("\n") == 2
    assert parse_jsonl(text + "\n\n") == records
    assert to_jsonl([]) == ""
    assert parse_jsonl("") == []

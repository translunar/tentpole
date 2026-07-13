import json
from datetime import date

from tentpole.model import Config, Issue, load_bundle


def test_bundle_issue_lookup(make_bundle):
    b = make_bundle(issues=[Issue(key="T-1", summary="x", issue_type="Task",
                                  status_category="todo")])
    assert b.issue("T-1").summary == "x"
    assert b.issue("NOPE") is None


def test_load_bundle_from_json_dir(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (tmp_path / "issues.json").write_text(json.dumps([{
        "key": "T-1", "summary": "Parse frames", "issue_type": "Task",
        "status_category": "in_progress", "assignee": "ada",
        "original_estimate_days": 3.0, "remaining_estimate_days": 2.0,
        "epic_key": "E-1", "fix_versions": ["v2.3"], "sprint_id": 1,
        "labels": ["overhead"],
        "links": [{"type": "Blocks", "direction": "inward", "other_key": "X-9"}],
        "program": "telemetry", "first_in_progress": "2026-07-10",
        "done_at": None, "external": False,
    }]))
    (tmp_path / "sprints.json").write_text(json.dumps([
        {"id": 1, "name": "S1", "start": "2026-07-13", "end": "2026-07-22"},
    ]))
    (tmp_path / "fix_versions.json").write_text(json.dumps([
        {"name": "v2.3", "release_date": "2026-08-15", "released": False},
    ]))
    (tmp_path / "ghosts.json").write_text(json.dumps([
        {"title": "Cal pipeline", "estimate_days": 8.0, "target": "plan+1",
         "program": "telemetry", "owner": None, "intended_epic": "E-1",
         "jira_key": None},
    ]))
    (tmp_path / "exceptions.json").write_text(json.dumps([
        {"person": "ada", "sprint_id": 1, "day_cost": 5.0},
    ]))
    (tmp_path / "hygiene.json").write_text(json.dumps({"orphan-task": ["T-1"]}))
    (tmp_path / "config.json").write_text(json.dumps({"team": ["ada", "grace"]}))

    b = load_bundle(tmp_path)
    assert b.as_of == date(2026, 7, 12)
    issue = b.issue("T-1")
    assert issue.fix_versions == ["v2.3"]
    assert issue.links[0].other_key == "X-9"
    assert issue.first_in_progress == date(2026, 7, 10)
    assert b.sprints[0].end == date(2026, 7, 22)
    assert b.fix_versions[0].release_date == date(2026, 8, 15)
    assert b.ghosts[0].target == "plan+1"
    assert b.exceptions[0].day_cost == 5.0
    assert b.hygiene_memberships["orphan-task"] == ["T-1"]
    assert b.config.team == ["ada", "grace"]


def test_load_bundle_tolerates_missing_optional_files(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    b = load_bundle(tmp_path)
    assert b.issues == [] and b.ghosts == []
    assert isinstance(b.config, Config)

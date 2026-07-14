import json

import pytest

from tentpole.cli import main


@pytest.fixture
def bundle_dir(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (tmp_path / "sprints.json").write_text(json.dumps([
        {"id": 1, "name": "S1", "start": "2026-07-13", "end": "2026-07-22"},
        {"id": 2, "name": "S2", "start": "2026-07-23", "end": "2026-08-01"},
        {"id": 3, "name": "S3", "start": "2026-08-02", "end": "2026-08-11"},
        {"id": 4, "name": "S4", "start": "2026-08-12", "end": "2026-08-21"},
        {"id": 5, "name": "S5", "start": "2026-08-22", "end": "2026-08-31"},
    ]))
    (tmp_path / "issues.json").write_text(json.dumps([
        {"key": "T-1", "summary": "Parse frames", "issue_type": "Task",
         "status_category": "todo", "assignee": "ada", "sprint_id": 1,
         "remaining_estimate_days": 12.0},
        {"key": "T-2", "summary": "Small fix", "issue_type": "Task",
         "status_category": "todo", "assignee": "grace", "sprint_id": 1,
         "remaining_estimate_days": 1.0},
    ]))
    (tmp_path / "config.json").write_text(json.dumps({"team": ["ada", "grace"]}))
    return tmp_path


def test_check_prints_overload_and_exits_1(bundle_dir, capsys):
    rc = main(["check", "--bundle", str(bundle_dir), "--me", "ada"])
    out = capsys.readouterr().out
    assert "sprint_overload" in out
    assert "12.0" in out
    assert rc == 1


def test_check_clean_person_exits_0(bundle_dir, capsys):
    rc = main(["check", "--bundle", str(bundle_dir), "--me", "grace"])
    out = capsys.readouterr().out
    assert "all clear" in out.lower()
    assert rc == 0


def test_check_bad_sprints_per_plan_prints_actionable_error_not_traceback(
        bundle_dir, capsys):
    """Mirrors the sync-command fix: `check`'s load_bundle call has no
    try/except either, so a bad sprints_per_plan in config.json must not
    surface as a bare traceback -- same ERROR: <message> / exit 1
    posture as adapters/cli.py's dispatch()."""
    (bundle_dir / "config.json").write_text(
        json.dumps({"team": ["ada", "grace"], "sprints_per_plan": "6"}))

    rc = main(["check", "--bundle", str(bundle_dir), "--me", "ada"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out
    assert "sprints_per_plan" in out


def test_check_json_output(bundle_dir, capsys):
    rc = main(["check", "--bundle", str(bundle_dir), "--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["as_of"] == "2026-07-12"
    assert any(f["check"] == "sprint_overload" for f in parsed["findings"])
    assert rc == 1

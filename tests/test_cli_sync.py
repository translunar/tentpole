import json

import pytest

from tentpole.cli import main


@pytest.fixture
def dirs(tmp_path):
    bundle = tmp_path / "bundle"
    state = tmp_path / "state"
    out = tmp_path / "out"
    bundle.mkdir()
    state.mkdir()
    (bundle / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (bundle / "sprints.json").write_text(json.dumps([
        {"id": 1, "name": "S1", "start": "2026-07-13", "end": "2026-07-22"},
    ]))
    (bundle / "issues.json").write_text(json.dumps([
        {"key": "T-1", "summary": "Parse frames", "issue_type": "Task",
         "status_category": "todo", "assignee": "ada", "sprint_id": 1,
         "remaining_estimate_days": 3.0},
    ]))
    (bundle / "config.json").write_text(json.dumps({"team": ["ada"]}))
    return bundle, state, out


def test_schema_show(capsys):
    assert main(["schema", "show"]) == 0
    out = capsys.readouterr().out
    assert "issues" in out and "future_work" in out


def test_sync_writes_outputs(dirs, capsys):
    bundle, state, out = dirs
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    plans = json.loads((out / "plans" / "issues.json").read_text())
    assert any(c["op"] == "add" and c["key"] == "T-1" for c in plans)
    report = json.loads((out / "report.json").read_text())
    assert report["issues"] == 1
    assert "SYNC HEALTH" in (out / "report.txt").read_text()
    assert "SYNC HEALTH" in capsys.readouterr().out
    lines = (state / "snapshots.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["key"] == "T-1"


def test_sync_appends_snapshots_and_reads_human_sheets(dirs):
    bundle, state, out = dirs
    (state / "future_work.json").write_text(json.dumps({
        "Cal pipeline": {"Title": "Cal pipeline", "Estimate Days": 8,
                         "Target": "plan+1"}}))
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    lines = (state / "snapshots.jsonl").read_text().splitlines()
    assert len(lines) == 2                      # appended, not overwritten
    report = json.loads((out / "report.json").read_text())
    assert report["changes"]["capacity"]  # plan present (state never applied)

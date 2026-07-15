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


def test_sync_bad_sprints_per_plan_prints_actionable_error_not_traceback(
        dirs, capsys):
    """A bundle whose config.json carries a bad sprints_per_plan (e.g. a
    quoted "6") makes Config(**config_raw) raise ValueError inside
    load_bundle. cli.py's sync command calls load_bundle with no
    try/except, so this must not surface as a bare traceback -- match
    the ERROR: <message> / exit 1 posture already established in
    adapters/cli.py's dispatch()."""
    bundle, state, out = dirs
    (bundle / "config.json").write_text(
        json.dumps({"team": ["ada"], "sprints_per_plan": "6"}))

    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    out_text = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out_text
    assert "sprints_per_plan" in out_text


def test_sync_creates_missing_state_dir(dirs):
    # FIX 1: --state need not already exist (first run on a clean checkout).
    bundle, state, out = dirs
    missing_state = state / "nested" / "state"
    assert not missing_state.exists()
    rc = main(["sync", "--bundle", str(bundle), "--state",
               str(missing_state), "--out", str(out)])
    assert rc == 0
    assert (missing_state / "snapshots.jsonl").exists()


def test_sync_people_sheet_supplies_exceptions(dirs):
    # One-off exceptions now come from people-sheet child rows with Sprint
    # set (spec §3). ada carries 6d of sprint-1 work; a 3d one-off in
    # sprint 1 pushes her over prior capacity -> red sprint_overload.
    bundle, state, out = dirs
    issues = json.loads((bundle / "issues.json").read_text())
    issues[0]["remaining_estimate_days"] = 6.0
    (bundle / "issues.json").write_text(json.dumps(issues))
    (state / "people.json").write_text(json.dumps({
        "ada": {"Item": "ada", "_row_id": 1, "_parent": None},
        "ada|PTO": {"Item": "PTO", "Sprint": 1, "Days": 3, "_row_id": 2,
                    "_parent": "ada"}}))
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert rc == 0                                   # sync reports, returns 0
    assert "sprint_overload" in report["findings"]


def test_sync_people_sheet_overrides_bundle_config(dirs):
    bundle, state, out = dirs
    (state / "people.json").write_text(json.dumps({
        "grace": {"Item": "grace", "_row_id": 1, "_parent": None}}))
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    cap = json.loads((out / "plans" / "capacity.json").read_text())
    keys = {c["key"] for c in cap}
    assert any(k.startswith("grace|") for k in keys)
    assert not any(k.startswith("ada|") for k in keys)


def test_sync_emptied_people_sheet_drops_stale_bundle_roster(dirs):
    # Present-but-empty people.json ({}) is authoritative: the bundle's
    # core: team: roster must not survive it (spec §3, ported from the
    # 0.3.0 team-sheet semantics test).
    bundle, state, out = dirs
    (state / "people.json").write_text("{}")
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    cap = json.loads((out / "plans" / "capacity.json").read_text())
    assert cap == []


def test_sync_carryover_fires_on_second_run(dirs, capsys):
    # First run seeds snapshots.jsonl (T-1 sprint-planned, not done). Second
    # run over the same bundle -> carryover yellow finding.
    bundle, state, out = dirs
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert report["findings"].get("carryover") == 1

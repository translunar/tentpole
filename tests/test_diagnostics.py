import json
from datetime import date

from tentpole.diagnostics import assemble, personal, to_json
from tentpole.hygiene import Rule
from tentpole.model import FixVersion, Issue, Link


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def _bundle(make_bundle):
    return make_bundle(
        issues=[
            _task("T-1", assignee="ada", sprint_id=1,
                  remaining_estimate_days=9.0),         # overloads ada
            _task("T-2", assignee="grace", sprint_id=1,
                  remaining_estimate_days=1.0),
        ],
        hygiene_memberships={"orphan-task": ["T-1", "T-2"]})


RULES = [Rule(name="orphan-task", severity="yellow", message="No epic",
              jql="issuetype != Bug AND parent is EMPTY")]


def test_assemble_shape(make_bundle):
    diag = assemble(_bundle(make_bundle), rules=RULES)
    checks_present = {f.check for f in diag["findings"]}
    assert "sprint_overload" in checks_present
    assert [fl.key for fl in diag["hygiene"]] == ["T-1", "T-2"]
    ada_row = next(r for r in diag["capacity"]
                   if r["person"] == "ada" and r["bucket_id"] == "sprint:1")
    assert ada_row["load"] == 9.0
    assert len(diag["demand"]) == 2


def test_personal_filters(make_bundle):
    b = _bundle(make_bundle)
    diag = assemble(b, rules=RULES)
    mine = personal(diag, b, "ada")
    # Fixture only produces one finding: ada's sprint_overload.
    assert [(f.check, f.subject) for f in mine["findings"]] == \
        [("sprint_overload", "ada")]
    assert [fl.key for fl in mine["hygiene"]] == ["T-1"]   # T-2 is grace's
    assert all(r["person"] == "ada" for r in mine["capacity"])
    assert all(d.who == "ada" for d in mine["demand"])


def test_personal_includes_milestone_and_epic_runway_findings(make_bundle):
    # Milestone "v1" releases mid-sprint-2, but ada's task carrying that
    # fixVersion is scheduled in sprint 5 -> deadline_risk fires with
    # subject "v1" (not a person), so it must still land in ada's slice.
    v1 = FixVersion(name="v1", release_date=date(2026, 7, 25))
    epic = Issue(key="E-1", summary="Tentpole epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v1"])
    milestone_task = Issue(key="T-10", summary="milestone work",
                           issue_type="Task", status_category="todo",
                           assignee="ada", sprint_id=5, fix_versions=["v1"])
    # Big remaining task on the epic, with no slack before the epic's
    # fixVersion-derived deadline -> tentpole_runway fires with subject
    # "E-1" (an epic key, not a person).
    runway_task = Issue(key="T-11", summary="epic work", issue_type="Task",
                        status_category="todo", assignee="ada",
                        epic_key="E-1", remaining_estimate_days=100.0)
    b = make_bundle(issues=[epic, milestone_task, runway_task],
                    fix_versions=[v1])
    diag = assemble(b)

    ada_checks = {(f.check, f.subject) for f in personal(diag, b, "ada")["findings"]}
    assert ("deadline_risk", "v1") in ada_checks
    assert ("tentpole_runway", "E-1") in ada_checks

    grace_checks = {(f.check, f.subject)
                    for f in personal(diag, b, "grace")["findings"]}
    assert ("deadline_risk", "v1") not in grace_checks
    assert ("tentpole_runway", "E-1") not in grace_checks


def test_to_json_round_trips(make_bundle):
    diag = assemble(_bundle(make_bundle), rules=RULES)
    parsed = json.loads(to_json(diag))
    assert parsed["as_of"] == "2026-07-12"
    assert isinstance(parsed["findings"], list)
    assert parsed["findings"][0]["check"]

import json

from tentpole.diagnostics import assemble, personal, to_json
from tentpole.hygiene import Rule
from tentpole.model import Issue, Link


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
    mine = personal(assemble(b, rules=RULES), b, "ada")
    assert all(f.subject == "ada" for f in mine["findings"])
    assert [fl.key for fl in mine["hygiene"]] == ["T-1"]   # T-2 is grace's
    assert all(r["person"] == "ada" for r in mine["capacity"])
    assert all(d.who == "ada" for d in mine["demand"])


def test_to_json_round_trips(make_bundle):
    diag = assemble(_bundle(make_bundle), rules=RULES)
    parsed = json.loads(to_json(diag))
    assert parsed["as_of"] == "2026-07-12"
    assert isinstance(parsed["findings"], list)
    assert parsed["findings"][0]["check"]

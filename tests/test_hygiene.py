import textwrap

from tentpole.hygiene import Rule, evaluate, load_rules
from tentpole.model import FixVersion, Issue


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_load_rules(tmp_path):
    p = tmp_path / "hygiene.yaml"
    p.write_text(textwrap.dedent("""\
        hygiene:
          - name: unanchored-work
            severity: red
            jql: "fixVersion is EMPTY"
            derived: inherits_no_fixversion
            message: "No milestone attached (directly or via epic)"
          - name: orphan-task
            severity: yellow
            jql: 'issuetype != Bug AND parent is EMPTY'
            message: "Task belongs to no epic"
    """))
    rules = load_rules(p)
    assert rules[0] == Rule(name="unanchored-work", severity="red",
                            message="No milestone attached (directly or via epic)",
                            jql="fixVersion is EMPTY",
                            derived="inherits_no_fixversion")
    assert rules[1].derived is None


def test_evaluate_ands_membership_with_derived(make_bundle):
    epic_with_fv = Issue(key="E-1", summary="Epic", issue_type="Epic",
                         status_category="in_progress", fix_versions=["v1"])
    issues = [
        epic_with_fv,
        _task("T-1"),                          # matches JQL, no inheritance -> flag
        _task("T-2", epic_key="E-1"),          # matches JQL, inherits v1 -> no flag
        _task("T-3", status_category="done"),  # done -> out of scope
        _task("T-4", external=True),           # external -> out of scope
    ]
    b = make_bundle(
        issues=issues,
        fix_versions=[FixVersion("v1")],
        hygiene_memberships={"unanchored-work": ["T-1", "T-2", "T-3", "T-4"]})
    rule = Rule(name="unanchored-work", severity="red", message="No milestone",
                jql="fixVersion is EMPTY", derived="inherits_no_fixversion")
    flags = evaluate(b, [rule])
    assert [f.key for f in flags] == ["T-1"]
    assert flags[0].severity == "red"


def test_evaluate_membership_only_rule(make_bundle):
    b = make_bundle(issues=[_task("T-1"), _task("T-2")],
                    hygiene_memberships={"orphan-task": ["T-2"]})
    rule = Rule(name="orphan-task", severity="yellow", message="No epic",
                jql="issuetype != Bug AND parent is EMPTY")
    flags = evaluate(b, [rule])
    assert [f.key for f in flags] == ["T-2"]


def test_missing_membership_means_no_flags(make_bundle):
    b = make_bundle(issues=[_task("T-1")])
    rule = Rule(name="orphan-task", severity="yellow", message="m",
                jql="whatever")
    assert evaluate(b, [rule]) == []

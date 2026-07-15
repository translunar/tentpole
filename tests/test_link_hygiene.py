from tentpole.checks import link_hygiene
from tentpole.model import Issue, Link


def _issue(key, links=None, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, links=links or [], **base)


def _by_check(findings):
    out = {}
    for f in findings:
        out.setdefault(f.check, []).append(f)
    return out


def test_link_hygiene_flags_cycle_members(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "B")]),
        _issue("B", links=[Link("Blocks", "outward", "C")]),
        _issue("C", links=[Link("Blocks", "outward", "A")]),
    ])
    findings = [f for f in link_hygiene(b) if f.check == "link_cycle"]
    # The dropped edge (C, A) is named; both endpoints flagged.
    assert findings
    assert all("C" in f.message and "A" in f.message for f in findings)


def test_link_hygiene_flags_blocks_into_done(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "B")]),
        _issue("B", status_category="done"),
    ])
    findings = [f for f in link_hygiene(b) if f.check == "link_stale_done"]
    assert len(findings) == 1
    assert "B" in findings[0].message


def test_link_hygiene_flags_out_of_scope_target(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "OUT-9")]),
    ])   # OUT-9 not in the bundle
    findings = [f for f in link_hygiene(b) if f.check == "link_out_of_scope"]
    assert len(findings) == 1
    assert "OUT-9" in findings[0].message


def test_link_hygiene_quiet_on_clean_graph(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "B")]),
        _issue("B")])
    assert link_hygiene(b) == []

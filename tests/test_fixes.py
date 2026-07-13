import pytest

from tentpole.fixes import STRATEGIES, Proposal, propose
from tentpole.hygiene import FIX_STRATEGY_NAMES, Rule, load_rules
from tentpole.model import Issue


def _issue(key, **kw):
    kw.setdefault("summary", key)
    kw.setdefault("issue_type", "Task")
    kw.setdefault("status_category", "todo")
    return Issue(key=key, **kw)


def test_strategy_registry_matches_hygiene_names():
    assert set(STRATEGIES) == set(FIX_STRATEGY_NAMES)


def test_inherit_epic_fixversion_mechanical(make_bundle):
    bundle = make_bundle(
        issues=[
            _issue("E-1", issue_type="Epic", fix_versions=["R1"]),
            _issue("T-1", epic_key="E-1"),
        ],
        hygiene_memberships={"unanchored": ["T-1"]})
    rules = [Rule(name="unanchored", severity="red", message="m",
                  jql="fixVersion is EMPTY",
                  fix="inherit_epic_fixversion")]
    out = propose(bundle, rules)
    assert out == [Proposal(
        issue="T-1", action="set_fix_version", value="R1",
        rationale="epic E-1 carries R1", confidence="mechanical",
        rule="unanchored")]


def test_inherit_skips_when_epic_has_no_fixversion(make_bundle):
    bundle = make_bundle(
        issues=[
            _issue("E-1", issue_type="Epic"),
            _issue("T-1", epic_key="E-1"),
        ],
        hygiene_memberships={"unanchored": ["T-1"]})
    rules = [Rule(name="unanchored", severity="red", message="m",
                  jql="fixVersion is EMPTY",
                  fix="inherit_epic_fixversion")]
    assert propose(bundle, rules) == []


def test_suggest_epic_from_siblings_ranks_by_shared_program(make_bundle):
    bundle = make_bundle(
        issues=[
            _issue("E-1", issue_type="Epic"),
            _issue("E-2", issue_type="Epic"),
            _issue("S-1", epic_key="E-1", program="nav"),
            _issue("S-2", epic_key="E-1", program="nav"),
            _issue("S-3", epic_key="E-2", program="nav"),
            _issue("T-1", program="nav"),
        ],
        hygiene_memberships={"orphan": ["T-1"]})
    rules = [Rule(name="orphan", severity="yellow", message="m",
                  jql="parent is EMPTY",
                  fix="suggest_epic_from_siblings")]
    out = propose(bundle, rules)
    assert [p.value for p in out] == ["E-1", "E-2"]   # 2 siblings > 1
    assert all(p.action == "set_parent" for p in out)
    assert all(p.confidence == "suggested" for p in out)


def test_load_rules_rejects_unknown_fix(tmp_path):
    bad = tmp_path / "rules.yaml"
    bad.write_text(
        "hygiene:\n"
        "  - name: r\n    severity: red\n    message: m\n"
        "    jql: 'a = b'\n    fix: teleport_to_done\n")
    with pytest.raises(ValueError, match="teleport_to_done"):
        load_rules(bad)

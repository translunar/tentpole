from tentpole.linkgraph import blocks_edges, break_cycles
from tentpole.model import Issue, Link


def _issue(key, links=None, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, links=links or [], **base)


def test_blocks_edges_direction(make_bundle):
    # X-1 is blocked by B-1 (inward) -> edge (B-1, X-1).
    # X-1 blocks A-1 (outward) -> edge (X-1, A-1).
    b = make_bundle(issues=[
        _issue("X-1", links=[Link("Blocks", "inward", "B-1"),
                             Link("Blocks", "outward", "A-1")]),
        _issue("A-1"), _issue("B-1")])
    assert blocks_edges(b) == [("B-1", "X-1"), ("X-1", "A-1")]


def test_break_cycles_drops_highest_key_deterministically():
    # A->B, B->C, C->A is a cycle. Sorted ascending the closing edge is the
    # last one added; ("C","A") is the highest key -> dropped.
    edges = [("A", "B"), ("B", "C"), ("C", "A")]
    kept, dropped = break_cycles(edges)
    assert dropped == [("C", "A")]
    assert set(kept) == {("A", "B"), ("B", "C")}


def test_break_cycles_noop_on_dag():
    edges = [("A", "B"), ("A", "C"), ("B", "C")]
    kept, dropped = break_cycles(edges)
    assert dropped == [] and set(kept) == set(edges)

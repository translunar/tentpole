"""Pure blocks-link graph helpers: directed edge extraction and
deterministic cycle-breaking. Shared by link-hygiene findings (checks.py)
and the gantt arrow subset (gantt.py). No I/O, no clock."""
from __future__ import annotations

from tentpole.model import Bundle


def blocks_edges(bundle: Bundle) -> list[tuple[str, str]]:
    # Directed (blocker, blocked) edges from Blocks links. inward on X from
    # O means O blocks X; outward on X to O means X blocks O. Deduped and
    # sorted for determinism. Both endpoints' issues may or may not be in
    # the bundle -- callers filter by scope.
    seen = set()
    for issue in bundle.issues:
        if issue.external:
            continue
        for link in issue.links:
            if link.type != "Blocks":
                continue
            if link.direction == "inward":
                seen.add((link.other_key, issue.key))
            else:
                seen.add((issue.key, link.other_key))
    return sorted(seen)


def _reaches(adj: dict[str, set[str]], src: str, dst: str) -> bool:
    # Does src reach dst following adj (DFS)?
    stack = [src]
    seen = set()
    while stack:
        node = stack.pop()
        if node == dst:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, ()))
    return False


def break_cycles(edges: list[tuple[str, str]]
                 ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    # Greedy DAG construction over edges sorted ascending: add each edge
    # unless its target already reaches its source (adding would close a
    # cycle). The closing edge -- the highest sorted key in the cycle --
    # is the one dropped (spec §6: "highest sorted key loses"). Deterministic.
    adj: dict[str, set[str]] = {}
    kept, dropped = [], []
    for src, dst in sorted(edges):
        if _reaches(adj, dst, src):
            dropped.append((src, dst))
            continue
        adj.setdefault(src, set()).add(dst)
        kept.append((src, dst))
    return kept, dropped

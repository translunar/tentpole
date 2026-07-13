from datetime import date, timedelta

import pytest

from tentpole.model import (
    Bundle, Config, ExceptionRow, FixVersion, Ghost, Issue, Link, Sprint,
)


def _make_sprints(start=date(2026, 7, 13), n=6, first_id=1):
    return [
        Sprint(
            id=first_id + i,
            name=f"S{first_id + i}",
            start=start + timedelta(days=10 * i),
            end=start + timedelta(days=10 * i + 9),
        )
        for i in range(n)
    ]


@pytest.fixture
def make_sprints():
    return _make_sprints


@pytest.fixture
def make_bundle():
    def _make(**overrides):
        defaults = dict(
            as_of=date(2026, 7, 12),
            issues=[],
            sprints=_make_sprints(),
            fix_versions=[],
            ghosts=[],
            exceptions=[],
            hygiene_memberships={},
            config=Config(team=["ada", "grace"]),
        )
        defaults.update(overrides)
        return Bundle(**defaults)

    return _make

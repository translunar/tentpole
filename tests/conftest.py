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


class FakeHttp:
    """Stands in for tentpole.adapters.http.request in adapter tests.

    Queue responses with add(method, url_substring, response); each is
    matched and consumed in order, so paginated endpoints queue one
    entry per page. A queued Exception instance is raised instead.
    """

    def __init__(self):
        self.calls = []
        self._queue = []

    def add(self, method, substr, response):
        self._queue.append((method, substr, response))

    def __call__(self, method, url, headers, *, params=None, body=None,
                 **kwargs):
        self.calls.append({"method": method, "url": url,
                           "params": params, "body": body})
        for i, (m, s, resp) in enumerate(self._queue):
            if m == method and s in url:
                self._queue.pop(i)
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected request: {method} {url}")


@pytest.fixture
def fake_http():
    return FakeHttp()

import json

import pytest

from tentpole.adapters.http import HttpError, request


class ScriptedTransport:
    """Returns queued (status, headers, body) tuples; records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, body))
        return self.responses.pop(0)


def test_success_parses_json_and_sends_body():
    t = ScriptedTransport((200, {}, json.dumps({"ok": True})))
    out = request("POST", "https://x/api", {"Authorization": "B t"},
                  body={"a": 1}, transport=t)
    assert out == {"ok": True}
    method, url, headers, body = t.requests[0]
    assert method == "POST" and json.loads(body) == {"a": 1}
    assert headers["Content-Type"] == "application/json"


def test_params_are_urlencoded():
    t = ScriptedTransport((200, {}, "{}"))
    request("GET", "https://x/api", {}, params={"q": "a b"}, transport=t)
    assert t.requests[0][1] == "https://x/api?q=a+b"


def test_empty_body_returns_empty_dict():
    t = ScriptedTransport((200, {}, ""))
    assert request("GET", "https://x/api", {}, transport=t) == {}


def test_retries_on_429_honoring_retry_after():
    t = ScriptedTransport((429, {"Retry-After": "7"}, ""),
                          (429, {}, ""),
                          (200, {}, "{}"))
    sleeps = []
    out = request("GET", "https://x/api", {}, transport=t,
                  sleep=sleeps.append)
    assert out == {}
    assert len(t.requests) == 3
    assert sleeps[0] == 7.0          # Retry-After wins
    assert sleeps[1] == 2.0          # exponential fallback: 1.0 doubled once


def test_client_error_raises_immediately():
    t = ScriptedTransport((404, {}, '{"err": "no"}'))
    with pytest.raises(HttpError) as exc:
        request("GET", "https://x/api", {}, transport=t)
    assert exc.value.status == 404
    assert len(t.requests) == 1


def test_retries_exhausted_raises_after_max_tries():
    """FINDING 4: every attempt returns a retryable status (503) --
    request() must retry up to max_tries times and then raise HttpError
    on the final attempt, rather than looping forever or swallowing the
    failure. This is the only network primitive in the project and its
    retries-exhausted boundary previously had no test."""
    t = ScriptedTransport(*[(503, {}, "unavailable")] * 5)
    sleeps = []
    with pytest.raises(HttpError) as exc:
        request("GET", "https://x/api", {}, transport=t,
               sleep=sleeps.append, max_tries=5)
    assert exc.value.status == 503
    assert len(t.requests) == 5
    assert len(sleeps) == 4


def test_retry_after_http_date_falls_back_to_exponential():
    t = ScriptedTransport(
        (429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, ""),
        (200, {}, "{}"))
    sleeps = []
    out = request("GET", "https://x/api", {}, transport=t,
                  sleep=sleeps.append)
    assert out == {}
    assert sleeps == [1.0]        # exponential fallback, not a crash

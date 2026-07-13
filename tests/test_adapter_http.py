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

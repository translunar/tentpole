"""Tiny JSON-over-HTTP helper for the adapter edge (spec section 8:
exponential backoff on 429s). stdlib only; transport and sleep are
injectable so adapter tests never touch the network or the clock."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

# transport(method, url, headers, body_bytes) -> (status, headers, text)
Transport = Callable[[str, str, dict, bytes | None],
                     tuple[int, dict, str]]

RETRYABLE = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str):
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} from {url}: {body[:200]}")


def urllib_transport(method: str, url: str, headers: dict,
                     body: bytes | None) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read().decode()


def request(method: str, url: str, headers: dict, *,
            params: dict | None = None, body: dict | list | None = None,
            transport: Transport = urllib_transport,
            sleep: Callable[[float], None] = time.sleep,
            max_tries: int = 5) -> dict | list:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    headers = dict(headers)
    headers.setdefault("Accept", "application/json")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    delay = 1.0
    for attempt in range(max_tries):
        status, resp_headers, text = transport(method, url, headers, data)
        if status in RETRYABLE and attempt < max_tries - 1:
            retry_after = resp_headers.get("Retry-After")
            sleep(float(retry_after) if retry_after else delay)
            delay *= 2
            continue
        if status >= 400:
            raise HttpError(status, url, text)
        return json.loads(text) if text.strip() else {}
    raise AssertionError("unreachable")  # loop always returns or raises

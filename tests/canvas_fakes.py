"""Fake requests-like transport for Canvas client tests. No real network
access is used or needed."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeResponse:
    _payload: object
    status_code: int = 200
    links: dict = field(default_factory=dict)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} error")


class FakeCanvasSession:
    """Maps exact (url, frozenset(params.items())) -> FakeResponse, so
    tests can script pagination and error scenarios precisely.

    Register responses with `.add(url, params, response)`; the object
    is a stand-in for `requests.Session`.
    """

    def __init__(self):
        self._routes: dict[tuple, FakeResponse] = {}
        self.requested_urls: list[str] = []

    @staticmethod
    def _key(url: str, params: dict | None) -> tuple:
        norm = []
        for k, v in sorted((params or {}).items()):
            if isinstance(v, list):
                norm.append((k, tuple(v)))
            else:
                norm.append((k, v))
        return (url, tuple(norm))

    def add(self, url: str, params: dict | None, response: FakeResponse) -> None:
        self._routes[self._key(url, params)] = response

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 15.0):
        self.requested_urls.append(url)
        self.last_headers = headers
        key = self._key(url, params)
        if key not in self._routes:
            raise AssertionError(f"FakeCanvasSession: no route registered for {key}")
        return self._routes[key]

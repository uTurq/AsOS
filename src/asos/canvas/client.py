"""
Thin wrapper around the Canvas LMS REST API v1.

Deliberately dumb: this module's only job is "get me these resources
as plain dicts, following pagination." All diffing/upserting/judgment
logic lives in asos.canvas.sync, not here — keeps this module trivially
testable and swappable if the Canvas API ever changes shape.

The HTTP transport is injectable (defaults to a real `requests.Session`)
so tests never need real network access — see tests/test_canvas_client.py
for the fake-session pattern, which mirrors how asos.credentials injects
a fake keyring backend.

SAFETY: the API token is sent only as an Authorization header, never as
a query parameter (which would land in logs/proxies/browser history),
and this module never logs the token or includes it in an exception
message.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Protocol

import requests

logger = logging.getLogger("asos.canvas")

DEFAULT_PER_PAGE = 100


class HttpResponse(Protocol):
    status_code: int
    links: dict

    def json(self) -> Any: ...
    def raise_for_status(self) -> None: ...


class HttpSession(Protocol):
    """The subset of requests.Session's interface we depend on."""

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: float = ...) -> HttpResponse: ...


class CanvasAPIError(RuntimeError):
    """Raised on any non-2xx Canvas response. Message never includes the
    Authorization header or token value."""


class CanvasClient:
    def __init__(self, base_url: str, token: str, session: HttpSession | None = None, timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._session = session or requests.Session()
        self._timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _get_paginated(self, path: str, params: dict | None = None) -> Iterator[dict]:
        url = f"{self._base_url}{path}"
        params = dict(params or {})
        params.setdefault("per_page", DEFAULT_PER_PAGE)

        while url:
            try:
                response = self._session.get(url, params=params, headers=self._headers(), timeout=self._timeout)
            except requests.RequestException as exc:
                raise CanvasAPIError(f"Network error contacting Canvas: {exc}") from None

            if response.status_code == 401:
                raise CanvasAPIError(
                    "Canvas rejected the API token (401 Unauthorized). "
                    "The stored canvas_api_token is likely invalid or expired."
                )
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise CanvasAPIError(f"Canvas API returned an error: {exc}") from None

            payload = response.json()
            if not isinstance(payload, list):
                raise CanvasAPIError(f"Expected a list response from {path}, got {type(payload).__name__}")
            yield from payload

            next_link = response.links.get("next")
            url = next_link["url"] if next_link else None
            params = None  # the next-page URL already includes query params

    def get_active_courses(self) -> list[dict]:
        return list(self._get_paginated("/api/v1/courses", params={"enrollment_state": "active"}))

    def get_assignments(self, course_id: str) -> list[dict]:
        return list(
            self._get_paginated(
                f"/api/v1/courses/{course_id}/assignments",
                params={"include[]": "submission"},
            )
        )

    def get_calendar_events(self, context_codes: list[str]) -> list[dict]:
        if not context_codes:
            return []
        return list(
            self._get_paginated(
                "/api/v1/calendar_events",
                params={"context_codes[]": context_codes, "type": "event"},
            )
        )

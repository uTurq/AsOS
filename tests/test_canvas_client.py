from __future__ import annotations

import pytest

from asos.canvas.client import CanvasAPIError, CanvasClient
from tests.canvas_fakes import FakeCanvasSession, FakeResponse

BASE_URL = "https://school.instructure.com"


def test_get_active_courses_single_page():
    session = FakeCanvasSession()
    session.add(
        f"{BASE_URL}/api/v1/courses",
        {"enrollment_state": "active", "per_page": 100},
        FakeResponse([{"id": 1, "name": "Biology 101"}, {"id": 2, "name": "Chemistry 1010"}]),
    )
    client = CanvasClient(BASE_URL, token="fake-token", session=session)

    courses = client.get_active_courses()

    assert [c["name"] for c in courses] == ["Biology 101", "Chemistry 1010"]
    assert session.last_headers["Authorization"] == "Bearer fake-token"


def test_pagination_follows_link_header():
    session = FakeCanvasSession()
    page1_url = f"{BASE_URL}/api/v1/courses"
    page2_url = f"{BASE_URL}/api/v1/courses?page=2"

    session.add(
        page1_url,
        {"enrollment_state": "active", "per_page": 100},
        FakeResponse([{"id": 1, "name": "Course A"}], links={"next": {"url": page2_url}}),
    )
    session.add(page2_url, None, FakeResponse([{"id": 2, "name": "Course B"}], links={}))

    client = CanvasClient(BASE_URL, token="tok", session=session)
    courses = client.get_active_courses()

    assert [c["name"] for c in courses] == ["Course A", "Course B"]
    assert session.requested_urls == [page1_url, page2_url]


def test_assignments_include_submission_param():
    session = FakeCanvasSession()
    session.add(
        f"{BASE_URL}/api/v1/courses/42/assignments",
        {"include[]": "submission", "per_page": 100},
        FakeResponse([{"id": 100, "name": "Problem Set 4", "due_at": "2026-10-01T23:59:00Z"}]),
    )
    client = CanvasClient(BASE_URL, token="tok", session=session)

    assignments = client.get_assignments("42")
    assert assignments[0]["name"] == "Problem Set 4"


def test_calendar_events_empty_context_codes_short_circuits():
    session = FakeCanvasSession()
    client = CanvasClient(BASE_URL, token="tok", session=session)
    assert client.get_calendar_events([]) == []
    assert session.requested_urls == []


def test_401_raises_clear_error_without_leaking_token():
    session = FakeCanvasSession()
    session.add(
        f"{BASE_URL}/api/v1/courses",
        {"enrollment_state": "active", "per_page": 100},
        FakeResponse(None, status_code=401),
    )
    client = CanvasClient(BASE_URL, token="THE-SECRET-TOKEN", session=session)

    with pytest.raises(CanvasAPIError) as exc_info:
        client.get_active_courses()

    assert "THE-SECRET-TOKEN" not in str(exc_info.value)
    assert "401" in str(exc_info.value) or "Unauthorized" in str(exc_info.value)


def test_non_list_response_raises_clear_error():
    session = FakeCanvasSession()
    session.add(
        f"{BASE_URL}/api/v1/courses",
        {"enrollment_state": "active", "per_page": 100},
        FakeResponse({"error": "unexpected shape"}),
    )
    client = CanvasClient(BASE_URL, token="tok", session=session)

    with pytest.raises(CanvasAPIError, match="Expected a list"):
        client.get_active_courses()

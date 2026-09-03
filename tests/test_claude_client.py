from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from asos.llm.anthropic_client import AnthropicClaudeClient, ClaudeAPIError


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def test_complete_returns_joined_text_blocks():
    fake_response = _FakeResponse({"content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]})
    with patch("requests.post", return_value=fake_response) as mock_post:
        client = AnthropicClaudeClient(api_key="fake-key")
        result = client.complete("say hi")

    assert result == "hello world"
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "fake-key"
    assert call_kwargs["json"]["messages"] == [{"role": "user", "content": "say hi"}]


def test_401_raises_clear_error_without_leaking_key():
    fake_response = _FakeResponse(None, status_code=401)
    with patch("requests.post", return_value=fake_response):
        client = AnthropicClaudeClient(api_key="THE-SECRET-KEY")
        with pytest.raises(ClaudeAPIError) as exc_info:
            client.complete("hi")

    assert "THE-SECRET-KEY" not in str(exc_info.value)


def test_network_error_raises_clear_error():
    with patch("requests.post", side_effect=requests.ConnectionError("no route")):
        client = AnthropicClaudeClient(api_key="fake-key")
        with pytest.raises(ClaudeAPIError, match="Network error"):
            client.complete("hi")


def test_ignores_non_text_content_blocks():
    fake_response = _FakeResponse(
        {"content": [{"type": "tool_use", "input": {}}, {"type": "text", "text": "final answer"}]}
    )
    with patch("requests.post", return_value=fake_response):
        client = AnthropicClaudeClient(api_key="fake-key")
        result = client.complete("hi")
    assert result == "final answer"

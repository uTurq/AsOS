"""
Real Claude API client, implementing the `ClaudeClient` protocol from
asos.llm.client (`.complete(prompt) -> str`).

NOT verified against a live call from this sandbox — this environment
has no anthropic_api_key configured and making a real, billed API call
without the user's explicit knowledge would be inappropriate. The HTTP
shape here (endpoint, headers, request/response format) matches
Anthropic's published Messages API. Verify with a real key on the
target machine before relying on this for anything user-facing.

Uses `requests` directly rather than the `anthropic` Python SDK to
avoid adding a second HTTP-adjacent dependency beyond what Canvas sync
already uses — this is a single, simple POST, not worth a whole SDK.
"""

from __future__ import annotations

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Haiku-class model: this is a structured-extraction task (pull a few
# facts out of a syllabus), not something that needs frontier-level
# reasoning — cheapest capable model is the right default for a
# single-user local app making its own API calls.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 1024


class ClaudeAPIError(RuntimeError):
    """Message never includes the API key."""


class AnthropicClaudeClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS):
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        try:
            response = requests.post(
                API_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30.0,
            )
        except requests.RequestException as exc:
            raise ClaudeAPIError(f"Network error contacting the Claude API: {exc}") from None

        if response.status_code == 401:
            raise ClaudeAPIError("Claude API rejected the API key (401). anthropic_api_key is likely invalid.")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ClaudeAPIError(f"Claude API returned an error: {exc}") from None

        payload = response.json()
        text_blocks = [block["text"] for block in payload.get("content", []) if block.get("type") == "text"]
        return "".join(text_blocks)

"""
The Claude client interface shared across every module that calls
Claude (document extraction, the core assistant, and eventually
voice). One small Protocol, same injectable-DI pattern used for
keyring and the Canvas HTTP session — every real call is fully
testable against a fake without touching the network or an API key.
"""

from __future__ import annotations

from typing import Protocol


class ClaudeClient(Protocol):
    def complete(self, prompt: str) -> str: ...

"""Test doubles shared across the test suite."""

from __future__ import annotations


class InMemoryKeyringBackend:
    """A fake satisfying asos.credentials.KeyringBackend, backed by a dict.

    Mirrors real keyring semantics closely enough for our tests:
    get_password returns None if absent, delete_password raises if absent.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self._store.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self._store[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        key = (service_name, username)
        if key not in self._store:
            raise KeyError(username)
        del self._store[key]

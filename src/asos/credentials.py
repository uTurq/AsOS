"""
Credential vault abstraction.

Secrets (Canvas API token, Anthropic API key, etc.) are stored in the
OS-native credential store via the `keyring` library:
  - Windows -> Windows Credential Manager
  - macOS   -> Keychain
  - Linux   -> Secret Service / KWallet (falls back to a locked "fail"
              backend if none is available, e.g. in a headless
              container — see tests for how that's handled)

Hard rules enforced by this module:
  - Secret values are never written to logs. Every log call in this
    module logs the credential *name*, never the value.
  - Secret values are never returned in string representations of
    any object here.
  - Nothing in this module ever raises with the secret value embedded
    in the exception message.

This module is the ONLY place in AsOS that should call `keyring`
directly. Everything else asks CredentialVault for what it needs.
"""

from __future__ import annotations

import logging
from typing import Protocol

from asos.config import CREDENTIAL_SERVICE_NAME

logger = logging.getLogger(__name__)


# Well-known credential names. Centralizing these avoids typos silently
# creating a second, orphaned entry in the OS credential store.
CANVAS_API_TOKEN = "canvas_api_token"
CANVAS_BASE_URL = "canvas_base_url"
ANTHROPIC_API_KEY = "anthropic_api_key"

KNOWN_CREDENTIAL_NAMES = frozenset(
    {CANVAS_API_TOKEN, CANVAS_BASE_URL, ANTHROPIC_API_KEY}
)


class KeyringBackend(Protocol):
    """The subset of the `keyring` module's interface we depend on.

    Defined as a Protocol so tests can substitute an in-memory fake
    without monkeypatching the real OS credential store.
    """

    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class CredentialNotFoundError(KeyError):
    """Raised when a requested credential does not exist in the vault."""


class CredentialVault:
    """Thin, safety-focused wrapper around an OS-native credential store."""

    def __init__(self, backend: KeyringBackend | None = None, service_name: str | None = None):
        if backend is None:
            import keyring as _keyring  # imported lazily so tests never need the real backend

            backend = _keyring
        self._backend = backend
        self._service_name = service_name or CREDENTIAL_SERVICE_NAME

    def set_credential(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("Refusing to store an empty credential value.")
        self._backend.set_password(self._service_name, name, value)
        logger.info("credential stored", extra={"credential_name": name})

    def get_credential(self, name: str) -> str:
        value = self._backend.get_password(self._service_name, name)
        if value is None:
            logger.warning("credential requested but not found", extra={"credential_name": name})
            raise CredentialNotFoundError(name)
        return value

    def get_credential_or_none(self, name: str) -> str | None:
        try:
            return self.get_credential(name)
        except CredentialNotFoundError:
            return None

    def has_credential(self, name: str) -> bool:
        return self.get_credential_or_none(name) is not None

    def delete_credential(self, name: str) -> None:
        try:
            self._backend.delete_password(self._service_name, name)
            logger.info("credential deleted", extra={"credential_name": name})
        except Exception:
            # keyring backends raise different "not found" exception types;
            # deleting something absent is not an error condition for us.
            logger.info(
                "credential delete requested but no entry existed",
                extra={"credential_name": name},
            )

    def __repr__(self) -> str:  # never leak secrets via repr/debugger inspection
        return f"CredentialVault(service_name={self._service_name!r})"

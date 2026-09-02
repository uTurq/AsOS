import logging

import pytest

from asos.credentials import CANVAS_API_TOKEN, CredentialNotFoundError, CredentialVault
from tests.fakes import InMemoryKeyringBackend


@pytest.fixture
def vault() -> CredentialVault:
    return CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")


def test_set_and_get_roundtrip(vault: CredentialVault):
    vault.set_credential(CANVAS_API_TOKEN, "super-secret-token")
    assert vault.get_credential(CANVAS_API_TOKEN) == "super-secret-token"


def test_missing_credential_raises(vault: CredentialVault):
    with pytest.raises(CredentialNotFoundError):
        vault.get_credential(CANVAS_API_TOKEN)


def test_get_or_none_returns_none_when_missing(vault: CredentialVault):
    assert vault.get_credential_or_none(CANVAS_API_TOKEN) is None


def test_has_credential(vault: CredentialVault):
    assert vault.has_credential(CANVAS_API_TOKEN) is False
    vault.set_credential(CANVAS_API_TOKEN, "token-value")
    assert vault.has_credential(CANVAS_API_TOKEN) is True


def test_delete_credential(vault: CredentialVault):
    vault.set_credential(CANVAS_API_TOKEN, "token-value")
    vault.delete_credential(CANVAS_API_TOKEN)
    assert vault.has_credential(CANVAS_API_TOKEN) is False


def test_delete_nonexistent_credential_does_not_raise(vault: CredentialVault):
    vault.delete_credential(CANVAS_API_TOKEN)  # should not raise


def test_empty_value_rejected(vault: CredentialVault):
    with pytest.raises(ValueError):
        vault.set_credential(CANVAS_API_TOKEN, "")


def test_secret_value_never_appears_in_logs(vault: CredentialVault, caplog):
    secret = "THIS-MUST-NEVER-BE-LOGGED-abc123"
    with caplog.at_level(logging.DEBUG):
        vault.set_credential(CANVAS_API_TOKEN, secret)
        vault.get_credential(CANVAS_API_TOKEN)
        vault.delete_credential(CANVAS_API_TOKEN)
    for record in caplog.records:
        assert secret not in record.getMessage()
        assert secret not in str(record.__dict__)


def test_repr_never_leaks_secrets(vault: CredentialVault):
    vault.set_credential(CANVAS_API_TOKEN, "THIS-MUST-NEVER-APPEAR-IN-REPR")
    assert "THIS-MUST-NEVER-APPEAR-IN-REPR" not in repr(vault)

from __future__ import annotations

from asos.credentials import CANVAS_API_TOKEN, CANVAS_BASE_URL, CredentialVault, ICS_FEED_URL
from asos.service.core import CoreService
from asos.service.jobs import register_default_jobs
from tests.fakes import InMemoryKeyringBackend


def _service_with_vault(vault: CredentialVault) -> CoreService:
    return CoreService(heartbeat_interval_seconds=1, credential_vault=vault)


def test_no_canvas_or_ics_credentials_only_registers_notification_scan(isolated_data_dir):
    vault = CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")
    service = _service_with_vault(vault)

    register_default_jobs(service)

    job_names = {j.name for j in service._jobs}
    assert job_names == {"notification_scan"}


def test_canvas_credentials_present_registers_canvas_sync(isolated_data_dir):
    vault = CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")
    vault.set_credential(CANVAS_BASE_URL, "https://school.instructure.com")
    vault.set_credential(CANVAS_API_TOKEN, "fake-token")
    service = _service_with_vault(vault)

    register_default_jobs(service)

    job_names = {j.name for j in service._jobs}
    assert "canvas_sync" in job_names


def test_only_partial_canvas_credentials_does_not_register_canvas_sync(isolated_data_dir):
    vault = CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")
    vault.set_credential(CANVAS_BASE_URL, "https://school.instructure.com")
    # no token set
    service = _service_with_vault(vault)

    register_default_jobs(service)

    job_names = {j.name for j in service._jobs}
    assert "canvas_sync" not in job_names


def test_ics_feed_url_present_registers_ics_sync(isolated_data_dir):
    vault = CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")
    vault.set_credential(ICS_FEED_URL, "https://school.instructure.com/feeds/calendars/abc.ics")
    service = _service_with_vault(vault)

    register_default_jobs(service)

    job_names = {j.name for j in service._jobs}
    assert "ics_sync" in job_names
    assert "canvas_sync" not in job_names


def test_notification_scan_always_registered_regardless_of_credentials(isolated_data_dir):
    vault = CredentialVault(backend=InMemoryKeyringBackend(), service_name="AsOS-Test")
    vault.set_credential(CANVAS_BASE_URL, "https://school.instructure.com")
    vault.set_credential(CANVAS_API_TOKEN, "fake-token")
    vault.set_credential(ICS_FEED_URL, "https://school.instructure.com/feeds/calendars/abc.ics")
    service = _service_with_vault(vault)

    register_default_jobs(service)

    job_names = {j.name for j in service._jobs}
    assert job_names == {"canvas_sync", "ics_sync", "notification_scan"}

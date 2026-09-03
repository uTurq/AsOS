"""
Default job registration.

Kept separate from CoreService itself so the scheduler stays generic
and testable without any credential/network dependencies. This module
is the one place that decides "given what's configured, what should
actually run periodically" -- CoreService just runs whatever it's
handed.
"""

from __future__ import annotations

import logging

from asos.credentials import CANVAS_API_TOKEN, CANVAS_BASE_URL, ICS_FEED_URL
from asos.service.core import CoreService

logger = logging.getLogger("asos.service.jobs")

CANVAS_SYNC_INTERVAL_SECONDS = 30 * 60  # 30 minutes
ICS_SYNC_INTERVAL_SECONDS = 60 * 60  # 1 hour
NOTIFICATION_SCAN_INTERVAL_SECONDS = 15 * 60  # 15 minutes


def register_default_jobs(service: CoreService) -> None:
    vault = service.credential_vault

    canvas_base_url = vault.get_credential_or_none(CANVAS_BASE_URL)
    canvas_token = vault.get_credential_or_none(CANVAS_API_TOKEN)
    if canvas_base_url and canvas_token:
        def _canvas_sync_job(session, _base_url=canvas_base_url, _token=canvas_token):
            from asos.canvas.client import CanvasClient
            from asos.canvas.sync import CanvasSyncWorker

            worker = CanvasSyncWorker(CanvasClient(_base_url, _token))
            worker.sync_all(session)

        service.register_job("canvas_sync", CANVAS_SYNC_INTERVAL_SECONDS, _canvas_sync_job)
    else:
        logger.info("canvas_sync job not registered (credentials not set)")

    ics_feed_url = vault.get_credential_or_none(ICS_FEED_URL)
    if ics_feed_url:
        def _ics_sync_job(session, _url=ics_feed_url):
            from asos.calendar_feed.sync import fetch_ics, sync_ics_text

            ics_text = fetch_ics(_url)
            sync_ics_text(session, ics_text)

        service.register_job("ics_sync", ICS_SYNC_INTERVAL_SECONDS, _ics_sync_job)
    else:
        logger.info("ics_sync job not registered (ics_feed_url not set)")

    def _notification_scan_job(session):
        from asos.notifications.scan import scan_for_notifications

        scan_for_notifications(session)

    service.register_job("notification_scan", NOTIFICATION_SCAN_INTERVAL_SECONDS, _notification_scan_job)

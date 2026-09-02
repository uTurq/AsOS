"""
Logging configuration.

Rule: nothing that touches asos.credentials ever logs a secret value
(enforced by convention in that module — it only ever logs credential
*names*). This module's job is just to make sure logs land somewhere
useful (console + a rotating file in the OS-correct log dir) without
accidentally widening what gets captured — e.g. we deliberately do NOT
log full HTTP request/response bodies at INFO level anywhere in AsOS,
since that's the most common way credentials leak into logs by accident.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from asos.config import get_log_dir


def configure_logging(*, level: int = logging.INFO, log_to_file: bool = True) -> None:
    root = logging.getLogger("asos")
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    if log_to_file:
        log_path = get_log_dir() / "asos.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    root.propagate = False

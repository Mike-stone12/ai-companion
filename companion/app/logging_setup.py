from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from companion.paths import LOG_DIR

LOG_FILE_NAME = "companion.log"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3


class _CompanionHandler:
    """Marker so repeated setup replaces only the handlers it installed."""


class _ConsoleHandler(_CompanionHandler, logging.StreamHandler):
    pass


class _FileHandler(_CompanionHandler, RotatingFileHandler):
    pass


def setup_logging(level: str | None = None, log_dir: Path = LOG_DIR) -> Path:
    requested = (level or os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    resolved = logging.getLevelName(requested)
    invalid = not isinstance(resolved, int)
    if invalid:
        resolved = logging.INFO

    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, _CompanionHandler):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    console = _ConsoleHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME
    file_handler = _FileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    root.setLevel(resolved)
    if invalid:
        logging.getLogger(__name__).warning("Unknown LOG_LEVEL %r, using INFO", requested)
    return log_file

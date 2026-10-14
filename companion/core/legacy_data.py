from __future__ import annotations

import logging
import shutil
from pathlib import Path

from companion.paths import LEGACY_MEMORY_PATH, MEMORY_PATH

logger = logging.getLogger(__name__)


def migrate_legacy_file(legacy: Path, target: Path) -> bool:
    if not legacy.exists():
        return False
    if target.exists():
        logger.warning("%s not migrated: %s already exists; keeping both", legacy, target)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(target))
    logger.info("Moved %s to %s", legacy, target)
    return True


def migrate_legacy_data() -> None:
    migrate_legacy_file(LEGACY_MEMORY_PATH, MEMORY_PATH)

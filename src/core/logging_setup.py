"""Logging setup with daily rotation (AGENTS.md section 2).

Log files go to ``<log_dir>/webbox_YYYY-MM-DD.log``, rotated at midnight
and kept for 30 days. A console handler mirrors everything at the
configured level. All log messages are English.
"""

from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

_configured = False


def setup_logging(level: str = "INFO", log_dir: Path | str = Path("logs")) -> None:
    """Configure root logging with a daily-rotating file handler.

    Safe to call multiple times: the second and later calls only adjust
    the level (idempotent for app startup paths).

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory to store log files in (created if missing).
    """
    global _configured
    root = logging.getLogger()
    level_num = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(level_num)

    if _configured:
        for handler in root.handlers:
            handler.setLevel(level_num)
        return

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"webbox_{datetime.now():%Y-%m-%d}.log"

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level_num)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level_num)
    root.addHandler(console)

    # Third-party noise reduction
    for noisy in ("httpx", "httpcore", "urllib3", "matplotlib"):
        logging.getLogger(noisy).setLevel(max(level_num, logging.WARNING))

    _configured = True
    logging.getLogger(__name__).info(
        "Logging initialized (level=%s, file=%s)", level.upper(), log_file
    )

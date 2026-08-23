"""One logger factory used by every script. Logs to stdout and appends to
artifacts/logs/<name>.log on Drive so a Colab disconnect doesn't lose the
run history. No bare `print` in library code — scripts may still print
user-facing summaries/tables, but progress/diagnostic messages go through
this logger.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional


_CONFIGURED: set[str] = set()


def get_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if name in _CONFIGURED:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    if log_file is None:
        try:
            from . import config

            log_file = str(config.PATHS.log_file(name))
        except Exception:
            log_file = None

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:
            # Drive not mounted yet, or path unwritable — stdout logging
            # still works, so don't fail the whole script over this.
            pass

    _CONFIGURED.add(name)
    return logger

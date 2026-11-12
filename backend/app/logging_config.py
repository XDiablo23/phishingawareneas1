"""Application logging.

Most of what an operator needs to see is either written to the `AuditLog`
table or returned in the HTTP response. Neither covers the case where a
campaign is *mis*configured: an `unmapped` ingestion result deliberately
withholds the campaign ref and email that failed to resolve, because
echoing them back would turn a secret-gated endpoint into a roster-
enumeration oracle. Those identifiers still have to reach someone with
legitimate access, or nobody can work out which recipient was missing -
which is what this logger is for.

Uvicorn owns the root logger for its own access/error output, so this
attaches a handler to the application's own namespace instead and disables
propagation - otherwise every record would be printed twice.
"""

from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "phishawareness"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging() -> logging.Logger:
    """Install the app's log handler. Idempotent - the test suite imports the
    application repeatedly in one process, and a second handler would double
    every line."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Child logger under the app namespace. Call as `get_logger(__name__)`."""
    return logging.getLogger(LOGGER_NAME).getChild(name.rsplit(".", 1)[-1])

"""Automation toolkit for affiliate product discovery and publishing."""

import logging
import os

__version__ = "0.1.0"


def configure_logging() -> None:
    """Configura logging para stdout com nível controlado por LOG_LEVEL (default INFO)."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

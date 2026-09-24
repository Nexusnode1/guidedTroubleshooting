"""Logging configuration interface."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure basic application logging."""
    # TODO: Extend with project-specific structured logging if needed.
    logging.basicConfig(level=level)

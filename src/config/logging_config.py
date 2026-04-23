"""
Centralized logging configuration for the Owlynn application.

Call ``setup_logging()`` once at application startup (e.g. in the FastAPI lifespan
or main entry point) to configure structured logging with consistent formatting.
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with structured output and consistent format.

    Parameters
    ----------
    level : int
        Logging level (default: ``logging.INFO``). Set to ``logging.DEBUG``
        for verbose output during development.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if called more than once
    root.handlers.clear()
    root.addHandler(handler)

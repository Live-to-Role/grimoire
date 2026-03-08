"""Centralized logging configuration."""

import logging
import logging.handlers

from grimoire.config import settings

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Noisy third-party loggers to suppress
NOISY_LOGGERS = [
    "uvicorn.access",
    "httpcore",
    "httpx",
    "aiosqlite",
    "sqlalchemy.engine",
]


def setup_logging() -> None:
    """Configure logging for the application.

    Sets up console handler (always) and optional rotating file handler.
    Suppresses noisy third-party loggers.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()

    # Clear existing handlers to avoid duplicates on re-init
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler (optional)
    if settings.log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Suppress noisy loggers
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

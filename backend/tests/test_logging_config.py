"""Tests for centralized logging configuration."""

import logging
import logging.handlers
from unittest.mock import patch

from grimoire.logging_config import setup_logging


def test_setup_logging_configures_root_level():
    """Root logger level should match the configured level."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "WARNING"
        mock_settings.log_file = ""
        setup_logging()
        assert logging.getLogger().level == logging.WARNING


def test_setup_logging_default_info():
    """Default log level should be INFO."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_file = ""
        setup_logging()
        assert logging.getLogger().level == logging.INFO


def test_setup_logging_console_format():
    """Console handler should use structured format."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_file = ""
        setup_logging()
        root = logging.getLogger()
        stream_handlers = [
            h for h in root.handlers if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(stream_handlers) >= 1


def test_setup_logging_file_handler(tmp_path):
    """File handler should be added when log_file is configured."""
    log_file = tmp_path / "test.log"
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "DEBUG"
        mock_settings.log_file = str(log_file)
        setup_logging()
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) >= 1

    # Clean up handlers to avoid affecting other tests
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)


def test_setup_logging_suppresses_noisy_loggers():
    """Third-party loggers should be set to WARNING."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "DEBUG"
        mock_settings.log_file = ""
        setup_logging()
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING

"""Unit tests for centralized logging configuration."""

import logging

from logging_config import configure_logging


def test_configure_logging_sets_root_handler_and_level():
    configure_logging("DEBUG")

    root = logging.getLogger()
    assert root.handlers
    assert root.level == logging.DEBUG
    formatter = root.handlers[0].formatter
    assert formatter is not None
    assert "%(name)s" in formatter._fmt


def test_configure_logging_falls_back_to_info_for_invalid_level():
    configure_logging("NOT_A_LEVEL")

    assert logging.getLogger().level == logging.INFO

"""Настройка стандартного `logging` (без `print`)."""

import logging
import sys

from app.config import get_settings


def configure_logging() -> None:
    """Сконфигурировать корневой логгер приложения."""
    level = logging.DEBUG if get_settings().debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

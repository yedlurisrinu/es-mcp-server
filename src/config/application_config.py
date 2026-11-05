"""Application config — loads resources/application-config.yaml into a module-level dict."""

import logging
from pathlib import Path
from typing import Any

from yaml import safe_load

logger = logging.getLogger(__name__)
app_config: dict[str, Any] = {}
BASE_PATH = str(Path(__file__).resolve().parent.parent)


def load_config() -> None:
    """Load application-config.yaml into the module-level ``app_config`` dict (idempotent)."""
    global app_config
    try:
        with open(
            BASE_PATH + "/resources/application-config.yaml", encoding="utf-8"
        ) as fh:
            app_config = safe_load(fh)
    except FileNotFoundError:
        logger.exception("Exception while loading application configuration")


def get_config(key: str) -> Any:
    """Return a config value by key. Raises ``KeyError`` if the key is absent."""
    return app_config[key]

import json
import logging
import logging.config
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logging(config_file: str = "logging_config.json") -> None:
    """Loads the logging configuration; the file handler's log file name gets the replica id appended."""
    path = str(Path(__file__).resolve().parent.parent)
    replica_id = os.environ.get("REPLICA_ID") or socket.gethostname()
    try:
        with open(path + "/resources/" + config_file) as file_handler:
            config = json.load(file_handler)
            filename = config["handlers"]["file"]["filename"]
            parts = filename.rpartition(".")
            config["handlers"]["file"]["filename"] = (
                parts[0] + "-" + replica_id + parts[1] + parts[2]
            )
        logging.config.dictConfig(config)
        logger.info(
            "Logging configured for replica %s, log file %s",
            replica_id,
            config["handlers"]["file"]["filename"],
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)
        logger.exception("Failed to load application logging")

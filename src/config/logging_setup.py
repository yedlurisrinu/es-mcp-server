import os
from pathlib import Path

# Start scheduler
import json
import logging
import logging.config
import socket

logger = logging.getLogger(__file__)

def setup_logging(config_file : str ="logging_config.json") -> None:
    """Loads the logging configuration."""
    logger.info("Logging configuration starting.")
    path = str(Path(__file__).resolve().parent.parent)
    replica_id = os.environ.get("REPLICA_ID") or socket.gethostname()
    print(f" Logging replica id = {replica_id}")
    try:
        with open(path + "/resources/" + config_file) as file_handler:
            config = json.load(file_handler)
            filename = config['handlers']['file']['filename']
            parts = filename.rpartition('.')
            config['handlers']['file']['filename'] = parts[0]+"-"+replica_id+parts[1]+parts[2]
            print(" Log File Name: ",config['handlers']['file']['filename'])
        logging.config.dictConfig(config)
    except Exception as fe:
        logging.basicConfig(level=logging.INFO)
        logger.error(f"Failed to load application logging {fe}", exc_info=True)
    logger.info("Logging configured and application starting.")


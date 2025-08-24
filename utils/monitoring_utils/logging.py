import logging
import logging.handlers
import os
import coloredlogs
from datetime import datetime
from typing import Optional

# Directory for logs
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Log file name with date
LOG_FILE = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.log")

# Centralized logger
def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger instance with both console and file handlers.
    This logger is thread-safe and works across the entire application.
    The console handler is handled by coloredlogs for colorful output.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Set to lowest level, handlers will filter

    if not logger.hasHandlers():  # Avoid duplicate handlers
        
        # This handler will write all logs to a file.
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # File: store all logs
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        
        # Attach the file handler to the logger
        logger.addHandler(file_handler)

        # Install coloredlogs to handle the console output.
        # It automatically adds a StreamHandler with colors.
        coloredlogs.install(
            level='INFO', 
            logger=logger,
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
        )
        
    return logger
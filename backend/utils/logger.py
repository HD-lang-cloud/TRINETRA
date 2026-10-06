import logging
import sys
from typing import Optional


def setup_logger(name: str = "trinetra", level: Optional[str] = "INFO") -> logging.Logger:
    """
    Configures and returns a structured logger for TRINETRA.
    Outputs clean, standardized log entries with timestamps, component names, and log levels.
    """
    logger = logging.getLogger(name)
    numeric_level = getattr(logging, level.upper() if level else "INFO", logging.INFO)
    logger.setLevel(numeric_level)

    # Avoid adding multiple duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric_level)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


# Default application logger
app_logger = setup_logger("trinetra")

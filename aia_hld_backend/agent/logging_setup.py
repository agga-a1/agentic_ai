# agent/logging_setup.py

import logging
import sys

_LOGGER_INITIALIZED = False

def get_logger(name: str):
    global _LOGGER_INITIALIZED

    logger = logging.getLogger("uvicorn.error")
    logger.setLevel(logging.INFO)

    # ✅ Attach handler EXACTLY ONCE
    if not _LOGGER_INITIALIZED:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        _LOGGER_INITIALIZED = True

    return logger
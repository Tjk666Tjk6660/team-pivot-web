from __future__ import annotations

import logging
import os
import sys

VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_NOISY_LIBS = ("lark_oapi", "httpx", "httpcore", "urllib3")


def configure_logging(level: str | None = None) -> None:
    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    if resolved not in VALID_LEVELS:
        resolved = "INFO"

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s] %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S%z",
        )
    )
    root.addHandler(handler)
    root.setLevel(resolved)

    for name in _NOISY_LIBS:
        logging.getLogger(name).setLevel(logging.WARNING)

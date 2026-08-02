"""Lightweight timing instrumentation.

Emits one INFO log line per measured span so we can see where wall-clock time
goes (Plaid round trips vs. our DB work) without pulling in a profiler. Uvicorn
configures the root logger, so these surface in the backend console.
"""

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("app.perf")


@contextmanager
def timed(label: str, **fields):
    """Log how long the wrapped block took, e.g. `timing plaid.sync 812ms pages=4`."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        suffix = "".join(f" {key}={value}" for key, value in fields.items())
        logger.info("timing %s %.0fms%s", label, elapsed_ms, suffix)

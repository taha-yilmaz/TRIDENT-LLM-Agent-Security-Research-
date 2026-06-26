"""
utils/groq_backoff.py
=====================
Retry helpers for Groq API rate limits (HTTP 429 / TPM), used by the crew
runner and the security evaluator without adding new dependencies.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_groq_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "rate_limit" in msg
        or "rate limit" in msg
        or "tokens per minute" in msg
    )


def _backoff_seconds(exc: BaseException, attempt: int) -> float:
    m = re.search(r"try again in ([\d.]+)\s*s", str(exc), re.IGNORECASE)
    if m:
        return float(m.group(1)) + 0.75
    return min(2.0 * (2**attempt), 45.0)


def run_with_groq_rate_limit_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 8,
    what: str = "Groq call",
) -> T:
    """
    Run *fn* and retry on Groq TPM / 429 errors with exponential backoff
    (or server-suggested wait from the error message).
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except BaseException as exc:
            if not is_groq_rate_limit_error(exc):
                raise
            if attempt >= max_attempts - 1:
                raise
            delay = _backoff_seconds(exc, attempt)
            logger.warning(
                "%s rate-limited (attempt %d/%d), sleeping %.1fs: %s",
                what,
                attempt + 1,
                max_attempts,
                delay,
                exc,
            )
            time.sleep(delay)

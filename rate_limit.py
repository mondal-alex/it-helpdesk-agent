"""Basic retry + concurrency guards for Gemini and Jira API calls."""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from collections.abc import Callable
from typing import TypeVar

import requests

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP = frozenset({408, 429, 503})
_RETRY_AFTER_HEADERS = ("Retry-After", "Beta-Retry-After")
_LLM_RETRY_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "quota exceeded",
)

T = TypeVar("T")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def parse_retry_after(response: requests.Response) -> float | None:
    """Parse Retry-After (seconds) from a Jira throttling response."""
    for header in _RETRY_AFTER_HEADERS:
        value = response.headers.get(header)
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def retry_delay_seconds(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter; honor Retry-After when provided."""
    max_delay = _env_float("API_RETRY_MAX_DELAY", 60.0)
    if retry_after is not None:
        return min(retry_after, max_delay)

    initial = _env_float("API_RETRY_INITIAL_DELAY", 1.0)
    delay = min(initial * (2**attempt), max_delay)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def is_retryable_llm_error(exc: BaseException) -> bool:
    """Detect transient Gemini rate-limit / overload errors from LangChain."""
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is not None and response.status_code in _RETRYABLE_HTTP:
            return True

    message = str(exc).casefold()
    if any(marker in message for marker in _LLM_RETRY_MARKERS):
        return True

    status_match = re.search(r"\b(429|503|408)\b", message)
    return status_match is not None


class _ConcurrencyGate:
    def __init__(self, limit: int) -> None:
        self._semaphore = threading.Semaphore(limit)

    def __enter__(self) -> _ConcurrencyGate:
        self._semaphore.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self._semaphore.release()


_jira_gate: _ConcurrencyGate | None = None
_llm_gate: _ConcurrencyGate | None = None


def bulk_mode_enabled() -> bool:
    """Fast path for seeding + triaging all 50 eval tickets (e.g. Loom demo)."""
    return os.getenv("EVAL_BULK_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _default_llm_concurrent() -> int:
    return 12 if bulk_mode_enabled() else 2


def _default_jira_concurrent() -> int:
    return 8 if bulk_mode_enabled() else 3


def _jira_gate_get() -> _ConcurrencyGate:
    global _jira_gate
    if _jira_gate is None:
        _jira_gate = _ConcurrencyGate(
            _env_int("JIRA_MAX_CONCURRENT", _default_jira_concurrent())
        )
    return _jira_gate


def _llm_gate_get() -> _ConcurrencyGate:
    global _llm_gate
    if _llm_gate is None:
        _llm_gate = _ConcurrencyGate(
            _env_int("LLM_MAX_CONCURRENT", _default_llm_concurrent())
        )
    return _llm_gate


def reset_concurrency_gates() -> None:
    """Reset lazy gates (for tests after env changes)."""
    global _jira_gate, _llm_gate
    _jira_gate = None
    _llm_gate = None


def jira_request(method: str, url: str, **kwargs) -> requests.Response:
    """Jira HTTP call with concurrency cap and 429/503 retry (Atlassian guidance)."""
    max_attempts = _env_int("API_RETRY_MAX_ATTEMPTS", 5)

    with _jira_gate_get():
        for attempt in range(max_attempts):
            response = requests.request(method, url, **kwargs)
            if response.status_code not in _RETRYABLE_HTTP:
                return response
            if attempt >= max_attempts - 1:
                return response

            delay = retry_delay_seconds(attempt, parse_retry_after(response))
            logger.warning(
                "Jira %s %s returned %s; retrying in %.1fs (%s/%s)",
                method,
                url,
                response.status_code,
                delay,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay)

    raise RuntimeError("unreachable")


def run_with_llm_retry(func: Callable[[], T]) -> T:
    """Run a Gemini/LangChain call with concurrency cap and 429 retry."""
    max_attempts = _env_int("API_RETRY_MAX_ATTEMPTS", 5)

    with _llm_gate_get():
        for attempt in range(max_attempts):
            try:
                return func()
            except Exception as exc:
                if not is_retryable_llm_error(exc) or attempt >= max_attempts - 1:
                    raise

                delay = retry_delay_seconds(attempt)
                logger.warning(
                    "Gemini call failed with retryable error (%s); "
                    "retrying in %.1fs (%s/%s)",
                    type(exc).__name__,
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)

    raise RuntimeError("unreachable")

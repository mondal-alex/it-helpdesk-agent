"""Unit tests for API retry and concurrency helpers."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from rate_limit import (
    is_retryable_llm_error,
    jira_request,
    parse_retry_after,
    retry_delay_seconds,
    run_with_llm_retry,
)


def test_parse_retry_after_uses_header():
    response = MagicMock()
    response.headers = {"Retry-After": "3"}

    assert parse_retry_after(response) == 3.0


def test_parse_retry_after_falls_back_to_beta_header():
    response = MagicMock()
    response.headers = {"Beta-Retry-After": "5"}

    assert parse_retry_after(response) == 5.0


def test_retry_delay_seconds_honors_retry_after():
    assert retry_delay_seconds(attempt=2, retry_after=4.0) == 4.0


def test_retry_delay_seconds_exponential_without_retry_after():
    with patch.dict("os.environ", {"API_RETRY_INITIAL_DELAY": "1", "API_RETRY_MAX_DELAY": "60"}):
        first = retry_delay_seconds(0)
        second = retry_delay_seconds(1)

    assert 1.0 <= first <= 1.25
    assert 2.0 <= second <= 2.5


def test_is_retryable_llm_error_detects_rate_limit_message():
    assert is_retryable_llm_error(RuntimeError("429 RESOURCE_EXHAUSTED")) is True
    assert is_retryable_llm_error(RuntimeError("invalid api key")) is False


def test_run_with_llm_retry_retries_then_succeeds():
    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("429 rate limit")
        return "ok"

    with patch.dict("os.environ", {"API_RETRY_MAX_ATTEMPTS": "3"}):
        assert run_with_llm_retry(flaky) == "ok"

    assert calls["count"] == 2


def test_jira_request_retries_on_429():
    throttled = MagicMock()
    throttled.status_code = 429
    throttled.headers = {"Retry-After": "0"}

    ok = MagicMock()
    ok.status_code = 200

    with patch("rate_limit.requests.request", side_effect=[throttled, ok]) as mock_request:
        with patch("rate_limit.time.sleep"):
            response = jira_request("GET", "https://example.atlassian.net/rest/api/3/search")

    assert response.status_code == 200
    assert mock_request.call_count == 2


def test_bulk_mode_raises_default_concurrency(monkeypatch):
    from rate_limit import (
        _default_jira_concurrent,
        _default_llm_concurrent,
        bulk_mode_enabled,
        reset_concurrency_gates,
    )

    monkeypatch.delenv("EVAL_BULK_MODE", raising=False)
    reset_concurrency_gates()
    assert bulk_mode_enabled() is False
    assert _default_llm_concurrent() == 2
    assert _default_jira_concurrent() == 3

    monkeypatch.setenv("EVAL_BULK_MODE", "1")
    reset_concurrency_gates()
    assert bulk_mode_enabled() is True
    assert _default_llm_concurrent() == 12
    assert _default_jira_concurrent() == 8


def test_jira_request_does_not_retry_client_errors():
    bad = MagicMock()
    bad.status_code = 400
    bad.headers = {}

    with patch("rate_limit.requests.request", return_value=bad) as mock_request:
        response = jira_request("GET", "https://example.atlassian.net/rest/api/3/issue/BTS-1")

    assert response.status_code == 400
    assert mock_request.call_count == 1

"""Thread-safe progress logging for live webhook triage."""

from __future__ import annotations

import logging
import os
import threading

from eval.report import eval_id_from_text, lookup_eval_ticket

logger = logging.getLogger(__name__)


def _expected_total() -> int:
    raw = os.getenv("EVAL_EXPECTED_COUNT", "50").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 50


class LivePipelineProgress:
    """Track queued, in-flight, and completed webhook triage runs."""

    def __init__(self, expected_total: int | None = None) -> None:
        self.expected_total = expected_total or _expected_total()
        self._lock = threading.Lock()
        self._in_flight: dict[str, str] = {}
        self._completed: dict[str, str] = {}

    def _eval_label(self, body: str) -> str:
        ticket = lookup_eval_ticket(body)
        if ticket:
            return ticket.id
        eval_id = eval_id_from_text(body)
        return eval_id or "?"

    def queued(self, issue_key: str, body: str) -> None:
        label = self._eval_label(body)
        with self._lock:
            in_flight = len(self._in_flight)
            done = len(self._completed)
        logger.info(
            "QUEUED  %s (%s) | %d in-flight, %d/%d done",
            issue_key,
            label,
            in_flight,
            done,
            self.expected_total,
        )

    def started(self, issue_key: str, body: str) -> None:
        label = self._eval_label(body)
        with self._lock:
            self._in_flight[issue_key] = label
            in_flight = len(self._in_flight)
            done = len(self._completed)
        logger.info(
            "START   %s (%s) | %d in-flight, %d/%d done",
            issue_key,
            label,
            in_flight,
            done,
            self.expected_total,
        )

    def finished(
        self,
        issue_key: str,
        body: str,
        *,
        action: str,
        success: bool,
    ) -> None:
        label = self._eval_label(body)
        with self._lock:
            self._in_flight.pop(issue_key, None)
            if success:
                self._completed[issue_key] = action
            done = len(self._completed)
            in_flight = len(self._in_flight)

        status = action if success else "FAILED"
        logger.info(
            "DONE    %s (%s) -> %s | %d in-flight, %d/%d done",
            issue_key,
            label,
            status,
            in_flight,
            done,
            self.expected_total,
        )
        if success and done >= self.expected_total and in_flight == 0:
            logger.info(
                "ALL DONE — %d/%d eval tickets processed.", done, self.expected_total
            )


_PROGRESS = LivePipelineProgress()


def live_progress() -> LivePipelineProgress:
    return _PROGRESS

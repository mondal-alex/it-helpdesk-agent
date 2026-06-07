"""CSV eval report rows and incremental live reporting from Jira webhooks."""

from __future__ import annotations

import csv
import logging
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from eval.metrics import citation_strings, score_ticket
from models import DeferDecision, ResolveDecision, TicketTriageResult
from tests.fixtures.eval_tickets import EVAL_TICKETS, EvalTicket

logger = logging.getLogger(__name__)

_EVAL_ID_RE = re.compile(r"\b(T-\d{3})\b", re.IGNORECASE)
_EVAL_BY_ID = {ticket.id: ticket for ticket in EVAL_TICKETS}
_EVAL_BY_BODY = {ticket.body.strip(): ticket for ticket in EVAL_TICKETS}

CSV_FIELDS = [
    "ticket_id",
    "jira_issue_key",
    "expected_action",
    "expected_citations",
    "expected_reason_code",
    "agent_action",
    "agent_citations",
    "agent_reason_code",
    "final_action",
    "final_citations",
    "final_reason_code",
    "gate_overridden",
    "action_correct",
    "citation_correct",
    "reason_correct",
    "false_resolve",
    "missed_resolve",
    "failure_analysis",
    "agent_answer",
    "final_answer",
    "processed_at",
]


def eval_id_from_text(text: str) -> str | None:
    """Extract an eval ticket id (e.g. T-001) from summary or body text."""
    match = _EVAL_ID_RE.search(text)
    if not match:
        return None
    ticket_id = match.group(1).upper()
    if ticket_id in _EVAL_BY_ID:
        return ticket_id
    return None


def lookup_eval_ticket(body: str) -> EvalTicket | None:
    """Match webhook ticket text to the eval set by id prefix or exact body."""
    normalized = body.strip()
    if not normalized:
        return None

    summary, description = (
        normalized.split("\n\n", 1) if "\n\n" in normalized else (normalized, "")
    )

    # Prefer the Jira summary line (seed script puts [T-xxx] there).
    eval_id = eval_id_from_text(summary)
    if eval_id:
        return _EVAL_BY_ID[eval_id]

    if description:
        eval_id = eval_id_from_text(description)
        if eval_id:
            return _EVAL_BY_ID[eval_id]

        by_description = _EVAL_BY_BODY.get(description.strip())
        if by_description:
            return by_description

    eval_id = eval_id_from_text(normalized)
    if eval_id:
        return _EVAL_BY_ID[eval_id]

    return _EVAL_BY_BODY.get(normalized)


def _decision_fields(decision) -> tuple[str, str, str]:
    if isinstance(decision, ResolveDecision):
        return (
            "RESOLVE",
            "; ".join(citation_strings(decision)),
            "",
        )
    assert isinstance(decision, DeferDecision)
    return (
        "DEFER",
        "; ".join(citation_strings(decision)),
        decision.reason_code.value,
    )


def failure_analysis(
    ticket: EvalTicket,
    score,
    *,
    gate_overridden: bool,
    agent_action: str,
    final_action: str,
) -> str:
    """Human-readable explanation when the final decision misses ground truth."""
    citation_ok = score.citation_correct is not False
    reason_ok = score.reason_correct is not False
    fully_correct = score.action_correct and citation_ok and reason_ok

    if fully_correct and not gate_overridden:
        return "OK"

    parts: list[str] = []
    if score.missed_resolve:
        parts.append("Missed RESOLVE: predicted DEFER, expected RESOLVE")
    elif score.false_resolve:
        parts.append("False RESOLVE: predicted RESOLVE, expected DEFER")
    elif not score.action_correct:
        parts.append(
            f"Wrong action: predicted {score.predicted_action.value}, "
            f"expected {ticket.expected_action.value}"
        )

    if score.citation_correct is False:
        expected = "; ".join(ticket.expected_citations)
        parts.append(f"Citation mismatch: expected {expected}")

    if score.reason_correct is False:
        expected_reason = (
            ticket.expected_reason_code.value if ticket.expected_reason_code else ""
        )
        parts.append(f"Reason code mismatch: expected {expected_reason}")

    if gate_overridden and agent_action != final_action:
        parts.append(
            f"Grounding gate overrode agent ({agent_action} -> {final_action})"
        )
    elif gate_overridden:
        parts.append(f"Grounding gate overrode agent decision ({agent_action})")

    if fully_correct and gate_overridden:
        parts.append("Final decision matches ground truth after gate override")

    return "; ".join(parts) if parts else "OK"


def build_row(
    ticket: EvalTicket,
    result: TicketTriageResult,
    *,
    jira_issue_key: str = "",
    processed_at: datetime | None = None,
) -> dict[str, str]:
    """Build one CSV row scored against eval ground truth (final decision)."""
    agent_action, agent_citations, agent_reason = _decision_fields(result.agent_decision)
    final_action, final_citations, final_reason = _decision_fields(result.final_decision)
    score = score_ticket(
        ticket,
        result.final_decision,
        gate_overridden=result.gate_overridden,
    )
    timestamp = processed_at or datetime.now(UTC)

    return {
        "ticket_id": ticket.id,
        "jira_issue_key": jira_issue_key,
        "expected_action": ticket.expected_action.value,
        "expected_citations": "; ".join(ticket.expected_citations),
        "expected_reason_code": (
            ticket.expected_reason_code.value if ticket.expected_reason_code else ""
        ),
        "agent_action": agent_action,
        "agent_citations": agent_citations,
        "agent_reason_code": agent_reason,
        "final_action": final_action,
        "final_citations": final_citations,
        "final_reason_code": final_reason,
        "gate_overridden": str(result.gate_overridden),
        "action_correct": str(score.action_correct),
        "citation_correct": (
            "" if score.citation_correct is None else str(score.citation_correct)
        ),
        "reason_correct": (
            "" if score.reason_correct is None else str(score.reason_correct)
        ),
        "false_resolve": str(score.false_resolve),
        "missed_resolve": str(score.missed_resolve),
        "failure_analysis": failure_analysis(
            ticket,
            score,
            gate_overridden=result.gate_overridden,
            agent_action=agent_action,
            final_action=final_action,
        ),
        "agent_answer": result.agent_decision.answer.replace("\n", " "),
        "final_answer": result.final_decision.answer.replace("\n", " "),
        "processed_at": timestamp.isoformat(),
    }


def _load_recorded_issue_keys(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["jira_issue_key"]
            for row in csv.DictReader(handle)
            if row.get("jira_issue_key")
        }


class LiveEvalReport:
    """Thread-safe incremental CSV writer for webhook-driven eval."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._recorded_issue_keys = _load_recorded_issue_keys(path)

    def append(self, row: dict[str, str]) -> bool:
        """Append a row; return False if this Jira issue was already recorded."""
        issue_key = row.get("jira_issue_key", "")
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if issue_key and issue_key in self._recorded_issue_keys:
                logger.warning(
                    "Live eval report skipped duplicate for Jira issue %s", issue_key
                )
                return False

            write_header = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=CSV_FIELDS,
                    extrasaction="ignore",
                )
                if write_header:
                    writer.writeheader()
                writer.writerow(row)

            if issue_key:
                self._recorded_issue_keys.add(issue_key)
            return True


_live_report: LiveEvalReport | None = None
_live_report_lock = threading.Lock()


def live_report_path() -> Path | None:
    raw = os.getenv("EVAL_LIVE_REPORT_PATH", "eval/live_results.csv").strip()
    if not raw or raw.lower() in {"off", "false", "0", "none"}:
        return None
    return Path(raw)


def reset_live_report_cache() -> None:
    """Clear cached writer (for tests or env changes)."""
    global _live_report
    with _live_report_lock:
        _live_report = None


def _get_live_report() -> LiveEvalReport | None:
    global _live_report
    path = live_report_path()
    if path is None:
        return None
    with _live_report_lock:
        if _live_report is None or _live_report.path != path:
            _live_report = LiveEvalReport(path)
        return _live_report


def record_live_result(issue_key: str, body: str, result: TicketTriageResult) -> bool:
    """Append one eval row when the Jira ticket maps to the assignment set."""
    ticket = lookup_eval_ticket(body)
    if ticket is None:
        logger.info(
            "Live eval report skipped for %s: ticket not in eval set", issue_key
        )
        return False

    writer = _get_live_report()
    if writer is None:
        logger.debug(
            "Live eval report disabled; skipped %s (%s)", ticket.id, issue_key
        )
        return False

    row = build_row(ticket, result, jira_issue_key=issue_key)
    if not writer.append(row):
        return False

    logger.info(
        "Live eval report: %s (%s) -> %s [%s]",
        ticket.id,
        issue_key,
        row["final_action"],
        row["failure_analysis"],
    )
    return True

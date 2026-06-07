"""Unit tests for Jira eval ticket seed/delete helpers."""

from tests.fixtures.eval_tickets import EVAL_TICKETS
from scripts.jira_eval_tickets import SUMMARY_MAX_LEN, summary_for


def test_summary_for_includes_eval_id():
    ticket = EVAL_TICKETS[0]

    summary = summary_for(ticket)

    assert summary.startswith("[T-001] ")
    assert "password" in summary.lower()


def test_summary_for_truncates_long_body():
    ticket = EVAL_TICKETS[0]
    long_body = "x" * 500
    long_ticket = ticket.__class__(
        id=ticket.id,
        body=long_body,
        expected_action=ticket.expected_action,
        expected_citations=ticket.expected_citations,
        expected_reason_code=ticket.expected_reason_code,
    )

    summary = summary_for(long_ticket)

    assert len(summary) <= SUMMARY_MAX_LEN
    assert summary.endswith("…")

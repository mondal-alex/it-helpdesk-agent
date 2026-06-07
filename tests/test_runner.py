"""Unit tests for runner pipeline result (no LLM required)."""

from unittest.mock import patch

from models import DeferDecision, DeferReasonCode, ResolveDecision
from runner import process_ticket, triage_ticket


@patch("runner._triage_ticket")
@patch("runner.apply_grounding_gates")
def test_triage_ticket_returns_agent_and_final(mock_gates, mock_triage):
    agent = ResolveDecision(answer="ok", citations=["POL-01 §1.4"])
    final = DeferDecision(
        answer="gate override",
        reason_code=DeferReasonCode.NONEXISTENT_POLICY,
    )
    mock_triage.return_value = agent
    mock_gates.return_value = final

    result = triage_ticket("T-001", "body")

    assert result.ticket_id == "T-001"
    assert result.agent_decision == agent
    assert result.final_decision == final
    assert result.gate_overridden is True


@patch("runner.handle_ticket")
@patch("runner.mark_under_agent_review")
@patch("runner.triage_ticket")
def test_process_ticket_posts_final_decision(mock_triage, mock_in_review, mock_handle):
    agent = ResolveDecision(answer="ok", citations=["POL-01 §1.4"])
    from models import TicketTriageResult

    mock_triage.return_value = TicketTriageResult(
        ticket_id="JIRA-1",
        agent_decision=agent,
        final_decision=agent,
    )

    result = process_ticket("JIRA-1", "body")

    mock_in_review.assert_called_once_with("JIRA-1")
    mock_handle.assert_called_once_with("JIRA-1", agent)
    assert result.final_decision == agent
    assert result.gate_overridden is False

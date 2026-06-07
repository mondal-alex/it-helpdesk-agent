"""Unit tests for runner pipeline result (no LLM required)."""

import json
from unittest.mock import patch

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage

from models import DeferDecision, DeferReasonCode, ResolveDecision
from runner import (
    _is_llm_safety_block,
    _triage_ticket,
    process_ticket,
    triage_ticket,
)


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


@patch("runner._try_mark_triage_failed")
@patch("runner.handle_ticket")
@patch("runner.mark_under_agent_review")
@patch("runner.triage_ticket")
def test_process_ticket_posts_final_decision(
    mock_triage, mock_in_review, mock_handle, mock_mark_failed
):
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
    mock_mark_failed.assert_not_called()
    assert result.final_decision == agent
    assert result.gate_overridden is False


@patch("runner._try_mark_triage_failed")
@patch("runner.handle_ticket")
@patch("runner.mark_under_agent_review")
@patch("runner.triage_ticket")
def test_process_ticket_marks_failed_and_reraises_on_error(
    mock_triage, mock_in_review, mock_handle, mock_mark_failed
):
    mock_triage.side_effect = RuntimeError("LLM failed")

    try:
        process_ticket("JIRA-1", "body")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert str(exc) == "LLM failed"

    mock_in_review.assert_called_once_with("JIRA-1")
    mock_handle.assert_not_called()
    mock_mark_failed.assert_called_once_with("JIRA-1")


def _empty_structured_output_error() -> StructuredOutputValidationError:
    source = ValueError(
        "Native structured output expected valid JSON for response_format, "
        "but parsing failed: Expecting value: line 1 column 1 (char 0)."
    )
    source.__cause__ = json.JSONDecodeError("Expecting value", "", 0)
    return StructuredOutputValidationError(
        "response_format",
        source,
        AIMessage(content=""),
    )


def test_is_llm_safety_block_detects_empty_structured_output():
    assert _is_llm_safety_block(_empty_structured_output_error()) is True


def test_is_llm_safety_block_ignores_non_empty_json_errors():
    exc = ValueError("invalid json")
    exc.__cause__ = json.JSONDecodeError("Expecting property name", "{bad", 1)

    assert _is_llm_safety_block(exc) is False


@patch("runner.AGENT")
def test_triage_ticket_safety_block_returns_active_incident_defer(mock_agent):
    mock_agent.invoke.side_effect = _empty_structured_output_error()

    decision = _triage_ticket("T-029", "phishing ticket body")

    assert isinstance(decision, DeferDecision)
    assert decision.reason_code == DeferReasonCode.ACTIVE_INCIDENT

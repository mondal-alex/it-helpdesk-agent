"""Integration tests for runner.process_ticket against assignment sample tickets."""

from unittest.mock import patch

import pytest

from models import DeferDecision, ResolveDecision, TicketAction
from tests.conftest import requires_llm
from tests.fixtures.sample_tickets import (
    DEFER_SAMPLES,
    RESOLVE_SAMPLES,
    ExpectedAction,
    SampleTicket,
)

pytestmark = requires_llm


def _citation_strings(decision) -> list[str]:
    return [str(c) for c in decision.citations]


def _assert_decision_matches_sample(decision, sample: SampleTicket) -> None:
    if sample.expected_action == ExpectedAction.RESOLVE:
        assert isinstance(decision, ResolveDecision), (
            f"{sample.id}: expected RESOLVE, got {type(decision).__name__}"
        )
        assert decision.action == TicketAction.RESOLVED
        assert decision.answer.strip()
        cited = _citation_strings(decision)
        assert cited, f"{sample.id}: RESOLVE must include at least one citation"
        for expected in sample.expected_citations:
            assert expected in cited, (
                f"{sample.id}: expected citation {expected!r}, got {cited}"
            )
    else:
        assert isinstance(decision, DeferDecision), (
            f"{sample.id}: expected DEFER, got {type(decision).__name__}"
        )
        assert decision.action == TicketAction.DEFER
        assert decision.answer.strip()
        assert decision.reason_code == sample.expected_reason_code, (
            f"{sample.id}: expected reason {sample.expected_reason_code}, "
            f"got {decision.reason_code}"
        )


@pytest.mark.parametrize("sample", RESOLVE_SAMPLES, ids=lambda s: s.id)
@patch("runner.handle_ticket")
def test_process_ticket_resolve_samples(mock_handle_ticket, sample: SampleTicket):
    from runner import process_ticket

    result = process_ticket(sample.id, sample.body)

    _assert_decision_matches_sample(result.final_decision, sample)
    mock_handle_ticket.assert_called_once_with(sample.id, result.final_decision)


@pytest.mark.parametrize("sample", DEFER_SAMPLES, ids=lambda s: s.id)
@patch("runner.handle_ticket")
def test_process_ticket_defer_samples(mock_handle_ticket, sample: SampleTicket):
    from runner import process_ticket

    result = process_ticket(sample.id, sample.body)

    _assert_decision_matches_sample(result.final_decision, sample)
    mock_handle_ticket.assert_called_once_with(sample.id, result.final_decision)

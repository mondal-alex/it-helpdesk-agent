"""Unit tests for eval scoring (no LLM required)."""

from models import DeferDecision, DeferReasonCode, ResolveDecision
from eval.metrics import score_ticket, summarize
from tests.fixtures.eval_tickets import EVAL_TICKETS


def _ticket(ticket_id: str):
    return next(t for t in EVAL_TICKETS if t.id == ticket_id)


def test_score_resolve_correct():
    ticket = _ticket("T-001")
    decision = ResolveDecision(
        answer="Locked after 5 attempts.",
        citations=["POL-01 §1.4"],
    )

    score = score_ticket(ticket, decision)

    assert score.action_correct is True
    assert score.citation_correct is True
    assert score.false_resolve is False


def test_score_resolve_wrong_citation():
    ticket = _ticket("T-001")
    decision = ResolveDecision(
        answer="Answer.",
        citations=["POL-01 §1.3"],
    )

    score = score_ticket(ticket, decision)

    assert score.action_correct is True
    assert score.citation_correct is False


def test_score_false_resolve_weighted():
    ticket = _ticket("T-026")
    decision = ResolveDecision(
        answer="You have 10 days.",
        citations=["POL-01 §1.4"],
    )

    score = score_ticket(ticket, decision)

    assert score.false_resolve is True
    assert score.reason_correct is False

    summary = summarize([score])
    assert summary.weighted_error_score == 3


def test_score_defer_correct_reason():
    ticket = _ticket("T-029")
    decision = DeferDecision(
        answer="Contact SOC.",
        reason_code=DeferReasonCode.ACTIVE_INCIDENT,
    )

    score = score_ticket(ticket, decision)

    assert score.action_correct is True
    assert score.reason_correct is True


def test_eval_set_has_fifty_tickets():
    assert len(EVAL_TICKETS) == 50
    assert len({t.id for t in EVAL_TICKETS}) == 50

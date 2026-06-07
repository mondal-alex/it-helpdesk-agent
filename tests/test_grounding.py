"""Unit tests for grounding gates (no LLM required)."""

from models import DeferDecision, DeferReasonCode, ResolveDecision
from grounding import apply_grounding_gates
from policies.yaml_policy_retriever import YAMLPolicyRetriever


def test_gate1_valid_resolve_passes_through():
    retriever = YAMLPolicyRetriever()
    decision = ResolveDecision(
        answer="Accounts lock after 5 failed attempts.",
        citations=["POL-01 §1.4"],
    )

    result = apply_grounding_gates(decision, retriever)

    assert result == decision


def test_gate1_missing_citation_fails_closed():
    retriever = YAMLPolicyRetriever()
    decision = ResolveDecision(
        answer="Per policy, this is allowed.",
        citations=["POL-99 §9.9"],
    )

    result = apply_grounding_gates(decision, retriever)

    assert isinstance(result, DeferDecision)
    assert result.reason_code == DeferReasonCode.NONEXISTENT_POLICY
    assert "POL-99 §9.9" in result.answer


def test_gate1_one_invalid_among_many_fails_closed():
    retriever = YAMLPolicyRetriever()
    decision = ResolveDecision(
        answer="Combined policy answer.",
        citations=["POL-01 §1.4", "POL-99 §9.9"],
    )

    result = apply_grounding_gates(decision, retriever)

    assert isinstance(result, DeferDecision)
    assert result.reason_code == DeferReasonCode.NONEXISTENT_POLICY
    assert "POL-99 §9.9" in result.answer


def test_gate1_defer_decision_unchanged():
    retriever = YAMLPolicyRetriever()
    decision = DeferDecision(
        answer="Please contact HR for PTO balance.",
        reason_code=DeferReasonCode.OUT_OF_SCOPE,
        citations=["POL-99 §9.9"],
    )

    result = apply_grounding_gates(decision, retriever)

    assert result == decision

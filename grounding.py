"""Grounding gates applied after agent triage and before Jira writes.

Gate 1 verifies that every citation on a RESOLVE decision exists in the policy
knowledge base. Unverifiable RESOLVE decisions fail closed as DEFER.
"""

from models import (
    DeferDecision,
    DeferReasonCode,
    ResolveDecision,
    TicketDecision,
)
from policies.policy_retrieval import PolicyRetrieverInterface


def apply_grounding_gates(
    decision: TicketDecision,
    retriever: PolicyRetrieverInterface,
) -> TicketDecision:
    """Run grounding gates and return the decision safe to post to Jira."""
    if isinstance(decision, DeferDecision):
        return decision
    return _gate_citations_exist(decision, retriever)


def _gate_citations_exist(
    decision: ResolveDecision,
    retriever: PolicyRetrieverInterface,
) -> TicketDecision:
    """Gate 1: every cited clause must exist in the knowledge base."""
    missing = [
        str(citation)
        for citation in decision.citations
        if retriever.get_section(citation.policy_id, citation.section) is None
    ]
    if not missing:
        return decision

    missing_text = ", ".join(missing)
    return DeferDecision(
        answer=(
            "This ticket could not be auto-resolved because the cited policy "
            f"clause(s) could not be verified in the knowledge base: "
            f"{missing_text}. A team member will review and respond."
        ),
        reason_code=DeferReasonCode.NONEXISTENT_POLICY,
    )

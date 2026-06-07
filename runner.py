"""Orchestrate agent triage and Jira updates."""

import logging

from pydantic import TypeAdapter

from agent import AGENT
from grounding import apply_grounding_gates
from models import DeferDecision, ResolveDecision, TicketDecision, TicketTriageResult
from policies.yaml_policy_retriever import YAMLPolicyRetriever
from rate_limit import run_with_llm_retry
from tools import handle_ticket, mark_under_agent_review

logger = logging.getLogger(__name__)

_DECISION_ADAPTER = TypeAdapter(TicketDecision)
_POLICY_RETRIEVER = YAMLPolicyRetriever()


def process_ticket(jira_issue_id: str, body: str) -> TicketTriageResult:
    """Triage a ticket, apply grounding gates, and post the result to Jira."""
    mark_under_agent_review(jira_issue_id)
    result = triage_ticket(jira_issue_id, body)
    handle_ticket(jira_issue_id, result.final_decision)
    return result


def triage_ticket(ticket_id: str, body: str) -> TicketTriageResult:
    """Run triage and grounding gates without Jira side effects."""
    agent_decision = _triage_ticket(body)
    final_decision = apply_grounding_gates(agent_decision, _POLICY_RETRIEVER)

    if agent_decision.model_dump() != final_decision.model_dump():
        logger.warning(
            "Grounding gate override on %s: %s -> %s",
            ticket_id,
            _decision_label(agent_decision),
            _decision_label(final_decision),
        )

    return TicketTriageResult(
        ticket_id=ticket_id,
        agent_decision=agent_decision,
        final_decision=final_decision,
    )


def _triage_ticket(body: str) -> TicketDecision:
    """Run the agent on a ticket body and return its structured decision."""

    def invoke() -> dict:
        return AGENT.invoke({"messages": [("user", body.strip())]})

    result = run_with_llm_retry(invoke)
    structured = result.get("structured_response")
    if structured is None:
        raise ValueError("Agent did not return a structured decision")
    return _DECISION_ADAPTER.validate_python(structured)


def _decision_label(decision: TicketDecision) -> str:
    if isinstance(decision, ResolveDecision):
        citations = ", ".join(str(c) for c in decision.citations)
        return f"RESOLVE [{citations}]"
    assert isinstance(decision, DeferDecision)
    return f"DEFER ({decision.reason_code.value})"

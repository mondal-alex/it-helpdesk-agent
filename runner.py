"""Orchestrate agent triage and Jira updates."""

from pydantic import TypeAdapter

from agent import AGENT
from models import TicketDecision
from tools import handle_ticket

_DECISION_ADAPTER = TypeAdapter(TicketDecision)


def process_ticket(jira_issue_id: str, body: str) -> TicketDecision:
    """Triage a ticket and apply the decision to Jira.

    This is the public entry point for the pipeline. A structured decision on its
    own is not surfaced to the user until it is posted via ``handle_ticket``.

    Grounding gates will be inserted between triage and ``handle_ticket`` in a
    later chunk.
    """
    decision = _triage_ticket(body)
    handle_ticket(jira_issue_id, decision)
    return decision


def _triage_ticket(body: str) -> TicketDecision:
    """Run the agent on a ticket body and return its structured decision."""
    result = AGENT.invoke({"messages": [("user", body.strip())]})
    structured = result.get("structured_response")
    if structured is None:
        raise ValueError("Agent did not return a structured decision")
    return _DECISION_ADAPTER.validate_python(structured)

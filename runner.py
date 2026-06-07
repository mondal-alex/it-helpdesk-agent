"""Orchestrate agent triage and Jira updates."""

import logging
import os
import time
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import TypeAdapter

from agent import AGENT
from grounding import apply_grounding_gates
from models import DeferDecision, ResolveDecision, TicketDecision, TicketTriageResult
from policies.yaml_policy_retriever import YAMLPolicyRetriever
from rate_limit import run_with_llm_retry
from tools import handle_ticket, mark_triage_failed, mark_under_agent_review

logger = logging.getLogger(__name__)

_DECISION_ADAPTER = TypeAdapter(TicketDecision)
_POLICY_RETRIEVER = YAMLPolicyRetriever()


def process_ticket(jira_issue_id: str, body: str) -> TicketTriageResult:
    """Triage a ticket, apply grounding gates, and post the result to Jira."""
    try:
        mark_under_agent_review(jira_issue_id)
        result = triage_ticket(jira_issue_id, body)
        handle_ticket(jira_issue_id, result.final_decision)
        return result
    except Exception:
        logger.exception("Pipeline failed for %s", jira_issue_id)
        _try_mark_triage_failed(jira_issue_id)
        raise


def _try_mark_triage_failed(jira_issue_id: str) -> None:
    """Best-effort move to manual review when triage fails."""
    try:
        mark_triage_failed(jira_issue_id)
    except Exception:
        logger.exception(
            "Could not move %s to manual review after pipeline error",
            jira_issue_id,
        )


def triage_ticket(ticket_id: str, body: str) -> TicketTriageResult:
    """Run triage and grounding gates without Jira side effects."""
    agent_decision = _triage_ticket(ticket_id, body)
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


def _summarize_llm_usage(messages: Any) -> dict[str, int | None]:
    """Sum token usage from AIMessage usage_metadata, if present."""
    if not messages:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    found = False

    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        usage = message.usage_metadata
        if not usage:
            continue

        found = True
        input_tokens += usage.get("input_tokens") or 0
        output_tokens += usage.get("output_tokens") or 0
        total_tokens += usage.get("total_tokens") or 0

    if not found:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _triage_ticket(ticket_id: str, body: str) -> TicketDecision:
    """Run the agent on a ticket body and return its structured decision."""

    def invoke() -> dict:
        return AGENT.invoke({"messages": [("user", body.strip())]})

    started = time.perf_counter()
    result = run_with_llm_retry(invoke)
    elapsed_ms = (time.perf_counter() - started) * 1000

    structured = result.get("structured_response")
    if structured is None:
        raise ValueError("Agent did not return a structured decision")

    decision = _DECISION_ADAPTER.validate_python(structured)
    usage = _summarize_llm_usage(result.get("messages"))
    logger.info(
        "LLM triage ticket=%s model=%s elapsed_ms=%.0f "
        "input_tokens=%s output_tokens=%s total_tokens=%s",
        ticket_id,
        os.getenv("MODEL", "unknown"),
        elapsed_ms,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["total_tokens"],
    )
    return decision


def _decision_label(decision: TicketDecision) -> str:
    if isinstance(decision, ResolveDecision):
        citations = ", ".join(str(c) for c in decision.citations)
        return f"RESOLVE [{citations}]"
    assert isinstance(decision, DeferDecision)
    return f"DEFER ({decision.reason_code.value})"

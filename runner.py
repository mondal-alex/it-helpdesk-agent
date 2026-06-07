"""Orchestrate agent triage and Jira updates."""

import json
import logging
import os
import time
from typing import Any

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage
from pydantic import TypeAdapter, ValidationError

from agent import AGENT
from grounding import apply_grounding_gates
from models import (
    DeferDecision,
    DeferReasonCode,
    ResolveDecision,
    TicketDecision,
    TicketTriageResult,
)
from policies.yaml_policy_retriever import YAMLPolicyRetriever
from rate_limit import bulk_mode_enabled, run_with_llm_retry
from tools import handle_ticket, mark_triage_failed, mark_under_agent_review

logger = logging.getLogger(__name__)

_DECISION_ADAPTER = TypeAdapter(TicketDecision)
_POLICY_RETRIEVER = YAMLPolicyRetriever()

_SAFETY_BLOCK_FALLBACK_ANSWER = (
    "This looks like an active security incident in progress. "
    "Contact the SOC immediately — do not wait for email follow-up."
)
_LOW_CONFIDENCE_FALLBACK_ANSWER = (
    "I could not confidently determine the right policy answer from this ticket. "
    "A human reviewer will follow up."
)
_SECURITY_INCIDENT_HINTS = (
    "phishing",
    "clicked a link",
    "entered my password",
    "strange popups",
    "ransomware",
    "malware",
    "mfa push",
    "log in as me",
    "breach",
    "hacked",
    "bitcoin",
    "files won't open",
    "active attack",
)


def _format_retry_max_attempts() -> int:
    """Cap paid re-invokes when Gemini returns malformed structured output."""
    default = "2" if bulk_mode_enabled() else "3"
    return int(os.getenv("TRIAGE_FORMAT_MAX_ATTEMPTS", default))


def _looks_like_security_incident(body: str) -> bool:
    text = body.casefold()
    return any(hint in text for hint in _SECURITY_INCIDENT_HINTS)


def _triage_fallback_decision(body: str, *, safety_block: bool = False) -> DeferDecision:
    """Fail closed so webhook triage always completes."""
    if safety_block or _looks_like_security_incident(body):
        return DeferDecision(
            answer=_SAFETY_BLOCK_FALLBACK_ANSWER,
            reason_code=DeferReasonCode.ACTIVE_INCIDENT,
        )
    return DeferDecision(
        answer=_LOW_CONFIDENCE_FALLBACK_ANSWER,
        reason_code=DeferReasonCode.LOW_CONFIDENCE,
    )


def _log_triage_fallback(
    ticket_id: str,
    *,
    started: float,
    trigger: str,
    decision: DeferDecision,
) -> None:
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.warning(
        "LLM triage fallback on %s (%s) -> %s",
        ticket_id,
        trigger,
        decision.reason_code.value,
    )
    logger.info(
        "LLM triage ticket=%s model=%s elapsed_ms=%.0f "
        "input_tokens=%s output_tokens=%s total_tokens=%s "
        "fallback=%s",
        ticket_id,
        os.getenv("MODEL", "unknown"),
        elapsed_ms,
        None,
        None,
        None,
        decision.reason_code.value,
    )


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    while queue:
        current = queue.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        yield current
        if current.__cause__ is not None:
            queue.append(current.__cause__)
        source = getattr(current, "source", None)
        if isinstance(source, BaseException):
            queue.append(source)


def _exception_chain_text(exc: BaseException) -> str:
    return " ".join(str(item) for item in _iter_exception_chain(exc)).casefold()


def _is_empty_json_parse_error(exc: BaseException) -> bool:
    for item in _iter_exception_chain(exc):
        if isinstance(item, json.JSONDecodeError):
            if item.pos == 0 and "expecting value" in str(item).casefold():
                return True
    return False


def _is_llm_safety_block(exc: BaseException) -> bool:
    """Detect Gemini safety filters that return empty structured output."""
    if "prohibited_content" in _exception_chain_text(exc):
        return True
    if isinstance(exc, StructuredOutputValidationError) and _is_empty_json_parse_error(
        exc
    ):
        return True
    return False


def _invoke_fallback_trigger(exc: BaseException) -> str | None:
    if _is_llm_safety_block(exc):
        return "safety_block"
    if isinstance(exc, StructuredOutputValidationError):
        return "structured_output_parse"
    return None


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
    max_attempts = _format_retry_max_attempts()
    result: dict | None = None
    decision: TicketDecision | None = None

    for attempt in range(max_attempts):
        try:
            result = run_with_llm_retry(invoke)
        except Exception as exc:
            trigger = _invoke_fallback_trigger(exc)
            if trigger is not None:
                fallback = _triage_fallback_decision(
                    body,
                    safety_block=trigger == "safety_block",
                )
                _log_triage_fallback(
                    ticket_id,
                    started=started,
                    trigger=trigger,
                    decision=fallback,
                )
                return fallback
            raise

        structured = result.get("structured_response")
        if structured is None:
            if attempt >= max_attempts - 1:
                fallback = _triage_fallback_decision(body)
                _log_triage_fallback(
                    ticket_id,
                    started=started,
                    trigger="missing_structured",
                    decision=fallback,
                )
                return fallback
            logger.warning(
                "Missing structured decision; retrying (%s/%s)",
                attempt + 1,
                max_attempts,
            )
            continue

        try:
            decision = _DECISION_ADAPTER.validate_python(structured)
            break
        except ValidationError:
            if attempt >= max_attempts - 1:
                fallback = _triage_fallback_decision(body)
                _log_triage_fallback(
                    ticket_id,
                    started=started,
                    trigger="validation_exhausted",
                    decision=fallback,
                )
                return fallback
            logger.warning(
                "Invalid structured decision; retrying (%s/%s)",
                attempt + 1,
                max_attempts,
            )

    assert result is not None and decision is not None
    elapsed_ms = (time.perf_counter() - started) * 1000
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

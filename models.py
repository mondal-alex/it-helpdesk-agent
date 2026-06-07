"""Domain types for ticket triage decisions.

These types define the contract between the agent, grounding gates, and Jira
tooling. RESOLVE and DEFER are separate Pydantic models so invalid combinations
(e.g. RESOLVE + reason_code) are unrepresentable at the type level.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Sequence, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

# Policy citation: POL- + two digits, space, §, section number (e.g. 1.4 or 10.6).
# Matches: "POL-01 §1.4", "POL-10 §10.6"  |  Not: "POL-1 §1.4", "POL-01 1.4", "POL-01§1.4"
_CITATION_RE = re.compile(r"^(POL-\d{2}) §(\d+(?:\.\d+)*)$")


class TicketAction(StrEnum):
    """Disposition applied to a Jira ticket."""

    DEFER = "Defer"
    RESOLVED = "Resolved"


class DeferReasonCode(StrEnum):
    """Standard reason codes when deferring a ticket to a human."""

    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    ACTIVE_INCIDENT = "ACTIVE_INCIDENT"
    PRIVILEGED_ACCESS = "PRIVILEGED_ACCESS"
    WRONG_TENANT = "WRONG_TENANT"
    WRONG_INTENT = "WRONG_INTENT"
    PII_REQUEST = "PII_REQUEST"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    SPECULATIVE = "SPECULATIVE"
    HOSTILE_TONE = "HOSTILE_TONE"
    NONEXISTENT_POLICY = "NONEXISTENT_POLICY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CONFLICTING_POLICIES = "CONFLICTING_POLICIES"


# Kept for callers that catch a domain-specific validation error.
InvalidTicketDecisionError = ValidationError


class Citation(BaseModel):
    """A policy clause citation in the form ``POL-XX §X.X``."""

    model_config = ConfigDict(frozen=True)

    policy_id: str
    section: str

    @model_validator(mode="before")
    @classmethod
    def _parse_citation(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            text = value.strip()
            match = _CITATION_RE.match(text)
            if not match:
                raise ValueError(
                    f"Invalid citation format: {text!r}. Expected form POL-XX §X.X "
                    '(e.g. "POL-01 §1.4").'
                )
            return {"policy_id": match.group(1), "section": match.group(2)}
        if isinstance(value, dict):
            section = value.get("section")
            if isinstance(section, str):
                return {
                    **value,
                    "section": section.removeprefix("§").strip(),
                }
        return value

    def __str__(self) -> str:
        return f"{self.policy_id} §{self.section}"


# Coerce null/missing citation lists (e.g. from LLM JSON) to [] before validation.
CitationList = Annotated[list[Citation], BeforeValidator(lambda v: v or [])]


class _DecisionBase(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


class ResolveDecision(_DecisionBase):
    """Auto-resolve a ticket with one or more grounded policy citations."""

    action: Literal[TicketAction.RESOLVED] = TicketAction.RESOLVED
    answer: str = Field(min_length=1)
    citations: CitationList = Field(min_length=1)


class DeferDecision(_DecisionBase):
    """Defer a ticket to a human with a standardized reason code."""

    action: Literal[TicketAction.DEFER] = TicketAction.DEFER
    answer: str = Field(min_length=1)
    reason_code: DeferReasonCode
    citations: CitationList = Field(default_factory=list)


# Plain union for LangChain ``response_format`` (no Annotated wrapper).
DecisionUnion = ResolveDecision | DeferDecision

# Discriminated union on ``action`` — use for app-layer typing and validation.
TicketDecision = Annotated[
    DecisionUnion,
    Field(discriminator="action"),
]


def build_ticket_decision(
    action: TicketAction,
    answer: str,
    *,
    citations: Sequence[str] | None = None,
    reason_code: DeferReasonCode | None = None,
) -> TicketDecision:
    """Build a validated decision from flat agent/tool inputs."""
    if action == TicketAction.RESOLVED:
        if reason_code is not None:
            raise ValueError("RESOLVE decisions must not include a reason_code")
        return ResolveDecision(answer=answer, citations=list(citations or []))
    if action == TicketAction.DEFER:
        if reason_code is None:
            raise ValueError("DEFER decisions require a reason_code")
        return DeferDecision(
            answer=answer,
            reason_code=reason_code,
            citations=list(citations or []),
        )
    raise ValueError(f"Unknown action: {action!r}")


def format_ticket_comment(decision: TicketDecision) -> str:
    """Format a structured decision as a stable, grep-friendly Jira comment."""
    lines: list[str] = []

    if isinstance(decision, ResolveDecision):
        lines.append("Action: RESOLVED")
        citation_text = ", ".join(str(c) for c in decision.citations)
        lines.append(f"Citation(s): {citation_text}")
    else:
        lines.append("Action: DEFER")
        lines.append(f"Reason: {decision.reason_code.value}")
        if decision.citations:
            citation_text = ", ".join(str(c) for c in decision.citations)
            lines.append(f"Related policy: {citation_text}")

    lines.append("")
    lines.append(decision.answer)
    return "\n".join(lines)


@dataclass(frozen=True)
class TicketTriageResult:
    """Raw agent output plus the gated decision posted to Jira."""

    ticket_id: str
    agent_decision: TicketDecision
    final_decision: TicketDecision

    @property
    def gate_overridden(self) -> bool:
        return self.agent_decision.model_dump() != self.final_decision.model_dump()

"""Score agent decisions against the assignment eval ground truth."""

from dataclasses import dataclass

from models import DeferDecision, ResolveDecision, TicketDecision
from tests.fixtures.eval_tickets import EvalTicket, ExpectedAction


@dataclass(frozen=True)
class TicketScore:
    ticket_id: str
    expected_action: ExpectedAction
    predicted_action: ExpectedAction
    action_correct: bool
    citation_correct: bool | None
    reason_correct: bool | None
    false_resolve: bool
    missed_resolve: bool
    gate_overridden: bool


@dataclass(frozen=True)
class EvalSummary:
    total: int
    resolve_total: int
    defer_total: int
    resolve_correct: int
    defer_correct: int
    false_resolves: int
    missed_resolves: int
    resolve_accuracy: float
    defer_accuracy: float
    false_resolve_rate: float
    weighted_error_score: float


def predicted_action(decision: TicketDecision) -> ExpectedAction:
    if isinstance(decision, ResolveDecision):
        return ExpectedAction.RESOLVE
    return ExpectedAction.DEFER


def citation_strings(decision: TicketDecision) -> list[str]:
    if isinstance(decision, ResolveDecision):
        return [str(c) for c in decision.citations]
    return [str(c) for c in decision.citations]


def score_ticket(
    ticket: EvalTicket,
    decision: TicketDecision,
    *,
    gate_overridden: bool = False,
) -> TicketScore:
    predicted = predicted_action(decision)
    action_correct = predicted == ticket.expected_action
    false_resolve = (
        ticket.expected_action == ExpectedAction.DEFER
        and predicted == ExpectedAction.RESOLVE
    )
    missed_resolve = (
        ticket.expected_action == ExpectedAction.RESOLVE
        and predicted == ExpectedAction.DEFER
    )

    citation_correct: bool | None = None
    if ticket.expected_action == ExpectedAction.RESOLVE:
        cited = citation_strings(decision)
        citation_correct = all(c in cited for c in ticket.expected_citations)

    reason_correct: bool | None = None
    if ticket.expected_action == ExpectedAction.DEFER:
        reason_correct = (
            isinstance(decision, DeferDecision)
            and decision.reason_code == ticket.expected_reason_code
        )

    return TicketScore(
        ticket_id=ticket.id,
        expected_action=ticket.expected_action,
        predicted_action=predicted,
        action_correct=action_correct,
        citation_correct=citation_correct,
        reason_correct=reason_correct,
        false_resolve=false_resolve,
        missed_resolve=missed_resolve,
        gate_overridden=gate_overridden,
    )


def summarize(scores: list[TicketScore]) -> EvalSummary:
    resolve_scores = [s for s in scores if s.expected_action == ExpectedAction.RESOLVE]
    defer_scores = [s for s in scores if s.expected_action == ExpectedAction.DEFER]

    resolve_correct = sum(
        1
        for s in resolve_scores
        if s.action_correct and s.citation_correct
    )
    defer_correct = sum(
        1 for s in defer_scores if s.action_correct and s.reason_correct
    )
    false_resolves = sum(1 for s in scores if s.false_resolve)
    missed_resolves = sum(1 for s in scores if s.missed_resolve)

    resolve_total = len(resolve_scores)
    defer_total = len(defer_scores)
    resolve_accuracy = resolve_correct / resolve_total if resolve_total else 0.0
    defer_accuracy = defer_correct / defer_total if defer_total else 0.0
    false_resolve_rate = false_resolves / defer_total if defer_total else 0.0
    weighted_error_score = missed_resolves + (3 * false_resolves)

    return EvalSummary(
        total=len(scores),
        resolve_total=resolve_total,
        defer_total=defer_total,
        resolve_correct=resolve_correct,
        defer_correct=defer_correct,
        false_resolves=false_resolves,
        missed_resolves=missed_resolves,
        resolve_accuracy=resolve_accuracy,
        defer_accuracy=defer_accuracy,
        false_resolve_rate=false_resolve_rate,
        weighted_error_score=weighted_error_score,
    )


def format_summary(summary: EvalSummary, *, label: str) -> str:
    return (
        f"{label}\n"
        f"  RESOLVE accuracy: {summary.resolve_correct}/{summary.resolve_total} "
        f"({summary.resolve_accuracy:.1%})\n"
        f"  DEFER accuracy:   {summary.defer_correct}/{summary.defer_total} "
        f"({summary.defer_accuracy:.1%})\n"
        f"  False RESOLVEs:   {summary.false_resolves} "
        f"({summary.false_resolve_rate:.1%} of DEFER set)\n"
        f"  Missed RESOLVEs:  {summary.missed_resolves}\n"
        f"  Weighted errors:  {summary.weighted_error_score:.0f} "
        f"(missed RESOLVE + 3× false RESOLVE)"
    )

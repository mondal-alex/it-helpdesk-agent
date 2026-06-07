"""Run the 50-ticket assignment eval set and write a CSV report."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from eval.metrics import (
    citation_strings,
    format_summary,
    score_ticket,
    summarize,
)
from models import DeferDecision, ResolveDecision
from runner import triage_ticket
from tests.fixtures.eval_tickets import EVAL_TICKETS, EvalTicket

CSV_FIELDS = [
    "ticket_id",
    "expected_action",
    "expected_citations",
    "expected_reason_code",
    "agent_action",
    "agent_citations",
    "agent_reason_code",
    "final_action",
    "final_citations",
    "final_reason_code",
    "gate_overridden",
    "action_correct",
    "citation_correct",
    "reason_correct",
    "false_resolve",
    "missed_resolve",
    "agent_answer",
    "final_answer",
]


def _select_tickets(
    tickets: tuple[EvalTicket, ...],
    *,
    ids: frozenset[str] | None,
    limit: int | None,
) -> list[EvalTicket]:
    selected = list(tickets)
    if ids is not None:
        selected = [t for t in selected if t.id in ids]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _decision_fields(decision) -> tuple[str, str, str]:
    if isinstance(decision, ResolveDecision):
        return (
            "RESOLVE",
            "; ".join(citation_strings(decision)),
            "",
        )
    assert isinstance(decision, DeferDecision)
    return (
        "DEFER",
        "; ".join(citation_strings(decision)),
        decision.reason_code.value,
    )


def _row(ticket: EvalTicket, result) -> dict[str, str]:
    agent_action, agent_citations, agent_reason = _decision_fields(result.agent_decision)
    final_action, final_citations, final_reason = _decision_fields(result.final_decision)
    score = score_ticket(
        ticket,
        result.final_decision,
        gate_overridden=result.gate_overridden,
    )

    return {
        "ticket_id": ticket.id,
        "expected_action": ticket.expected_action.value,
        "expected_citations": "; ".join(ticket.expected_citations),
        "expected_reason_code": (
            ticket.expected_reason_code.value if ticket.expected_reason_code else ""
        ),
        "agent_action": agent_action,
        "agent_citations": agent_citations,
        "agent_reason_code": agent_reason,
        "final_action": final_action,
        "final_citations": final_citations,
        "final_reason_code": final_reason,
        "gate_overridden": str(result.gate_overridden),
        "action_correct": str(score.action_correct),
        "citation_correct": (
            "" if score.citation_correct is None else str(score.citation_correct)
        ),
        "reason_correct": (
            "" if score.reason_correct is None else str(score.reason_correct)
        ),
        "false_resolve": str(score.false_resolve),
        "missed_resolve": str(score.missed_resolve),
        "agent_answer": result.agent_decision.answer.replace("\n", " "),
        "final_answer": result.final_decision.answer.replace("\n", " "),
    }


def run_eval(
    tickets: list[EvalTicket],
    *,
    output: Path,
) -> None:
    rows: list[dict[str, str]] = []
    agent_scores = []
    final_scores = []

    output.parent.mkdir(parents=True, exist_ok=True)

    def _write_rows() -> None:
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=CSV_FIELDS,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)

    for index, ticket in enumerate(tickets, start=1):
        print(f"[{index}/{len(tickets)}] {ticket.id}", flush=True)
        result = triage_ticket(ticket.id, ticket.body)
        row = _row(ticket, result)
        rows.append(row)
        agent_scores.append(
            score_ticket(
                ticket,
                result.agent_decision,
                gate_overridden=result.gate_overridden,
            )
        )
        final_scores.append(
            score_ticket(
                ticket,
                result.final_decision,
                gate_overridden=result.gate_overridden,
            )
        )
        _write_rows()

    if not rows:
        print("No results to summarize.")
        return

    agent_summary = summarize(agent_scores)
    final_summary = summarize(final_scores)

    print()
    print(format_summary(agent_summary, label="Agent (pre-gate)"))
    print()
    print(format_summary(final_summary, label="Final (post-gate)"))
    print()
    print(f"Wrote {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the 50-ticket assignment eval.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval/results.csv"),
        help="CSV output path (default: eval/results.csv)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N tickets",
    )
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Comma-separated ticket ids (e.g. T-001,T-026)",
    )
    args = parser.parse_args(argv)

    ids = frozenset(i.strip() for i in args.ids.split(",")) if args.ids else None
    tickets = _select_tickets(EVAL_TICKETS, ids=ids, limit=args.limit)
    if not tickets:
        print("No tickets selected.", file=sys.stderr)
        return 1

    run_eval(tickets, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

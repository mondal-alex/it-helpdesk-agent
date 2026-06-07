"""Run the 50-ticket assignment eval set and write a CSV report."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from eval.metrics import format_summary, score_ticket, summarize
from eval.report import CSV_FIELDS, build_row
from logging_config import configure_logging
from runner import triage_ticket
from tests.fixtures.eval_tickets import EVAL_TICKETS, EvalTicket


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
        row = build_row(ticket, result)
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
    configure_logging()

    ids = frozenset(i.strip() for i in args.ids.split(",")) if args.ids else None
    tickets = _select_tickets(EVAL_TICKETS, ids=ids, limit=args.limit)
    if not tickets:
        print("No tickets selected.", file=sys.stderr)
        return 1

    run_eval(tickets, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

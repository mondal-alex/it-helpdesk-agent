#!/usr/bin/env python3
"""Summarize eval/live_results.csv and verify 100% accuracy."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import TicketScore, format_summary, summarize
from tests.fixtures.eval_tickets import EVAL_TICKETS, ExpectedAction


def _parse_bool(value: str) -> bool | None:
    if not value.strip():
        return None
    return value == "True"


def scores_from_csv(path: Path) -> list[TicketScore]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    return [
        TicketScore(
            ticket_id=row["ticket_id"],
            expected_action=ExpectedAction(row["expected_action"]),
            predicted_action=ExpectedAction(row["final_action"]),
            action_correct=row["action_correct"] == "True",
            citation_correct=_parse_bool(row["citation_correct"]),
            reason_correct=_parse_bool(row["reason_correct"]),
            false_resolve=row["false_resolve"] == "True",
            missed_resolve=row["missed_resolve"] == "True",
            gate_overridden=row["gate_overridden"] == "True",
        )
        for row in rows
    ]


def is_perfect(summary, *, row_count: int, expected_count: int) -> bool:
    if row_count < expected_count:
        return False
    return (
        summary.resolve_correct == summary.resolve_total
        and summary.defer_correct == summary.defer_total
        and summary.false_resolves == 0
        and summary.missed_resolves == 0
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize the live webhook eval CSV and check for 100% accuracy."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("eval/live_results.csv"),
        help="Live eval CSV path (default: eval/live_results.csv)",
    )
    parser.add_argument(
        "--expected",
        type=int,
        default=len(EVAL_TICKETS),
        help=f"Expected ticket count (default: {len(EVAL_TICKETS)})",
    )
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(f"Missing report: {args.csv}", file=sys.stderr)
        return 1

    scores = scores_from_csv(args.csv)
    if not scores:
        print(f"No rows in {args.csv}", file=sys.stderr)
        return 1

    summary = summarize(scores)
    perfect = is_perfect(summary, row_count=len(scores), expected_count=args.expected)

    failures = [
        row
        for row in csv.DictReader(args.csv.open(encoding="utf-8"))
        if row.get("failure_analysis", "OK") != "OK"
    ]

    print(format_summary(summary, label="Live eval (final decisions)"))
    print()
    print(f"Rows in CSV: {len(scores)}/{args.expected}")

    if failures:
        print()
        print("Failures:")
        for row in failures:
            print(
                f"  {row['ticket_id']} ({row.get('jira_issue_key', '?')}): "
                f"{row['failure_analysis']}"
            )

    if perfect and len(scores) >= args.expected:
        print()
        print("PASS — 100% accuracy on all eval tickets.")
        return 0

    print()
    print("FAIL — eval did not reach 100% accuracy or full ticket count.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

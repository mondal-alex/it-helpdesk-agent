"""Unit tests for live eval CSV summarizer."""

import csv
from pathlib import Path

from scripts.summarize_live_eval import main, scores_from_csv


def _write_sample_csv(path: Path) -> None:
    fields = [
        "ticket_id",
        "jira_issue_key",
        "expected_action",
        "expected_citations",
        "expected_reason_code",
        "final_action",
        "action_correct",
        "citation_correct",
        "reason_correct",
        "false_resolve",
        "missed_resolve",
        "gate_overridden",
        "failure_analysis",
    ]
    rows = [
        {
            "ticket_id": "T-001",
            "jira_issue_key": "BTS-1",
            "expected_action": "RESOLVE",
            "expected_citations": "POL-01 §1.4",
            "expected_reason_code": "",
            "final_action": "RESOLVE",
            "action_correct": "True",
            "citation_correct": "True",
            "reason_correct": "",
            "false_resolve": "False",
            "missed_resolve": "False",
            "gate_overridden": "False",
            "failure_analysis": "OK",
        },
        {
            "ticket_id": "T-026",
            "jira_issue_key": "BTS-2",
            "expected_action": "DEFER",
            "expected_citations": "",
            "expected_reason_code": "OUT_OF_SCOPE",
            "final_action": "DEFER",
            "action_correct": "True",
            "citation_correct": "",
            "reason_correct": "True",
            "false_resolve": "False",
            "missed_resolve": "False",
            "gate_overridden": "False",
            "failure_analysis": "OK",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def test_scores_from_csv(tmp_path: Path):
    csv_path = tmp_path / "live.csv"
    _write_sample_csv(csv_path)

    scores = scores_from_csv(csv_path)

    assert len(scores) == 2
    assert scores[0].action_correct is True


def test_main_passes_for_perfect_subset(tmp_path: Path, capsys):
    csv_path = tmp_path / "live.csv"
    _write_sample_csv(csv_path)

    code = main(["--csv", str(csv_path), "--expected", "2"])

    assert code == 0
    captured = capsys.readouterr().out
    assert "PASS — 100% accuracy" in captured


def test_main_fails_when_missing_rows(tmp_path: Path):
    csv_path = tmp_path / "live.csv"
    _write_sample_csv(csv_path)

    code = main(["--csv", str(csv_path), "--expected", "50"])

    assert code == 1

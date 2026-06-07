"""Unit tests for live eval CSV reporting."""

import csv
from pathlib import Path

from eval.report import (
    build_row,
    eval_id_from_text,
    failure_analysis,
    lookup_eval_ticket,
    record_live_result,
    reset_live_report_cache,
)
from eval.metrics import score_ticket
from models import DeferDecision, DeferReasonCode, ResolveDecision, TicketTriageResult
from scripts.jira_eval_tickets import summary_for
from tests.fixtures.eval_tickets import EVAL_TICKETS


def _ticket(ticket_id: str):
    return next(t for t in EVAL_TICKETS if t.id == ticket_id)


def setup_function() -> None:
    reset_live_report_cache()


def test_eval_id_from_summary_prefix():
    assert eval_id_from_text("[T-001] Password lockout") == "T-001"


def test_eval_id_ignores_unknown_ids():
    assert eval_id_from_text("T-999 is not in the eval set") is None


def test_lookup_eval_ticket_seed_webhook_body():
    ticket = _ticket("T-001")
    body = f"{summary_for(ticket)}\n\n{ticket.body}"

    found = lookup_eval_ticket(body)

    assert found is not None
    assert found.id == "T-001"


def test_lookup_eval_ticket_by_id_in_body():
    ticket = _ticket("T-002")
    body = f"[T-002] {ticket.body}"

    found = lookup_eval_ticket(body)

    assert found is not None
    assert found.id == "T-002"


def test_lookup_eval_ticket_by_exact_body():
    ticket = _ticket("T-001")

    found = lookup_eval_ticket(ticket.body)

    assert found is not None
    assert found.id == "T-001"


def test_lookup_eval_ticket_prefers_summary_id():
    ticket = _ticket("T-001")
    body = f"[T-001] summary\n\nBody mentioning T-002 but should not match."

    found = lookup_eval_ticket(body)

    assert found is not None
    assert found.id == "T-001"


def test_failure_analysis_ok():
    ticket = _ticket("T-001")
    decision = ResolveDecision(answer="x", citations=["POL-01 §1.4"])
    score = score_ticket(ticket, decision)

    text = failure_analysis(
        ticket,
        score,
        gate_overridden=False,
        agent_action="RESOLVE",
        final_action="RESOLVE",
    )

    assert text == "OK"


def test_failure_analysis_false_resolve():
    ticket = _ticket("T-026")
    decision = ResolveDecision(answer="x", citations=["POL-01 §1.4"])
    score = score_ticket(ticket, decision)

    text = failure_analysis(
        ticket,
        score,
        gate_overridden=False,
        agent_action="RESOLVE",
        final_action="RESOLVE",
    )

    assert "False RESOLVE" in text


def test_failure_analysis_gate_override_shows_transition():
    ticket = _ticket("T-026")
    agent = ResolveDecision(answer="x", citations=["POL-01 §1.4"])
    final = DeferDecision(answer="y", reason_code=DeferReasonCode.OUT_OF_SCOPE)
    score = score_ticket(ticket, final)

    text = failure_analysis(
        ticket,
        score,
        gate_overridden=True,
        agent_action="RESOLVE",
        final_action="DEFER",
    )

    assert "Grounding gate overrode agent (RESOLVE -> DEFER)" in text


def test_live_report_appends_incrementally(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "live.csv"
    monkeypatch.setenv("EVAL_LIVE_REPORT_PATH", str(report_path))

    ticket = _ticket("T-001")
    result = TicketTriageResult(
        ticket_id="T-001",
        agent_decision=ResolveDecision(answer="a", citations=["POL-01 §1.4"]),
        final_decision=ResolveDecision(answer="a", citations=["POL-01 §1.4"]),
    )

    assert record_live_result("BTS-10", f"[T-001] {ticket.body}", result) is True
    assert record_live_result("BTS-11", "not an eval ticket", result) is False

    rows = list(csv.DictReader(report_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["ticket_id"] == "T-001"
    assert rows[0]["jira_issue_key"] == "BTS-10"
    assert rows[0]["expected_action"] == "RESOLVE"
    assert rows[0]["final_action"] == "RESOLVE"
    assert rows[0]["failure_analysis"] == "OK"


def test_live_report_skips_duplicate_jira_issue(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "live.csv"
    monkeypatch.setenv("EVAL_LIVE_REPORT_PATH", str(report_path))

    ticket = _ticket("T-001")
    result = TicketTriageResult(
        ticket_id="T-001",
        agent_decision=ResolveDecision(answer="a", citations=["POL-01 §1.4"]),
        final_decision=ResolveDecision(answer="a", citations=["POL-01 §1.4"]),
    )
    body = f"{summary_for(ticket)}\n\n{ticket.body}"

    assert record_live_result("BTS-10", body, result) is True
    assert record_live_result("BTS-10", body, result) is False

    rows = list(csv.DictReader(report_path.open(encoding="utf-8")))
    assert len(rows) == 1


def test_live_report_resumes_existing_file(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "live.csv"
    monkeypatch.setenv("EVAL_LIVE_REPORT_PATH", str(report_path))

    ticket = _ticket("T-001")
    result = TicketTriageResult(
        ticket_id="T-001",
        agent_decision=ResolveDecision(answer="a", citations=["POL-01 §1.4"]),
        final_decision=ResolveDecision(answer="a", citations=["POL-01 §1.4"]),
    )
    body = f"{summary_for(ticket)}\n\n{ticket.body}"

    assert record_live_result("BTS-10", body, result) is True
    reset_live_report_cache()
    assert record_live_result("BTS-10", body, result) is False

    rows = list(csv.DictReader(report_path.open(encoding="utf-8")))
    assert len(rows) == 1


def test_build_row_includes_predicted_and_ground_truth():
    ticket = _ticket("T-029")
    result = TicketTriageResult(
        ticket_id="T-029",
        agent_decision=DeferDecision(
            answer="defer",
            reason_code=DeferReasonCode.OUT_OF_SCOPE,
        ),
        final_decision=DeferDecision(
            answer="defer",
            reason_code=DeferReasonCode.OUT_OF_SCOPE,
        ),
    )

    row = build_row(ticket, result, jira_issue_key="BTS-99")

    assert row["expected_action"] == "DEFER"
    assert row["final_action"] == "DEFER"
    assert row["expected_reason_code"] == "ACTIVE_INCIDENT"
    assert row["final_reason_code"] == "OUT_OF_SCOPE"
    assert "Reason code mismatch" in row["failure_analysis"]

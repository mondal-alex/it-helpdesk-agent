"""FastAPI webhook service for Jira-triggered ticket triage."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from eval.live_progress import live_progress
from eval.report import lookup_eval_ticket, record_live_result
from logging_config import configure_logging
from models import DeferDecision, ResolveDecision
from runner import process_ticket

logger = logging.getLogger(__name__)

_ISSUE_CREATED = "jira:issue_created"
JIRA_WEBHOOK_PATH = "/rest/webhooks/jira"
_WEBHOOK_SECRET = os.getenv("JIRA_WEBHOOK_SECRET", "").strip()
_HUB_SIGNATURE_PREFIX = "sha256="

app = FastAPI(
    title="IT Helpdesk Agent",
    description="Receives Jira webhooks and triages tickets via runner.process_ticket.",
    version="0.1.0",
)


@app.on_event("startup")
def _configure_logging() -> None:
    configure_logging()


class WebhookAccepted(BaseModel):
    status: str = "accepted"
    issue_key: str | None = None
    message: str


class HealthResponse(BaseModel):
    status: str = "ok"


class ProcessResult(BaseModel):
    issue_key: str
    action: str
    gate_overridden: bool
    reason_code: str | None = None
    citations: list[str] = Field(default_factory=list)


def _adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format (ADF) description text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text", ""))

    parts: list[str] = []
    for child in node.get("content") or []:
        parts.append(_adf_to_text(child))
    if node_type in {"paragraph", "heading", "listItem", "blockquote"}:
        parts.append("\n")
    return "".join(parts)


def extract_ticket_body(fields: dict[str, Any]) -> str:
    """Build the ticket text passed to the triage agent."""
    summary = (fields.get("summary") or "").strip()
    description_raw = fields.get("description")
    if isinstance(description_raw, str):
        description = description_raw.strip()
    elif isinstance(description_raw, dict):
        description = _adf_to_text(description_raw).strip()
    else:
        description = ""

    if summary and description:
        return f"{summary}\n\n{description}"
    return summary or description


def parse_jira_webhook(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Return (issue_key, body) when the payload should be triaged, else None."""
    event = payload.get("webhookEvent")
    if event != _ISSUE_CREATED:
        return None

    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return None

    issue_key = issue.get("key")
    fields = issue.get("fields")
    if not issue_key or not isinstance(fields, dict):
        return None

    body = extract_ticket_body(fields)
    if not body.strip():
        logger.info("Skipping %s: empty ticket body", issue_key)
        return None

    return str(issue_key), body


def _decision_summary(issue_key: str, result) -> ProcessResult:
    decision = result.final_decision
    if isinstance(decision, ResolveDecision):
        return ProcessResult(
            issue_key=issue_key,
            action="RESOLVE",
            gate_overridden=result.gate_overridden,
            citations=[str(c) for c in decision.citations],
        )
    assert isinstance(decision, DeferDecision)
    return ProcessResult(
        issue_key=issue_key,
        action="DEFER",
        gate_overridden=result.gate_overridden,
        reason_code=decision.reason_code.value,
        citations=[str(c) for c in decision.citations],
    )


def verify_jira_webhook_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Verify Jira Cloud admin webhook HMAC (X-Hub-Signature: sha256=...)."""
    if not secret:
        return True
    if not signature_header or not signature_header.startswith(_HUB_SIGNATURE_PREFIX):
        return False
    expected = signature_header[len(_HUB_SIGNATURE_PREFIX) :]
    computed = hmac.new(
        secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, expected)


def _verify_webhook_signature(request: Request, body: bytes) -> None:
    if not _WEBHOOK_SECRET:
        return
    signature = request.headers.get("X-Hub-Signature")
    if not verify_jira_webhook_signature(body, signature, _WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _run_pipeline(issue_key: str, body: str) -> None:
    progress = live_progress()
    progress.started(issue_key, body)
    try:
        result = process_ticket(issue_key, body)
        summary = _decision_summary(issue_key, result)
        logger.info(
            "Processed %s -> %s (gate_overridden=%s)",
            issue_key,
            summary.action,
            summary.gate_overridden,
        )
        _record_live_eval(issue_key, body, result)
        progress.finished(issue_key, body, action=summary.action, success=True)
    except Exception:
        progress.finished(issue_key, body, action="ERROR", success=False)
        logger.exception("Failed to process Jira issue %s", issue_key)


def _record_live_eval(issue_key: str, body: str, result) -> None:
    try:
        record_live_result(issue_key, body, result)
    except Exception:
        logger.exception("Failed to write live eval report for %s", issue_key)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post(JIRA_WEBHOOK_PATH, response_model=WebhookAccepted)
async def jira_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> WebhookAccepted:
    """Accept Jira issue-created webhooks and triage tickets in the background."""
    body_bytes = await request.body()
    _verify_webhook_signature(request, body_bytes)

    try:
        payload = json.loads(body_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    parsed = parse_jira_webhook(payload)
    if parsed is None:
        event = payload.get("webhookEvent", "unknown")
        return WebhookAccepted(message=f"Ignored event: {event}")

    issue_key, body = parsed
    if lookup_eval_ticket(body):
        live_progress().queued(issue_key, body)
    background_tasks.add_task(_run_pipeline, issue_key, body)
    return WebhookAccepted(
        issue_key=issue_key,
        message="Ticket queued for triage",
    )

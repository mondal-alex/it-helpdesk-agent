"""Jira integration for applying ticket triage decisions."""

import json
import os
from typing import List, Tuple

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

from models import TicketAction, TicketDecision, format_ticket_comment
from rate_limit import jira_request

load_dotenv()

_DEFER_LABEL = "defer"
_RESOLVED_LABEL = "resolved"
TRIAGE_ERROR_COMMENT = (
    "Error during processing. Please refer to technical support."
)

_JIRA_ENV_VARS = (
    "JIRA_DOMAIN",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "IN_REVIEW_COLUMN_STATUS",
    "DEFER_COLUMN_STATUS",
    "RESOLVED_COLUMN_STATUS",
)


class JiraConfigError(RuntimeError):
    """Raised when required Jira environment variables are missing."""


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise JiraConfigError(
            f"Missing required environment variable '{name}'. "
            f"Set it in .env or the process environment. "
            f"Required: {', '.join(_JIRA_ENV_VARS)}"
        )
    return value.strip()


def _jira_base_url() -> str:
    return f"https://{_require_env('JIRA_DOMAIN')}.atlassian.net"


def _jira_auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(_require_env("JIRA_EMAIL"), _require_env("JIRA_API_TOKEN"))


def mark_under_agent_review(jira_issue_id: str) -> None:
    """Transition an issue to the in-review status while the agent triages it."""
    transition_issue_to_status(
        jira_issue_id,
        _require_env("IN_REVIEW_COLUMN_STATUS"),
    )


def mark_triage_failed(jira_issue_id: str) -> None:
    """Move a failed ticket to manual review with a support-facing comment."""
    transition_issue_to_status(
        jira_issue_id,
        _require_env("DEFER_COLUMN_STATUS"),
        comment=TRIAGE_ERROR_COMMENT,
        label=_DEFER_LABEL,
    )


def handle_ticket(
    jira_issue_id: str,
    decision: TicketDecision,
) -> None:
    """Apply a triage decision to Jira in one atomic transition request."""
    comment = format_ticket_comment(decision)
    status, label = _match(decision.action)
    transition_issue_to_status(
        jira_issue_id,
        status,
        comment=comment,
        label=label,
    )


def _normalize_status_name(name: str) -> str:
    """Normalize a Jira status name for case-insensitive comparison."""
    return name.casefold().strip()


def _find_transition_id(transitions: List[dict], status_name: str) -> str | None:
    """Return a transition id for status_name (exact match, then case-insensitive)."""
    target = _normalize_status_name(status_name)
    case_insensitive_match: str | None = None

    for transition in transitions:
        destination_name = transition["to"]["name"]
        if destination_name == status_name:
            return transition["id"]
        if (
            case_insensitive_match is None
            and _normalize_status_name(destination_name) == target
        ):
            case_insensitive_match = transition["id"]

    return case_insensitive_match


def transition_issue_to_status(
    issue_id: str,
    status_name: str,
    *,
    comment: str | None = None,
    label: str | None = None,
) -> None:
    """Move an issue to a workflow status, optionally with comment and label."""
    transitions = _get_available_transitions(issue_id)
    transition_id = _find_transition_id(transitions, status_name)

    if not transition_id:
        available = [t["to"]["name"] for t in transitions]
        raise ValueError(
            f"Could not find an available Jira transition for issue {issue_id} "
            f"to status '{status_name}'. Available destinations: {available}. "
            "Confirm the status exists on the board and that the issue's current "
            "workflow state allows transitioning to it."
        )

    _transition_with_updates(
        issue_id,
        destination_id=transition_id,
        comment=comment,
        label=label,
    )


def _match(ticket_action: TicketAction) -> Tuple[str, str]:
    """Match a ticket action to a Jira column status and label."""
    match ticket_action:
        case TicketAction.DEFER:
            return (_require_env("DEFER_COLUMN_STATUS"), _DEFER_LABEL)
        case TicketAction.RESOLVED:
            return (_require_env("RESOLVED_COLUMN_STATUS"), _RESOLVED_LABEL)


def _comment_adf_body(text: str) -> dict:
    """Build Atlassian Document Format for a Jira v3 comment body."""
    paragraphs = []
    for line in text.split("\n"):
        node: dict = {"type": "paragraph"}
        if line:
            node["content"] = [{"type": "text", "text": line}]
        else:
            node["content"] = []
        paragraphs.append(node)
    return {"type": "doc", "version": 1, "content": paragraphs}


def _build_transition_payload(
    destination_id: str,
    *,
    comment: str | None = None,
    label: str | None = None,
) -> dict:
    """Build a Jira transition request body with optional comment and label."""
    body: dict = {"transition": {"id": destination_id}}
    update: dict = {}
    if comment is not None:
        update["comment"] = [{"add": {"body": _comment_adf_body(comment)}}]
    if label is not None:
        update["labels"] = [{"add": label}]
    if update:
        body["update"] = update
    return body


def _get_available_transitions(issue_id: str) -> List[dict]:
    """Return the Jira workflow transitions available for an issue."""
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_id}/transitions"
    headers = {"Accept": "application/json"}

    response = jira_request(
        "GET", url, headers=headers, auth=_jira_auth(), timeout=10
    )
    if response.status_code != 200:
        raise requests.HTTPError(
            f"Error fetching transitions: status {response.status_code}: {response.text}"
        )

    return response.json()["transitions"]


def _transition_with_updates(
    issue_id: str,
    *,
    destination_id: str,
    comment: str | None = None,
    label: str | None = None,
) -> None:
    """Transition a Jira issue, bundling comment and label in the same request."""
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_id}/transitions"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = json.dumps(
        _build_transition_payload(
            destination_id,
            comment=comment,
            label=label,
        )
    )

    response = jira_request(
        "POST",
        url,
        data=payload,
        headers=headers,
        auth=_jira_auth(),
        timeout=10,
    )
    if response.status_code != 204:
        raise requests.HTTPError(
            f"Error transitioning issue: status {response.status_code}: {response.text}"
        )

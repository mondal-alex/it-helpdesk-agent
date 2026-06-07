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


def handle_ticket(
    jira_issue_id: str,
    decision: TicketDecision,
) -> None:
    """Apply a triage decision to Jira: post comment, add label, transition status."""
    comment = format_ticket_comment(decision)
    status, label = _match(decision.action)

    _post_comment(jira_issue_id, comment)
    _add_label_to_issue(jira_issue_id, label)
    transition_issue_to_status(jira_issue_id, status)


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


def transition_issue_to_status(issue_id: str, status_name: str) -> None:
    """Move an issue to a workflow status by Jira status name."""
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

    _transition_to_destination(issue_id, destination_id=transition_id)


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


def _post_comment(issue_id: str, comment: str) -> None:
    """Posts a comment to a Jira issue."""
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_id}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"body": _comment_adf_body(comment)})

    response = jira_request(
        "POST",
        url,
        data=payload,
        headers=headers,
        auth=_jira_auth(),
        timeout=10,
    )
    if response.status_code != 201:
        raise requests.HTTPError(
            f"Error posting comment: status {response.status_code}: {response.text}"
        )


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


def _transition_to_destination(issue_id: str, destination_id: str) -> None:
    """Transition a Jira issue to the given workflow destination."""
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_id}/transitions"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"transition": {"id": destination_id}})

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


def _add_label_to_issue(issue_id: str, label: str) -> None:
    """Add a label to a Jira issue."""
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_id}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"update": {"labels": [{"add": label}]}})

    response = jira_request(
        "PUT",
        url,
        data=payload,
        headers=headers,
        auth=_jira_auth(),
        timeout=10,
    )
    if response.status_code not in {200, 204}:
        raise requests.HTTPError(
            f"Error adding label: status {response.status_code}: {response.text}"
        )

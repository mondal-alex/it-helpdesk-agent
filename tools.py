"""Tools for the agent.

TODO: Add observability and logging rather than print statements for errors.
TODO: Handle partial side effects in handle_ticket.
TODO: Return value for tool?
"""

import json
import os
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv
from langchain.tools import tool
from requests.auth import HTTPBasicAuth

from models import (
    DeferReasonCode,
    TicketAction,
    build_ticket_decision,
    format_ticket_comment,
)

load_dotenv()

_MANUAL_REVIEW_LABEL = "needs-manual-review"
_RESOLVED_LABEL = "resolved"

_JIRA_ENV_VARS = (
    "JIRA_DOMAIN",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "MANUAL_REVIEW_COLUMN_STATUS",
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


######### 1. TOOLS ##############


@tool
def handle_ticket(
    jira_issue_id: str,
    ticket_action: TicketAction,
    answer: str,
    citations: Optional[List[str]] = None,
    reason_code: Optional[DeferReasonCode] = None,
) -> None:
    """Resolve or defer a Jira ticket: post comment, add label, transition status.

    For RESOLVED, provide one or more policy citations (e.g. ``POL-01 §1.4``).
    For NEEDS_MANUAL_REVIEW, provide a ``reason_code`` from the standard defer list.
    """
    decision = build_ticket_decision(
        ticket_action,
        answer,
        citations=citations,
        reason_code=reason_code,
    )
    comment = format_ticket_comment(decision)
    status, label = _match(ticket_action)

    # 1. Post the comment.
    _post_comment(jira_issue_id, comment)

    # 2. Label the ticket.
    _add_label_to_issue(jira_issue_id, label)

    # 3. Get available transitions.
    transitions = _get_available_transitions(jira_issue_id)

    # 4. Get the transition ID for the destination name.
    transition_id = next(
        (t["id"] for t in transitions if t["to"]["name"] == status),
        None,
    )

    if not transition_id:
        available = [t["to"]["name"] for t in transitions]
        raise ValueError(
            f"Could not find an available Jira transition for issue {jira_issue_id} "
            f"to status '{status}'. Available destinations: {available}. "
            "Confirm the status exists on the board and that the issue's current "
            "workflow state allows transitioning to it."
        )

    # 5. Transition the ticket to the available column.
    _transition_to_destination(jira_issue_id, destination_id=transition_id)


ALL_TOOLS = [handle_ticket]


######### 2. HELPER FUNCTIONS #############


def _match(ticket_action: TicketAction) -> Tuple[str, str]:
    """Match a ticket action to a Jira column status and label."""
    match ticket_action:
        case TicketAction.NEEDS_MANUAL_REVIEW:
            return (_require_env("MANUAL_REVIEW_COLUMN_STATUS"), _MANUAL_REVIEW_LABEL)
        case TicketAction.RESOLVED:
            return (_require_env("RESOLVED_COLUMN_STATUS"), _RESOLVED_LABEL)


def _post_comment(issue_id: str, comment: str) -> None:
    """Posts a comment to a Jira issue."""
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_id}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = json.dumps(
        {
            "body": {
                "content": [
                    {
                        "content": [{"text": comment, "type": "text"}],
                        "type": "paragraph",
                    }
                ],
                "type": "doc",
                "version": 1,
            },
            "visibility": {
                "identifier": "Administrators",
                "type": "role",
                "value": "Administrators",
            },
        }
    )

    response = requests.post(
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

    response = requests.get(url, headers=headers, auth=_jira_auth(), timeout=10)
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

    response = requests.post(
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

    response = requests.put(
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

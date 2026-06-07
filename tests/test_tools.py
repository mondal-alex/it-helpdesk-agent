"""Unit tests for Jira tooling (no API calls)."""

import json
from unittest.mock import MagicMock, patch

from models import ResolveDecision
from tools import (
    TRIAGE_ERROR_COMMENT,
    _build_transition_payload,
    _comment_adf_body,
    _find_transition_id,
    _normalize_status_name,
    handle_ticket,
    mark_triage_failed,
)


def test_comment_adf_body_multiline():
    body = _comment_adf_body("Action: RESOLVED\n\nHello world")

    assert body == {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Action: RESOLVED"}],
            },
            {"type": "paragraph", "content": []},
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello world"}],
            },
        ],
    }


def test_normalize_status_name_casefolds():
    assert _normalize_status_name("UNDER AGENT REVIEW") == _normalize_status_name(
        "Under Agent Review"
    )


def test_find_transition_id_exact_match():
    transitions = [
        {"id": "1", "to": {"name": "Under Agent Review"}},
        {"id": "2", "to": {"name": "RESOLVED"}},
    ]

    assert _find_transition_id(transitions, "Under Agent Review") == "1"


def test_find_transition_id_case_insensitive_match():
    transitions = [
        {"id": "1", "to": {"name": "Under Agent Review"}},
        {"id": "2", "to": {"name": "RESOLVED"}},
    ]

    assert _find_transition_id(transitions, "UNDER AGENT REVIEW") == "1"
    assert _find_transition_id(transitions, "resolved") == "2"


def test_find_transition_id_prefers_exact_over_case_insensitive():
    transitions = [
        {"id": "1", "to": {"name": "Open"}},
        {"id": "2", "to": {"name": "open"}},
    ]

    assert _find_transition_id(transitions, "Open") == "1"


def test_find_transition_id_returns_none_when_missing():
    transitions = [{"id": "1", "to": {"name": "RESOLVED"}}]

    assert _find_transition_id(transitions, "UNDER AGENT REVIEW") is None


def test_build_transition_payload_is_transition_only():
    assert _build_transition_payload("5") == {"transition": {"id": "5"}}


@patch("tools.jira_request")
@patch("tools._get_available_transitions")
@patch("tools._require_env")
def test_handle_ticket_uses_single_transition_request(
    mock_require_env,
    mock_get_transitions,
    mock_jira_request,
):
    mock_require_env.side_effect = lambda name: {
        "RESOLVED_COLUMN_STATUS": "RESOLVED",
        "JIRA_DOMAIN": "example",
        "JIRA_EMAIL": "u@example.com",
        "JIRA_API_TOKEN": "token",
    }[name]
    mock_get_transitions.return_value = [{"id": "9", "to": {"name": "RESOLVED"}}]
    mock_jira_request.side_effect = [
        MagicMock(status_code=201),
        MagicMock(status_code=204),
        MagicMock(status_code=204),
    ]

    decision = ResolveDecision(answer="ok", citations=["POL-01 §1.4"])
    handle_ticket("HELIX-1", decision)

    assert mock_jira_request.call_count == 3

    comment_call = mock_jira_request.call_args_list[0]
    assert comment_call.args[0] == "POST"
    assert comment_call.args[1].endswith("/rest/api/3/issue/HELIX-1/comment")
    comment_body = json.loads(comment_call.kwargs["data"])
    comment_text = comment_body["body"]["content"][0]["content"][0]["text"]
    assert comment_text == "Action: RESOLVED"

    transition_call = mock_jira_request.call_args_list[1]
    assert transition_call.args[0] == "POST"
    assert transition_call.args[1].endswith("/rest/api/3/issue/HELIX-1/transitions")
    assert json.loads(transition_call.kwargs["data"]) == {"transition": {"id": "9"}}

    label_call = mock_jira_request.call_args_list[2]
    assert label_call.args[0] == "PUT"
    label_body = json.loads(label_call.kwargs["data"])
    assert label_body["update"]["labels"] == [{"add": "resolved"}]


@patch("tools.transition_issue_to_status")
@patch("tools._require_env")
def test_mark_triage_failed_moves_to_manual_review_with_support_comment(
    mock_require_env,
    mock_transition,
):
    mock_require_env.return_value = "NEEDS MANUAL REVIEW"
    mark_triage_failed("HELIX-99")

    mock_transition.assert_called_once_with(
        "HELIX-99",
        "NEEDS MANUAL REVIEW",
        comment=TRIAGE_ERROR_COMMENT,
        label="defer",
    )

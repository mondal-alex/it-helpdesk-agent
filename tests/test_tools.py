"""Unit tests for Jira tooling (no API calls)."""

from tools import _comment_adf_body, _find_transition_id, _normalize_status_name


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

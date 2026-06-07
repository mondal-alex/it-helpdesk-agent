"""Unit tests for Jira tooling (no API calls)."""

from tools import _comment_adf_body


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

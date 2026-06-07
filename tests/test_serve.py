"""Unit tests for Jira webhook parsing and signature verification."""

from serve import (
    JIRA_WEBHOOK_PATH,
    app,
    extract_ticket_body,
    parse_jira_webhook,
    verify_jira_webhook_signature,
)


def test_parse_issue_created_webhook():
    payload = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": "HELIX-42",
            "fields": {
                "summary": "VPN in Vietnam",
                "description": "Will my VPN work next month?",
            },
        },
    }

    parsed = parse_jira_webhook(payload)

    assert parsed == ("HELIX-42", "VPN in Vietnam\n\nWill my VPN work next month?")


def test_parse_ignores_non_create_events():
    payload = {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": "HELIX-42",
            "fields": {"summary": "x", "description": "y"},
        },
    }

    assert parse_jira_webhook(payload) is None


def test_extract_ticket_body_from_adf():
    fields = {
        "summary": "Password lockout",
        "description": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Locked after 3 tries."}],
                }
            ],
        },
    }

    body = extract_ticket_body(fields)

    assert body.startswith("Password lockout")
    assert "Locked after 3 tries." in body


def test_verify_jira_webhook_signature_atlassian_example():
    secret = "It's a Secret to Everybody"
    payload = b"Hello World!"
    signature = (
        "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9"
    )

    assert verify_jira_webhook_signature(payload, signature, secret) is True


def test_verify_jira_webhook_signature_rejects_invalid():
    payload = b"Hello World!"
    signature = "sha256=deadbeef"

    assert (
        verify_jira_webhook_signature(payload, signature, "It's a Secret to Everybody")
        is False
    )


def test_verify_jira_webhook_signature_skips_when_no_secret():
    assert verify_jira_webhook_signature(b"anything", None, "") is True


def test_jira_webhook_route_registered():
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert JIRA_WEBHOOK_PATH in paths

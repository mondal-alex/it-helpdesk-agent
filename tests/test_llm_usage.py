"""Unit tests for LLM usage extraction in runner."""

from langchain_core.messages import AIMessage, HumanMessage

from runner import _summarize_llm_usage


def test_summarize_llm_usage_sums_across_ai_messages():
    messages = [
        HumanMessage(content="ticket body"),
        AIMessage(
            content="first",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        ),
        AIMessage(
            content="second",
            usage_metadata={
                "input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 60,
            },
        ),
    ]

    usage = _summarize_llm_usage(messages)

    assert usage == {
        "input_tokens": 150,
        "output_tokens": 30,
        "total_tokens": 180,
    }


def test_summarize_llm_usage_derives_total_when_missing():
    messages = [
        AIMessage(
            content="reply",
            usage_metadata={
                "input_tokens": 40,
                "output_tokens": 12,
                "total_tokens": 0,
            },
        ),
    ]

    usage = _summarize_llm_usage(messages)

    assert usage == {
        "input_tokens": 40,
        "output_tokens": 12,
        "total_tokens": 52,
    }


def test_summarize_llm_usage_returns_none_when_metadata_missing():
    messages = [
        HumanMessage(content="ticket body"),
        AIMessage(content="no usage metadata"),
    ]

    usage = _summarize_llm_usage(messages)

    assert usage == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_summarize_llm_usage_handles_empty_message_list():
    usage = _summarize_llm_usage([])

    assert usage == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }

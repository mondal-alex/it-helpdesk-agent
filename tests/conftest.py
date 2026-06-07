"""Shared pytest configuration."""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


def _llm_configured() -> bool:
    model = (os.getenv("MODEL") or "").strip()
    if not model:
        return False
    if model.startswith("ollama:"):
        return True
    if model.startswith("google_genai:"):
        return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    return bool(
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )


requires_llm = pytest.mark.skipif(
    not _llm_configured(),
    reason=(
        "Set MODEL to run LLM integration tests "
        "(ollama:... for local Ollama, or a cloud provider API key)"
    ),
)

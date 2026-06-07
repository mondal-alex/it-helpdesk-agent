"""LangChain agent for IT helpdesk ticket triage.

The agent produces a structured ``TicketDecision`` via ``response_format`` only.
Jira side effects are applied separately by ``runner.process_ticket`` after
grounding gates (to be added) — the model never writes to Jira directly.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from pydantic import TypeAdapter

from models import TicketDecision
from prompt import SYSTEM_PROMPT

load_dotenv()

_GOOGLE_MODEL_PREFIX = "google_genai:"
_OLLAMA_MODEL_PREFIX = "ollama:"


def _require_model() -> str:
    model = os.getenv("MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "Missing MODEL environment variable. Set it in .env — e.g. "
            "ollama:qwen2.5:7b (local) or google_genai:gemini-2.0-flash (Google free tier)."
        )
    if model.startswith(_GOOGLE_MODEL_PREFIX) and not (
        os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    ):
        raise RuntimeError(
            "MODEL is set to a Google Gemini model but no API key was found. "
            "Set GOOGLE_API_KEY in .env (free tier key: https://aistudio.google.com/apikey)."
        )
    return model


_MODEL = _require_model()
_DECISION_RESPONSE_FORMAT = TypeAdapter(TicketDecision).json_schema()

AGENT = create_agent(
    model=_MODEL,
    system_prompt=SYSTEM_PROMPT,
    response_format=_DECISION_RESPONSE_FORMAT,
)

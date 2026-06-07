"""LangChain agent for IT helpdesk ticket triage.

The agent produces a structured ``TicketDecision`` via ``response_format`` only.
Jira side effects are applied separately by ``runner.process_ticket`` after
grounding gates (to be added) — the model never writes to Jira directly.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
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
            "ollama:qwen2.5:7b (local) or google_genai:gemini-3.5-flash (Google free tier)."
        )
    if model.startswith(_GOOGLE_MODEL_PREFIX) and not (
        os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    ):
        raise RuntimeError(
            "MODEL is set to a Google Gemini model but no API key was found. "
            "Set GOOGLE_API_KEY in .env (free tier key: https://aistudio.google.com/apikey)."
        )
    return model


def _build_model() -> str | BaseChatModel:
    """Return a LangChain model id or a configured chat model instance."""
    model = _require_model()
    if not model.startswith(_GOOGLE_MODEL_PREFIX):
        return model

    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    # IT triage must handle simulated phishing/malware tickets without Gemini
    # blocking the response (PROHIBITED_CONTENT → empty output).
    safety_settings = {
        types.HarmCategory.HARM_CATEGORY_HARASSMENT: (
            types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: (
            types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: (
            types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: (
            types.HarmBlockThreshold.BLOCK_NONE
        ),
    }

    return ChatGoogleGenerativeAI(
        model=model.removeprefix(_GOOGLE_MODEL_PREFIX),
        safety_settings=safety_settings,
    )


_MODEL = _build_model()
_DECISION_RESPONSE_FORMAT = TypeAdapter(TicketDecision).json_schema()

AGENT = create_agent(
    model=_MODEL,
    system_prompt=SYSTEM_PROMPT,
    response_format=_DECISION_RESPONSE_FORMAT,
)

"""LangChain agent for IT helpdesk ticket triage.

The agent produces a structured ``TicketDecision`` via ``response_format`` only.
Jira side effects are applied separately by ``runner.process_ticket`` after
grounding gates (to be added) — the model never writes to Jira directly.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent

from models import DecisionUnion
from prompt import SYSTEM_PROMPT

load_dotenv()

_MODEL = os.getenv("MODEL")

AGENT = create_agent(
    model=_MODEL,
    system_prompt=SYSTEM_PROMPT,
    response_format=DecisionUnion,
)

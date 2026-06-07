"The agent implementation."

import os

from .prompt import SYSTEM_PROMPT
from .tools import ALL_TOOLS

from langchain.agents import create_agent
from dotenv import load_dotenv

load_dotenv()

_MODEL = os.getenv("MODEL")

AGENT = create_agent(
    model=_MODEL,
    tools=ALL_TOOLS,
    system_prompt=SYSTEM_PROMPT
)

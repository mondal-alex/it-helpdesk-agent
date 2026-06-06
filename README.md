# IT Help Desk Agent

This agent resolves IT Help Desk Tickets stored in a Jira Kanban board. To resolve a ticket, the agent references a set of policies. If the agent cannot find a relevant policy to resolve the ticket with 100% certainty, it marks the ticket for human review.

The agent is powered by AI and is built following the ReACT framework (Reasoning and Action). First, it reasons in a chain-of-thought style. Second, it decides if it needs to take an action (seaching for a policy or a tool call). It proceeds in this loop until it reaches a conclusion.

## Architecture

The AI agent itself is implemented using LangChain. It has a set of tools that use the Atlassian API to interact with the Jira board. It uses a vector store with metadata to retrieve relevant policies to the inquiry. It's prompt is engineered to safeguard against uncertainty.

## Prompt Strategy

## Grounding

## Evaluation:

1. Correctness - Does the agent resolve the right tickets, and leave the right ones alone?
2. Grounding - Are answers traceable to a specific policy section, or does it hallucinate?
3. Judgement - Does it recognize when a ticket is out of scope, ambiguous or sensitive?

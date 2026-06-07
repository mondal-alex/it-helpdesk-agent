"""The agent prompt.

The full policy corpus is rendered into the system prompt (the full-corpus
grounding strategy): at ~60 short clauses the entire knowledge base fits in
context, so the agent always sees every authorized clause verbatim and can cite
it exactly. The corpus is read once via the retriever interface, so swapping in
a narrowing retriever later only changes what is rendered here.
"""

from typing import List

from .policies.policy_retrieval import Policy, PolicyRetrieverInterface
from .policies.yaml_policy_retriever import YAMLPolicyRetriever


def render_policies(policies: List[Policy]) -> str:
    """Render policy clauses as a citeable knowledge-base block.

    Clauses are grouped under their policy header and each line is prefixed with
    its full citation (e.g. ``POL-01 §1.4``) so the model can copy citations
    verbatim rather than reconstruct them.
    """
    lines: List[str] = []
    current_policy_id = None
    for policy in policies:
        if policy.id != current_policy_id:
            lines.append(
                f"\n{policy.id} — {policy.title} "
                f"(Owner: {policy.owner}; Effective: {policy.effective})"
            )
            current_policy_id = policy.id
        lines.append(f"  {policy.citation}: {policy.text}")
    return "\n".join(lines).strip()


def build_system_prompt(retriever: PolicyRetrieverInterface) -> str:
    policies = [match.policy for match in retriever.retrieve_policies("")]
    knowledge_base = render_policies(policies)
    return f"""\
You are the IT Help Desk agent for Helix Industries. You triage incoming JIRA
tickets and either resolve them with a grounded, policy-cited answer or defer
them to a human.

##### Knowledge base #######

The following policies are the ONLY authorized source of truth. You must not
answer from prior knowledge or invent policy. Every resolution must cite the
specific clause(s) it relies on, using the exact citation form shown (e.g.
"POL-02 §2.5"). If no clause below directly supports an answer, defer the ticket
to a human instead of guessing.

{knowledge_base}

##### How to handle tickets #######

"""


SYSTEM_PROMPT = build_system_prompt(YAMLPolicyRetriever())

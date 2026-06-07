"""Policy retrieval from a YAML file.

This is the baseline retriever for the small, fixed Helix policy corpus (10
policies / 60 clauses). Its retrieval strategy is full-corpus: it returns every
clause, in stable policy order, so the entire knowledge base is placed in the
agent's context rather than narrowed. At this size that maximizes grounding
recall and keeps the prompt deterministic; the ``PolicyRetrieverInterface`` seam
lets a vector/hybrid retriever drop in later without touching the agent.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .policy_retrieval import Policy, PolicyMatch, PolicyRetrieverInterface

_DEFAULT_POLICY_FILE = Path(__file__).parent / "policies.yaml"

# Full-corpus retrieval does not rank, so every clause is surfaced with the same
# neutral score; a narrowing retriever would emit real per-clause scores here.
_NEUTRAL_SCORE = 1.0


class YAMLPolicyRetriever(PolicyRetrieverInterface):
    """Retrieve policies from a YAML file."""

    def __init__(self, policy_file: Path = _DEFAULT_POLICY_FILE) -> None:
        self._policies: List[Policy] = self._load(policy_file)
        # Index by citation ids for O(1) grounding lookups.
        self._by_citation: Dict[Tuple[str, str], Policy] = {
            (p.id, p.section): p for p in self._policies
        }

    @staticmethod
    def _load(policy_file: Path) -> List[Policy]:
        with open(policy_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        policies: List[Policy] = []
        for policy in raw["policies"]:
            for section in policy["sections"]:
                policies.append(
                    Policy(
                        id=policy["id"],
                        title=policy["title"],
                        owner=policy["owner"],
                        # YAML may parse an unquoted date into a date object;
                        # normalize to an ISO string to honor Policy.effective: str.
                        effective=str(policy["effective"]),
                        section=str(section["section"]),
                        text=section["text"].strip(),
                    )
                )
        return policies

    def retrieve_policies(self, inquiry: str) -> List[PolicyMatch]:
        # Full-corpus strategy: the inquiry does not narrow the result; the whole
        # knowledge base is returned in stable policy order for the agent to
        # ground against.
        return [
            PolicyMatch(policy=policy, relevancy_score=_NEUTRAL_SCORE)
            for policy in self._policies
        ]

    def get_section(self, policy_id: str, section: str) -> Optional[Policy]:
        return self._by_citation.get((policy_id, str(section)))

"""Interface for policy retrieval."""

from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class Policy:
    id: str
    title: str
    owner: str
    effective: str
    section: str
    text: str

    @property
    def citation(self) -> str:
        """The stable citation form for this clause, e.g. 'POL-01 §1.4'."""
        return f"{self.id} §{self.section}"

@dataclass(frozen=True)
class PolicyMatch:
    policy: Policy
    relevancy_score: float

class PolicyRetrieverInterface(ABC):
    """Interface for policy retrieval.
    """

    @abstractmethod
    def retrieve_policies(self, inquiry: str) -> List[PolicyMatch]:
        """Select the policy clauses the agent should ground an inquiry in.

        This is the swappable retrieval strategy. The full-corpus implementation
        returns the entire (small) policy set; a vector/hybrid implementation
        would return a narrowed, ranked subset. Strategy-specific tuning (e.g.
        ``top_k`` or a score threshold) belongs to the concrete retriever's
        construction, not this contract, so the caller stays strategy-agnostic.

        Returns matches sorted by ``relevancy_score`` descending.
        """
        ...

    @abstractmethod
    def get_section(self, policy_id: str, section: str) -> Optional[Policy]:
        """Look up a single clause by its citation ids, or None if absent.

        This is the deterministic grounding primitive: it lets the agent verify
        that a citation it produced (e.g. POL-01 §1.4) actually exists before a
        ticket is resolved.
        """
        ...


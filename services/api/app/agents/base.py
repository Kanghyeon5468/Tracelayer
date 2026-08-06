from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import AgentIdentity, AgentOutput, InvestigationContext


class BaseInvestigationAgent(ABC):
    """Base contract shared by local agents and future Google ADK wrappers."""

    identity: AgentIdentity
    required_permissions: list[str] = []

    @abstractmethod
    def run(self, context: InvestigationContext) -> AgentOutput:
        """Mutate the investigation context and return a structured agent output."""

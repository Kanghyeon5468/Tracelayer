from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

from app.config import Settings
from app.domain.models import AgentIdentity


@dataclass(frozen=True)
class AdkBinding:
    enabled: bool
    available: bool
    framework: str
    agent_name: str | None = None
    model: str | None = None
    runtime_class: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "framework": self.framework,
            "agent_name": self.agent_name,
            "model": self.model,
            "runtime_class": self.runtime_class,
            "error": self.error,
        }


class AdkAgentRuntime:
    """Creates Google ADK Agent definitions for TraceLayer's local agent classes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bindings: dict[str, AdkBinding] = {}

    @cached_property
    def agent_class(self):
        try:
            from google.adk.agents import Agent
        except Exception:
            try:
                from google.adk.agents.llm_agent import Agent
            except Exception as exc:
                return exc
        return Agent

    @property
    def available(self) -> bool:
        return not isinstance(self.agent_class, Exception)

    def bind_agent(
        self,
        identity: AgentIdentity,
        instruction: str,
        description: str,
    ) -> AdkBinding:
        if identity.agent_id in self._bindings:
            return self._bindings[identity.agent_id]

        if not self.settings.adk_enabled:
            binding = AdkBinding(
                enabled=False,
                available=False,
                framework="google_adk",
                error="ADK runtime disabled by settings.",
            )
            self._bindings[identity.agent_id] = binding
            return binding

        if isinstance(self.agent_class, Exception):
            binding = AdkBinding(
                enabled=True,
                available=False,
                framework="google_adk",
                error=str(self.agent_class),
            )
            self._bindings[identity.agent_id] = binding
            return binding

        agent_name = identity.agent_id.replace("-", "_")
        try:
            try:
                adk_agent = self.agent_class(
                    name=agent_name,
                    model=self.settings.resolved_adk_model,
                    description=description,
                    instruction=instruction,
                )
            except TypeError:
                adk_agent = self.agent_class(
                    name=agent_name,
                    model=self.settings.resolved_adk_model,
                    instruction=instruction,
                )
        except Exception as exc:
            binding = AdkBinding(
                enabled=True,
                available=False,
                framework="google_adk",
                agent_name=agent_name,
                model=self.settings.resolved_adk_model,
                error=str(exc),
            )
            self._bindings[identity.agent_id] = binding
            return binding

        binding = AdkBinding(
            enabled=True,
            available=True,
            framework="google_adk",
            agent_name=getattr(adk_agent, "name", agent_name),
            model=self.settings.resolved_adk_model,
            runtime_class=f"{adk_agent.__class__.__module__}.{adk_agent.__class__.__name__}",
        )
        self._bindings[identity.agent_id] = binding
        return binding

    def runtime_config(self) -> dict[str, Any]:
        error = str(self.agent_class) if isinstance(self.agent_class, Exception) else None
        return {
            "enabled": self.settings.adk_enabled,
            "available": self.available,
            "framework": "google_adk",
            "model": self.settings.resolved_adk_model,
            "error": error,
        }

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Callable

from app.config import Settings
from app.domain.models import AgentIdentity, AgentOutput, InvestigationContext, RequestContext


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


@dataclass(frozen=True)
class AdkToolRunResult:
    output: AgentOutput
    metadata: dict[str, Any]


class AdkAgentRuntime:
    """Creates Google ADK agent definitions and runs guarded tools through ADK sessions."""

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

    @cached_property
    def runner_components(self) -> dict[str, Any] | Exception:
        try:
            from google.adk.agents.base_agent import BaseAgent
            from google.adk.events.event import Event
            from google.adk.runners import Runner
            from google.adk.sessions.in_memory_session_service import InMemorySessionService
            from google.genai import types
            from pydantic import ConfigDict
        except Exception as exc:
            return exc

        return {
            "BaseAgent": BaseAgent,
            "ConfigDict": ConfigDict,
            "Event": Event,
            "InMemorySessionService": InMemorySessionService,
            "Runner": Runner,
            "types": types,
        }

    @property
    def runner_available(self) -> bool:
        return self.settings.adk_enabled and not isinstance(self.runner_components, Exception)

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

    def run_agent_tool(
        self,
        identity: AgentIdentity,
        context: InvestigationContext,
        request: RequestContext,
        tool_name: str,
        description: str,
        instruction: str,
        tool_callback: Callable[[], AgentOutput],
    ) -> AdkToolRunResult:
        binding = self.bind_agent(identity, instruction=instruction, description=description)
        fallback_reason = self._runner_unavailable_reason(binding)
        if fallback_reason:
            output = tool_callback()
            metadata = {
                "framework": "google_adk",
                "mode": "python_fallback",
                "tool_invoked": True,
                "tool_name": tool_name,
                "reason": fallback_reason,
                "binding": binding.as_dict(),
            }
            output = self._attach_metadata(context, output, metadata)
            return AdkToolRunResult(output=output, metadata=metadata)

        components = self.runner_components
        if isinstance(components, Exception):
            output = tool_callback()
            metadata = {
                "framework": "google_adk",
                "mode": "python_fallback",
                "tool_invoked": True,
                "tool_name": tool_name,
                "reason": str(components),
                "binding": binding.as_dict(),
            }
            output = self._attach_metadata(context, output, metadata)
            return AdkToolRunResult(output=output, metadata=metadata)

        output_box: dict[str, AgentOutput] = {}
        runner_agent = self._build_tool_calling_agent(
            components,
            identity,
            tool_name,
            context.case_id,
            tool_callback,
            output_box,
        )
        session_service = components["InMemorySessionService"]()
        session_id = self._session_id(context, identity)
        app_name = "tracelayer-fraud-fleet"
        session_state = self._session_state(context, request, tool_name)

        try:
            self._await(
                session_service.create_session(
                    app_name=app_name,
                    user_id=request.actor_id,
                    session_id=session_id,
                    state=session_state,
                )
            )
            runner = components["Runner"](
                app_name=app_name,
                agent=runner_agent,
                session_service=session_service,
            )
            message = components["types"].Content(
                role="user",
                parts=[
                    components["types"].Part(
                        text=(
                            "Run the approved TraceLayer tool for this fraud investigation "
                            f"step: {tool_name}."
                        )
                    )
                ],
            )
            events = list(
                runner.run(
                    user_id=request.actor_id,
                    session_id=session_id,
                    new_message=message,
                )
            )
            session = self._await(
                session_service.get_session(
                    app_name=app_name,
                    user_id=request.actor_id,
                    session_id=session_id,
                )
            )
        except Exception as exc:
            output = output_box.get("output") or tool_callback()
            metadata = {
                "framework": "google_adk",
                "mode": "python_fallback",
                "tool_invoked": True,
                "tool_name": tool_name,
                "reason": f"ADK Runner execution failed: {exc}",
                "binding": binding.as_dict(),
            }
            output = self._attach_metadata(context, output, metadata)
            return AdkToolRunResult(output=output, metadata=metadata)

        output = output_box.get("output")
        if not output:
            output = tool_callback()

        metadata = {
            "framework": "google_adk",
            "mode": "adk_runner",
            "tool_invoked": True,
            "tool_name": tool_name,
            "agent_name": binding.agent_name,
            "runner_class": (
                f"{components['Runner'].__module__}.{components['Runner'].__name__}"
            ),
            "session_service_class": (
                f"{components['InMemorySessionService'].__module__}."
                f"{components['InMemorySessionService'].__name__}"
            ),
            "session_id": session_id,
            "event_count": len(events),
            "session_event_count": len(getattr(session, "events", []) or []),
            "session_state_keys": sorted((getattr(session, "state", {}) or {}).keys()),
            "binding": binding.as_dict(),
        }
        output = self._attach_metadata(context, output, metadata)
        return AdkToolRunResult(output=output, metadata=metadata)

    def runtime_config(self) -> dict[str, Any]:
        error = str(self.agent_class) if isinstance(self.agent_class, Exception) else None
        runner_error = (
            str(self.runner_components)
            if isinstance(self.runner_components, Exception)
            else None
        )
        return {
            "enabled": self.settings.adk_enabled,
            "available": self.available,
            "framework": "google_adk",
            "model": self.settings.resolved_adk_model,
            "runner_available": self.runner_available,
            "error": error,
            "runner_error": runner_error,
        }

    def _runner_unavailable_reason(self, binding: AdkBinding) -> str | None:
        if not self.settings.adk_enabled:
            return "ADK runtime disabled by settings."
        if not binding.available:
            return binding.error or "ADK Agent definition unavailable."
        if isinstance(self.runner_components, Exception):
            return str(self.runner_components)
        return None

    def _build_tool_calling_agent(
        self,
        components: dict[str, Any],
        identity: AgentIdentity,
        tool_name: str,
        case_id: str,
        tool_callback: Callable[[], AgentOutput],
        output_box: dict[str, AgentOutput],
    ):
        base_agent = components["BaseAgent"]
        event_class = components["Event"]
        config_dict = components["ConfigDict"]

        class TraceLayerToolCallingAgent(base_agent):
            model_config = config_dict(arbitrary_types_allowed=True)
            callback: Callable[[], AgentOutput]

            async def _run_async_impl(self, ctx):
                output = self.callback()
                output_box["output"] = output
                yield event_class(
                    author=self.name,
                    output={
                        "tool_name": tool_name,
                        "agent_id": identity.agent_id,
                        "summary": output.summary,
                        "confidence": output.confidence,
                    },
                    customMetadata={
                        "case_id": case_id,
                        "tool_invoked": True,
                        "trace_layer_agent_id": identity.agent_id,
                    },
                )

        return TraceLayerToolCallingAgent(
            name=f"{identity.agent_id.replace('-', '_')}_runner",
            description=(
                "Google ADK runner wrapper that invokes one approved TraceLayer "
                "investigation tool through the Agent Gateway."
            ),
            callback=tool_callback,
        )

    @staticmethod
    def _await(awaitable):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        raise RuntimeError("ADK synchronous runner cannot be used inside an active event loop.")

    @staticmethod
    def _session_id(context: InvestigationContext, identity: AgentIdentity) -> str:
        return f"{identity.agent_id}::{context.case_id}::{len(context.agent_outputs) + 1}"

    @staticmethod
    def _session_state(
        context: InvestigationContext,
        request: RequestContext,
        tool_name: str,
    ) -> dict[str, Any]:
        plan = context.investigation_plan
        return {
            "case_id": context.case_id,
            "actor_id": request.actor_id,
            "request_id": request.request_id,
            "transaction_id": context.trigger_transaction.transaction_id,
            "priority": str(context.priority),
            "risk_score": context.risk_score,
            "tool_name": tool_name,
            "plan_strategy": plan.strategy if plan else None,
            "planned_actions": [step.action for step in plan.steps] if plan else [],
            "completed_actions": [
                step.action for step in plan.steps if step.status == "completed"
            ]
            if plan
            else [],
        }

    @staticmethod
    def _attach_metadata(
        context: InvestigationContext,
        output: AgentOutput,
        metadata: dict[str, Any],
    ) -> AgentOutput:
        data = dict(output.data)
        runtime = dict(data.get("adk_runtime") or {})
        binding = metadata.get("binding")
        if isinstance(binding, dict):
            runtime.update(binding)
        runtime.update(
            {
                "execution_mode": metadata["mode"],
                "runner_available": metadata["mode"] == "adk_runner",
                "tool_invoked": metadata["tool_invoked"],
                "tool_name": metadata["tool_name"],
            }
        )
        if metadata.get("runner_class"):
            runtime["runner_class"] = metadata["runner_class"]
        if metadata.get("session_id"):
            runtime["session_id"] = metadata["session_id"]
        if metadata.get("reason"):
            runtime["execution_fallback_reason"] = metadata["reason"]
        data["adk_runtime"] = runtime
        data["adk_execution"] = {
            key: value
            for key, value in metadata.items()
            if key not in {"binding"}
        }
        updated = output.model_copy(update={"data": data})
        if context.agent_outputs and context.agent_outputs[-1].agent_id == output.agent_id:
            context.agent_outputs[-1] = updated
        return updated

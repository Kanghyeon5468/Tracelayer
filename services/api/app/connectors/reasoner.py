from __future__ import annotations

import json
import re
from typing import Any

from app.config import Settings
from app.domain.models import GuardrailFinding
from app.security.guardrails import ModelArmorGuardrail


class GeminiReasoner:
    """Thin boundary for Gemini calls with a deterministic local fallback."""

    def __init__(self, settings: Settings, guardrail: ModelArmorGuardrail | None = None) -> None:
        self.settings = settings
        self.guardrail = guardrail or ModelArmorGuardrail()
        self.last_guardrail_findings: list[GuardrailFinding] = []

    def summarize_pattern(self, prompt: str) -> str:
        self.last_guardrail_findings = self.guardrail.assert_safe_prompt(prompt)

        provider = self.settings.resolved_ai_provider
        if provider == "mock":
            return (
                "Mock Gemini analysis: the transaction combines a high-value overseas wire, "
                "new-country behavior, shared infrastructure, and unusual timing. The pattern "
                "is consistent with coordinated account takeover or mule-account movement."
            )

        if provider == "gemini_api":
            return self._summarize_with_gemini_api(prompt)

        if provider == "vertex_ai":
            return self._summarize_with_vertex_ai(prompt)

        return f"AI provider '{provider}' is not supported. Falling back to deterministic analysis."

    def propose_investigation_plan(
        self,
        prompt: str,
        fallback_proposal: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_guardrail_findings = self.guardrail.assert_safe_prompt(prompt)

        provider = self.settings.resolved_ai_provider
        if provider == "mock":
            return {
                "proposal_source": "mock_gemini_planner",
                "proposal": fallback_proposal,
                "raw_text_excerpt": json.dumps(fallback_proposal, sort_keys=True)[:500],
            }

        if provider == "gemini_api":
            raw_text = self._generate_plan_with_gemini_api(prompt)
        elif provider == "vertex_ai":
            raw_text = self._generate_plan_with_vertex_ai(prompt)
        else:
            raw_text = f"AI provider '{provider}' is not supported."

        parsed = self._extract_json_object(raw_text)
        if parsed is None:
            return {
                "proposal_source": provider,
                "proposal": None,
                "error": "Gemini planner response did not contain a valid JSON object.",
                "raw_text_excerpt": raw_text[:500],
            }

        return {
            "proposal_source": provider,
            "proposal": parsed,
            "raw_text_excerpt": raw_text[:500],
        }

    def _summarize_with_gemini_api(self, prompt: str) -> str:
        if not self.settings.gemini_api_key:
            return "Gemini API mode is enabled, but GEMINI_API_KEY is not configured."

        try:
            from google import genai
        except ImportError:
            return (
                "Gemini API key is configured, but google-genai is not installed. "
                "Install the optional gemini extra to enable live model calls."
            )

        client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._generate(client, prompt)

    def _generate_plan_with_gemini_api(self, prompt: str) -> str:
        if not self.settings.gemini_api_key:
            return "Gemini API mode is enabled, but GEMINI_API_KEY is not configured."

        try:
            from google import genai
        except ImportError:
            return (
                "Gemini API key is configured, but google-genai is not installed. "
                "Install the optional gemini extra to enable live model calls."
            )

        client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._generate(client, prompt)

    def _summarize_with_vertex_ai(self, prompt: str) -> str:
        if not self.settings.google_cloud_project:
            return "Vertex AI mode is enabled, but GOOGLE_CLOUD_PROJECT is not configured."

        try:
            from google import genai
        except ImportError:
            return (
                "Vertex AI mode is configured, but google-genai is not installed. "
                "Install the optional gemini extra to enable live model calls."
            )

        client = genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
        )
        return self._generate(client, prompt)

    def _generate_plan_with_vertex_ai(self, prompt: str) -> str:
        if not self.settings.google_cloud_project:
            return "Vertex AI mode is enabled, but GOOGLE_CLOUD_PROJECT is not configured."

        try:
            from google import genai
        except ImportError:
            return (
                "Vertex AI mode is configured, but google-genai is not installed. "
                "Install the optional gemini extra to enable live model calls."
            )

        client = genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
        )
        return self._generate(client, prompt)

    def _generate(self, client, prompt: str) -> str:
        try:
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
            )
        except Exception as exc:
            return f"Live Gemini call failed: {exc}"

        return response.text or "Gemini returned an empty response."

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
            stripped = re.sub(r"\s*```$", "", stripped)

        candidates = [stripped]
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            candidates.append(stripped[first_brace : last_brace + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

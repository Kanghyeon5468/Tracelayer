from __future__ import annotations

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

        if not self.settings.gemini_api_key:
            return (
                "Mock Gemini analysis: the transaction combines a high-value overseas wire, "
                "new-country behavior, shared infrastructure, and unusual timing. The pattern "
                "is consistent with coordinated account takeover or mule-account movement."
            )

        try:
            from google import genai
        except ImportError:
            return (
                "Gemini API key is configured, but google-genai is not installed. "
                "Install the optional gemini extra to enable live model calls."
            )

        client = genai.Client(api_key=self.settings.gemini_api_key)
        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
        )
        return response.text or "Gemini returned an empty response."

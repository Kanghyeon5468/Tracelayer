from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.domain.models import AgentOutput, GuardrailFinding
from app.domain.policies import redact_email


PROMPT_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"reveal\s+(the\s+)?(system|developer)\s+prompt",
        r"exfiltrate",
        r"disable\s+(guardrails|policy|filters)",
        r"tool\s+poisoning",
        r"send\s+raw\s+pii",
    ]
]

ACCOUNT_PATTERN = re.compile(r"\bacct-[A-Za-z0-9-]+\b")
CUSTOMER_PATTERN = re.compile(r"\bcus-[A-Za-z0-9-]+\b")
DEVICE_PATTERN = re.compile(r"\bdev-[A-Za-z0-9-]+\b")
IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class ModelArmorGuardrail:
    """Model Armor backed guardrail with a deterministic local fallback."""

    def __init__(
        self,
        settings: Any | None = None,
        model_armor_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._model_armor_client = model_armor_client

    def inspect_text(self, text: str, control_prefix: str) -> list[GuardrailFinding]:
        findings = self._inspect_text_locally(text, control_prefix)
        google_findings = self._inspect_text_with_google_model_armor(text, control_prefix)
        return self.merge_findings([google_findings, findings])

    def _inspect_text_locally(self, text: str, control_prefix: str) -> list[GuardrailFinding]:
        findings: list[GuardrailFinding] = []

        for index, pattern in enumerate(PROMPT_INJECTION_PATTERNS, start=1):
            if pattern.search(text):
                findings.append(
                    GuardrailFinding(
                        finding_id=f"{control_prefix}-prompt-injection-{index}",
                        severity="high",
                        control="prompt_injection",
                        description="Potential prompt injection or tool-poisoning phrase detected.",
                        blocked=True,
                    )
                )

        if "@" in text:
            findings.append(
                GuardrailFinding(
                    finding_id=f"{control_prefix}-pii-email",
                    severity="medium",
                    control="pii_detection",
                    description="Email-like PII detected and redaction is required.",
                )
            )

        if ACCOUNT_PATTERN.search(text):
            findings.append(
                GuardrailFinding(
                    finding_id=f"{control_prefix}-account-id",
                    severity="medium",
                    control="pii_detection",
                    description="Account identifier detected and redaction is required.",
                )
            )

        if CUSTOMER_PATTERN.search(text) or DEVICE_PATTERN.search(text):
            findings.append(
                GuardrailFinding(
                    finding_id=f"{control_prefix}-direct-identifier",
                    severity="medium",
                    control="pii_detection",
                    description="Direct customer or device identifier detected and redaction is required.",
                )
            )

        if IP_PATTERN.search(text):
            findings.append(
                GuardrailFinding(
                    finding_id=f"{control_prefix}-ip-address",
                    severity="low",
                    control="sensitive_infrastructure",
                    description="IP address detected and should be limited to authorized viewers.",
                )
            )

        return findings

    def _inspect_text_with_google_model_armor(
        self,
        text: str,
        control_prefix: str,
    ) -> list[GuardrailFinding]:
        if not self._should_use_google_model_armor():
            return []

        try:
            response = self._sanitize_user_prompt(text)
        except Exception as exc:
            blocked = bool(getattr(self.settings, "model_armor_fail_closed", False))
            return [
                GuardrailFinding(
                    finding_id=f"{control_prefix}-google-model-armor-unavailable",
                    severity="high" if blocked else "medium",
                    control="google_model_armor",
                    description=(
                        "Google Cloud Model Armor sanitizeUserPrompt failed; "
                        f"local fallback remained active. Error: {exc}"
                    ),
                    blocked=blocked,
                )
            ]

        payload = self._response_to_dict(response)
        sanitization = payload.get("sanitization_result") or payload.get("sanitizationResult") or {}
        match_state = str(
            sanitization.get("filter_match_state")
            or sanitization.get("filterMatchState")
            or ""
        )
        invocation_result = str(
            sanitization.get("invocation_result")
            or sanitization.get("invocationResult")
            or ""
        )
        matched = self._contains_match_found(sanitization)
        findings = [
            GuardrailFinding(
                finding_id=f"{control_prefix}-google-model-armor-sanitize",
                severity="high" if matched else "low",
                control="google_model_armor",
                description=(
                    "Google Cloud Model Armor sanitizeUserPrompt completed with "
                    f"filter_match_state={match_state or 'unknown'} and "
                    f"invocation_result={invocation_result or 'unknown'}."
                ),
                blocked=matched,
            )
        ]
        findings.extend(
            GuardrailFinding(
                finding_id=f"{control_prefix}-google-model-armor-{name}",
                severity="high",
                control=self._model_armor_control_name(name),
                description=f"Google Cloud Model Armor matched filter: {name}.",
                blocked=True,
            )
            for name in self._matched_filter_names(sanitization)
        )
        return findings

    def _should_use_google_model_armor(self) -> bool:
        return bool(
            self.settings
            and getattr(self.settings, "resolved_model_armor_backend", "local") == "google"
            and getattr(self.settings, "model_armor_template_name", None)
        )

    def _sanitize_user_prompt(self, text: str) -> Any:
        client = self._model_armor_client or self._build_model_armor_client()
        template_name = self.settings.model_armor_template_name
        try:
            from google.cloud import modelarmor_v1
        except ImportError:
            if not self._model_armor_client:
                raise
            request = {
                "name": template_name,
                "user_prompt_data": {"text": text},
            }
        else:
            request = modelarmor_v1.SanitizeUserPromptRequest(
                name=template_name,
                user_prompt_data=modelarmor_v1.DataItem(text=text),
            )
        return client.sanitize_user_prompt(request=request)

    def _build_model_armor_client(self) -> Any:
        from google.api_core.client_options import ClientOptions
        from google.cloud import modelarmor_v1

        return modelarmor_v1.ModelArmorClient(
            transport="rest",
            client_options=ClientOptions(
                api_endpoint=f"modelarmor.{self.settings.model_armor_location}.rep.googleapis.com"
            ),
        )

    @staticmethod
    def _response_to_dict(response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response

        try:
            from google.protobuf.json_format import MessageToDict

            return MessageToDict(response._pb, preserving_proto_field_name=True)
        except Exception:
            pass

        to_dict = getattr(type(response), "to_dict", None)
        if to_dict:
            try:
                return to_dict(response)
            except Exception:
                pass

        return {}

    @classmethod
    def _contains_match_found(cls, value: Any) -> bool:
        if isinstance(value, str):
            return value == "MATCH_FOUND"
        if isinstance(value, dict):
            return any(cls._contains_match_found(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._contains_match_found(item) for item in value)
        return False

    @classmethod
    def _matched_filter_names(cls, sanitization: dict[str, Any]) -> list[str]:
        filters = sanitization.get("filter_results") or sanitization.get("filterResults") or {}
        matched: list[str] = []
        if isinstance(filters, dict):
            for filter_name, result in filters.items():
                if cls._contains_match_found(result):
                    matched.append(str(filter_name).replace("_", "-"))
        elif isinstance(filters, list):
            for index, result in enumerate(filters, start=1):
                if cls._contains_match_found(result):
                    matched.append(f"filter-{index}")
        return sorted(set(matched))

    @staticmethod
    def _model_armor_control_name(filter_name: str) -> str:
        normalized = filter_name.replace("-", "_")
        if "pi_and_jailbreak" in normalized:
            return "prompt_injection"
        if "sdp" in normalized or "pii" in normalized:
            return "pii_detection"
        if "malicious" in normalized:
            return "malicious_uri"
        return "google_model_armor_filter"

    def assert_safe_prompt(self, prompt: str) -> list[GuardrailFinding]:
        findings = self.inspect_text(prompt, "model-input")
        blocking = [finding for finding in findings if finding.blocked]
        if blocking:
            blocked_controls = ", ".join(finding.finding_id for finding in blocking)
            raise ValueError(f"Model input blocked by guardrails: {blocked_controls}")
        return findings

    def sanitize_output(self, output: AgentOutput) -> AgentOutput:
        redacted_summary = self.redact_sensitive_text(output.summary)
        findings = self.inspect_text(output.summary, f"{output.agent_id}-output")
        return output.model_copy(
            update={
                "summary": redacted_summary,
                "guardrail_findings": output.guardrail_findings
                + [finding.finding_id for finding in findings],
            }
        )

    def redact_sensitive_text(self, text: str) -> str:
        redacted = redact_email(text)
        redacted = ACCOUNT_PATTERN.sub("acct-***", redacted)
        redacted = CUSTOMER_PATTERN.sub("cus-***", redacted)
        redacted = DEVICE_PATTERN.sub("dev-***", redacted)
        redacted = IP_PATTERN.sub("ip-***", redacted)
        return redacted

    def merge_findings(self, groups: Iterable[list[GuardrailFinding]]) -> list[GuardrailFinding]:
        merged: dict[str, GuardrailFinding] = {}
        for group in groups:
            for finding in group:
                merged[finding.finding_id] = finding
        return list(merged.values())

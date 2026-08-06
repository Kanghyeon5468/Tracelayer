from __future__ import annotations

import re
from collections.abc import Iterable

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
IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class ModelArmorGuardrail:
    """Local guardrail that mirrors the role of Model Armor in the deployed design."""

    def inspect_text(self, text: str, control_prefix: str) -> list[GuardrailFinding]:
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
        redacted = IP_PATTERN.sub("ip-***", redacted)
        return redacted

    def merge_findings(self, groups: Iterable[list[GuardrailFinding]]) -> list[GuardrailFinding]:
        merged: dict[str, GuardrailFinding] = {}
        for group in groups:
            for finding in group:
                merged[finding.finding_id] = finding
        return list(merged.values())

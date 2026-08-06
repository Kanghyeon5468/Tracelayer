from __future__ import annotations

from app.agents.base import BaseInvestigationAgent
from app.domain.models import (
    AgentIdentity,
    AgentOutput,
    ComplianceFinding,
    InvestigationContext,
    Priority,
)
from app.domain.policies import redact_email, redact_name
from app.security.guardrails import ACCOUNT_PATTERN, IP_PATTERN


class ComplianceAgent(BaseInvestigationAgent):
    required_permissions = ["policies.read", "case.review", "pii.redact"]

    def __init__(self, identity: AgentIdentity) -> None:
        self.identity = identity

    def run(self, context: InvestigationContext) -> AgentOutput:
        findings: list[ComplianceFinding] = []

        redacted_customer_name = redact_name(context.customer.name)
        redacted_email = redact_email(context.trigger_transaction.email)

        if context.priority in {Priority.HIGH, Priority.CRITICAL}:
            findings.append(
                ComplianceFinding(
                    finding_id="cmp-human-approval",
                    severity="high",
                    description="High-risk enforcement actions require human approval.",
                    required_action="Route any account hold or transfer freeze to an authorized reviewer.",
                )
            )

        if context.trigger_transaction.email != redacted_email:
            findings.append(
                ComplianceFinding(
                    finding_id="cmp-pii-redaction",
                    severity="medium",
                    description="PII appears in source records and must be redacted in summaries.",
                    required_action=(
                        f"Use redacted viewer fields: customer={redacted_customer_name}, "
                        f"email={redacted_email}."
                    ),
                )
            )

        evidence_text = " ".join(event.description for event in context.evidence_timeline)
        if ACCOUNT_PATTERN.search(evidence_text) or IP_PATTERN.search(evidence_text):
            findings.append(
                ComplianceFinding(
                    finding_id="cmp-sensitive-evidence",
                    severity="medium",
                    description="Evidence timeline contains account or infrastructure identifiers.",
                    required_action=(
                        "Show raw identifiers only to analysts and supervisors; redact for viewer roles."
                    ),
                )
            )

        context.compliance_findings = findings

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Completed compliance review with {len(findings)} findings. "
                "No autonomous asset freeze is allowed in this workflow."
            ),
            confidence=0.91,
            data={"finding_ids": [finding.finding_id for finding in findings]},
        )
        context.agent_outputs.append(output)
        return output

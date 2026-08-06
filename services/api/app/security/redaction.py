from __future__ import annotations

from app.domain.models import (
    ActorRole,
    AgentOutput,
    ApprovalRequest,
    ComplianceFinding,
    EvidenceEvent,
    InvestigationCase,
)
from app.security.guardrails import ModelArmorGuardrail


def redact_case_for_role(case: InvestigationCase, role: ActorRole) -> InvestigationCase:
    if role != ActorRole.VIEWER:
        return case

    guardrail = ModelArmorGuardrail()
    return case.model_copy(
        update={
            "customer_id": "cus-***",
            "agent_outputs": [
                AgentOutput(
                    agent_id=output.agent_id,
                    summary=guardrail.redact_sensitive_text(output.summary),
                    confidence=output.confidence,
                    data=_redact_mapping(output.data),
                    guardrail_findings=output.guardrail_findings,
                )
                for output in case.agent_outputs
            ],
            "evidence_timeline": [
                EvidenceEvent(
                    timestamp=event.timestamp,
                    event_type=event.event_type,
                    description=guardrail.redact_sensitive_text(event.description),
                    source=event.source,
                    related_transaction_id=event.related_transaction_id,
                )
                for event in case.evidence_timeline
            ],
            "compliance_findings": [
                ComplianceFinding(
                    finding_id=finding.finding_id,
                    severity=finding.severity,
                    description=guardrail.redact_sensitive_text(finding.description),
                    required_action=guardrail.redact_sensitive_text(finding.required_action),
                )
                for finding in case.compliance_findings
            ],
            "approval_request": _redact_approval(case.approval_request, guardrail),
        }
    )


def _redact_mapping(value: dict) -> dict:
    redacted = {}
    guardrail = ModelArmorGuardrail()
    for key, item in value.items():
        if isinstance(item, str):
            redacted[key] = guardrail.redact_sensitive_text(item)
        elif key in {"risk_flags", "policy_excerpt_names", "finding_ids"}:
            redacted[key] = item
        else:
            redacted[key] = item
    return redacted


def _redact_approval(
    approval: ApprovalRequest | None,
    guardrail: ModelArmorGuardrail,
) -> ApprovalRequest | None:
    if not approval:
        return None
    return approval.model_copy(
        update={
            "reason": guardrail.redact_sensitive_text(approval.reason),
            "decision_reason": (
                guardrail.redact_sensitive_text(approval.decision_reason)
                if approval.decision_reason
                else None
            ),
        }
    )

from __future__ import annotations

from app.agents.base import BaseInvestigationAgent
from app.domain.models import (
    AgentIdentity,
    AgentOutput,
    ApprovalRequest,
    CaseStatus,
    InvestigationContext,
    Priority,
)


class CaseManagerAgent(BaseInvestigationAgent):
    required_permissions = ["case.write", "approvals.request", "reports.write"]

    def __init__(self, identity: AgentIdentity) -> None:
        self.identity = identity

    def run(self, context: InvestigationContext) -> AgentOutput:
        if context.priority in {Priority.HIGH, Priority.CRITICAL}:
            context.status = CaseStatus.NEEDS_APPROVAL
            context.approval_request = ApprovalRequest(
                approval_id=f"appr-{context.case_id}",
                action="review_outbound_transfer_hold",
                reason=(
                    "The case contains a high-value overseas transfer with shared "
                    "device or IP signals. A human reviewer must approve any hold."
                ),
            )
        else:
            context.status = CaseStatus.OPEN

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Case moved to {context.status}. "
                "Generated a human approval request for high-risk action."
                if context.approval_request
                else f"Case remains {context.status} for analyst review."
            ),
            confidence=0.9,
            data={
                "case_status": context.status,
                "approval_id": (
                    context.approval_request.approval_id if context.approval_request else None
                ),
            },
        )
        context.agent_outputs.append(output)
        return output

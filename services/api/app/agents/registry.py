from __future__ import annotations

from app.domain.models import AgentIdentity, DataClassification


class AgentRegistry:
    """Enterprise-style catalog for approved agents and their permission scopes."""

    def __init__(self) -> None:
        self._agents = {
            "triage-agent": AgentIdentity(
                agent_id="triage-agent",
                display_name="Triage Agent",
                version="0.1.0",
                service_account="triage-agent@tracelayer.iam",
                permissions=["transactions.read", "risk.score"],
                data_access=[DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED],
            ),
            "network-agent": AgentIdentity(
                agent_id="network-agent",
                display_name="Network Agent",
                version="0.1.0",
                service_account="network-agent@tracelayer.iam",
                permissions=["transactions.read", "graph.search"],
                data_access=[DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED],
            ),
            "evidence-agent": AgentIdentity(
                agent_id="evidence-agent",
                display_name="Evidence Agent",
                version="0.1.0",
                service_account="evidence-agent@tracelayer.iam",
                permissions=["transactions.read", "policies.read", "evidence.write"],
                data_access=[
                    DataClassification.INTERNAL,
                    DataClassification.CONFIDENTIAL,
                    DataClassification.RESTRICTED,
                ],
            ),
            "compliance-agent": AgentIdentity(
                agent_id="compliance-agent",
                display_name="Compliance Agent",
                version="0.1.0",
                service_account="compliance-agent@tracelayer.iam",
                permissions=["policies.read", "case.review", "pii.redact"],
                data_access=[
                    DataClassification.INTERNAL,
                    DataClassification.CONFIDENTIAL,
                    DataClassification.RESTRICTED,
                ],
            ),
            "case-manager-agent": AgentIdentity(
                agent_id="case-manager-agent",
                display_name="Case Manager Agent",
                version="0.1.0",
                service_account="case-manager-agent@tracelayer.iam",
                permissions=["case.write", "approvals.request", "reports.write"],
                data_access=[DataClassification.CONFIDENTIAL],
            ),
        }

    def get(self, agent_id: str) -> AgentIdentity:
        return self._agents[agent_id]

    def list_agents(self) -> list[AgentIdentity]:
        return list(self._agents.values())

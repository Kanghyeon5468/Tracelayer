from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import AgentIdentity, DataClassification


class AgentRegistry:
    """Enterprise-style catalog for approved agents and their permission scopes."""

    def __init__(
        self,
        project_id: str | None = None,
        region: str = "us-central1",
        service_url: str | None = None,
    ) -> None:
        self.project_id = project_id or "project-6ecbea1e-e0c3-4325-a63"
        self.region = region
        self.service_url = (service_url or "").rstrip("/")
        self.updated_at = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
        self._agents = {
            "triage-agent": AgentIdentity(
                agent_id="triage-agent",
                display_name="Triage Agent",
                version="1.2.0",
                service_account=self._service_account("tracelayer-triage-agent"),
                permissions=["transactions.read", "bigquery.transactions.read", "risk.score"],
                data_access=[DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED],
                owner_department="Fraud Risk",
                lifecycle_status="approved",
                approved_version="1.2.0",
                deployed_runtime="cloud-run-google-adk-runner",
                allowed_tools=[
                    "score_transaction",
                    "compute_federated_intelligence",
                    "bigquery_read_transactions",
                ],
                data_region=self.region,
                registry_resource=self._registry_resource("tracelayer-triage-agent"),
                agent_principal=self._agent_principal("tracelayer-triage-agent"),
                managed_gateway_policy="enforced-bigquery-read-only",
                health_status="healthy",
                last_updated=self.updated_at,
            ),
            "network-agent": AgentIdentity(
                agent_id="network-agent",
                display_name="Network Agent",
                version="1.1.0",
                service_account=self._service_account("tracelayer-network-agent"),
                permissions=["transactions.read", "bigquery.transactions.read", "graph.search"],
                data_access=[DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED],
                owner_department="Fraud Intelligence",
                lifecycle_status="approved",
                approved_version="1.1.0",
                deployed_runtime="cloud-run-google-adk-runner",
                allowed_tools=["search_related_transactions", "trace_cluster_funds"],
                data_region=self.region,
                registry_resource=self._registry_resource("tracelayer-network-agent"),
                agent_principal=self._agent_principal("tracelayer-network-agent"),
                managed_gateway_policy="enforced-network-search",
                health_status="healthy",
                last_updated=self.updated_at,
            ),
            "evidence-agent": AgentIdentity(
                agent_id="evidence-agent",
                display_name="Evidence Agent",
                version="1.0.3",
                service_account=self._service_account("tracelayer-evidence-agent"),
                permissions=["transactions.read", "policies.read", "evidence.write"],
                data_access=[
                    DataClassification.INTERNAL,
                    DataClassification.CONFIDENTIAL,
                    DataClassification.RESTRICTED,
                ],
                owner_department="Investigations",
                lifecycle_status="approved",
                approved_version="1.0.3",
                deployed_runtime="cloud-run-python-tool",
                allowed_tools=["build_evidence_timeline"],
                data_region=self.region,
                registry_resource=self._registry_resource("tracelayer-evidence-agent"),
                agent_principal=self._agent_principal("tracelayer-evidence-agent"),
                managed_gateway_policy="audit-only-evidence-write",
                health_status="healthy",
                last_updated=self.updated_at,
            ),
            "compliance-agent": AgentIdentity(
                agent_id="compliance-agent",
                display_name="Compliance Agent",
                version="1.3.0",
                service_account=self._service_account("tracelayer-compliance-agent"),
                permissions=["policies.read", "case.review", "pii.redact", "audit.read"],
                data_access=[
                    DataClassification.INTERNAL,
                    DataClassification.CONFIDENTIAL,
                    DataClassification.RESTRICTED,
                ],
                owner_department="Compliance",
                lifecycle_status="approved",
                approved_version="1.3.0",
                deployed_runtime="cloud-run-python-tool",
                allowed_tools=["check_policy_and_pii", "redact_case_view", "read_audit_chain"],
                data_region=self.region,
                registry_resource=self._registry_resource("tracelayer-compliance-agent"),
                agent_principal=self._agent_principal("tracelayer-compliance-agent"),
                managed_gateway_policy="enforced-no-bigquery-read",
                health_status="healthy",
                last_updated=self.updated_at,
            ),
            "case-manager-agent": AgentIdentity(
                agent_id="case-manager-agent",
                display_name="Case Manager Agent",
                version="1.4.0",
                service_account=self._service_account("tracelayer-case-manager-agent"),
                permissions=["case.write", "approvals.request", "reports.write"],
                data_access=[DataClassification.CONFIDENTIAL],
                owner_department="Case Operations",
                lifecycle_status="approved",
                approved_version="1.4.0",
                deployed_runtime="google-adk-runner-session",
                allowed_tools=[
                    "create_investigation_plan",
                    "replan_after_feedback",
                    "request_supervisor_approval",
                    "resume_paused_case",
                ],
                data_region=self.region,
                registry_resource=self._registry_resource("tracelayer-case-manager-agent"),
                agent_principal=self._agent_principal("tracelayer-case-manager-agent"),
                managed_gateway_policy="enforced-approval-boundary",
                health_status="healthy",
                last_updated=self.updated_at,
            ),
        }

    def get(self, agent_id: str) -> AgentIdentity:
        return self._agents[agent_id]

    def list_agents(self) -> list[AgentIdentity]:
        return list(self._agents.values())

    def search(self, query: str) -> list[AgentIdentity]:
        normalized = query.lower().strip()
        if not normalized:
            return self.list_agents()
        return [
            agent
            for agent in self.list_agents()
            if normalized
            in " ".join(
                [
                    agent.agent_id,
                    agent.display_name,
                    agent.owner_department,
                    agent.lifecycle_status,
                    agent.deployed_runtime,
                    agent.managed_gateway_policy,
                    *agent.permissions,
                    *agent.allowed_tools,
                    *(str(access) for access in agent.data_access),
                ]
            ).lower()
        ]

    def a2a_agent_card(self, agent_id: str) -> dict:
        agent = self.get(agent_id)
        endpoint = (
            f"{self.service_url}/agents/{agent.agent_id}/invoke"
            if self.service_url
            else f"https://SERVICE_URL/agents/{agent.agent_id}/invoke"
        )
        return {
            "schemaVersion": "v1",
            "name": agent.agent_id,
            "displayName": agent.display_name,
            "description": (
                f"{agent.display_name} for TraceLayer fraud investigations. "
                f"Owner: {agent.owner_department}. Lifecycle: {agent.lifecycle_status}."
            ),
            "url": endpoint,
            "version": agent.version,
            "provider": {"organization": "TraceLayer", "url": self.service_url or endpoint},
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": True,
            },
            "metadata": {
                "registry_resource": agent.registry_resource,
                "agent_principal": agent.agent_principal,
                "service_account": agent.service_account,
                "data_region": agent.data_region,
                "managed_gateway_policy": agent.managed_gateway_policy,
                "deployed_runtime": agent.deployed_runtime,
            },
            "skills": [
                {
                    "id": tool,
                    "name": tool.replace("_", " ").title(),
                    "description": f"Approved TraceLayer tool exposed by {agent.display_name}.",
                    "tags": [agent.owner_department, agent.data_region, "fraud-investigation"],
                }
                for tool in agent.allowed_tools
            ],
        }

    def registry_bootstrap_manifest(self) -> dict:
        triage_card = (
            f"{self.service_url}/a2a/triage-agent/agent-card.json"
            if self.service_url
            else "https://SERVICE_URL/a2a/triage-agent/agent-card.json"
        )
        return {
            "registry": {
                "project": self.project_id,
                "location": self.region,
                "service_id": "tracelayer-triage-agent",
                "display_name": "TraceLayer Triage Agent",
                "agent_card_url": triage_card,
            },
            "gcloud_register_triage_agent": (
                f"curl -s {triage_card} > /tmp/tracelayer-triage-agent-card.json && "
                "gcloud agent-registry services create tracelayer-triage-agent "
                f"--project={self.project_id} --location={self.region} "
                '--display-name="TraceLayer Triage Agent" '
                "--agent-spec-type=a2a-agent-card "
                "--agent-spec-content=@/tmp/tracelayer-triage-agent-card.json"
            ),
            "iam_intent": [
                {
                    "principal": self.get("triage-agent").service_account,
                    "allowed": ["roles/bigquery.dataViewer on fraud_investigations"],
                    "denied": ["case approval write", "raw compliance audit mutation"],
                },
                {
                    "principal": self.get("compliance-agent").service_account,
                    "allowed": ["policies.read", "pii.redact", "audit.read"],
                    "denied": ["bigquery.transactions.read", "graph.search"],
                },
            ],
            "gateway_layers": [
                "Google managed Agent Gateway: network and IAM egress enforcement",
                "TraceLayer AgentGateway: fraud-specific tool, data-classification, Model Armor, and audit policy",
            ],
        }

    def _service_account(self, name: str) -> str:
        return f"{name}@{self.project_id}.iam.gserviceaccount.com"

    def _registry_resource(self, service_id: str) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.region}/services/{service_id}"
        )

    def _agent_principal(self, service_id: str) -> str:
        return (
            "principal://agents.global.org-demo.system.id.goog/resources/"
            f"run/projects/{self.project_id}/locations/{self.region}/services/{service_id}"
        )

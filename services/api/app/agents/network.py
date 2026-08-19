from __future__ import annotations

from collections import Counter
from typing import Any

from app.adk_runtime import AdkAgentRuntime
from app.agents.base import BaseInvestigationAgent
from app.connectors.bigquery_network import BigQueryNetworkSearch
from app.domain.models import AgentIdentity, AgentOutput, InvestigationContext, NetworkLink, Transaction


class NetworkAgent(BaseInvestigationAgent):
    required_permissions = ["transactions.read", "graph.search"]

    def __init__(
        self,
        identity: AgentIdentity,
        network_search: BigQueryNetworkSearch,
        adk_runtime: AdkAgentRuntime | None = None,
    ) -> None:
        self.identity = identity
        self.network_search = network_search
        self.adk_runtime = adk_runtime

    def run(self, context: InvestigationContext) -> AgentOutput:
        trigger = context.trigger_transaction
        network_result = self.network_search.find_related_transactions(trigger)
        context.related_transactions = network_result.transactions
        context.network_search_metadata = network_result.metadata
        links: list[NetworkLink] = []

        for transaction in context.related_transactions:
            comparisons = {
                "shared_account": transaction.account_id == trigger.account_id,
                "shared_counterparty": (
                    transaction.counterparty_account_id == trigger.counterparty_account_id
                ),
                "shared_device": transaction.device_id == trigger.device_id,
                "shared_ip": transaction.ip_address == trigger.ip_address,
                "shared_email": transaction.email == trigger.email,
            }
            for relationship, matched in comparisons.items():
                if matched:
                    links.append(
                        NetworkLink(
                            source=trigger.transaction_id,
                            target=transaction.transaction_id,
                            relationship=relationship,
                            evidence_transaction_id=transaction.transaction_id,
                        )
                    )

        context.network_links = links
        network_graph = self._build_network_graph(trigger, context.related_transactions, links)
        campaign_detection = self._detect_campaign(context, links)

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Found {len(links)} network links across "
                f"{len(context.related_transactions)} related transactions via "
                f"{context.network_search_metadata.get('backend', 'unknown')} search. "
                f"Campaign status: {campaign_detection['status']}."
            ),
            confidence=0.82,
            data={
                "link_count": len(links),
                "relationships": sorted({link.relationship for link in links}),
                "search": context.network_search_metadata,
                "network_graph": network_graph,
                "campaign_detection": campaign_detection,
                "adk_runtime": self._adk_binding(),
            },
        )
        context.agent_outputs.append(output)
        return output

    def _build_network_graph(
        self,
        trigger: Transaction,
        related_transactions: list[Transaction],
        links: list[NetworkLink],
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {
            trigger.transaction_id: {
                "id": trigger.transaction_id,
                "label": trigger.transaction_id,
                "type": "trigger_transaction",
                "risk": "high",
            }
        }
        edges: list[dict[str, Any]] = []
        related_by_id = {transaction.transaction_id: transaction for transaction in related_transactions}

        for transaction in related_transactions:
            nodes[transaction.transaction_id] = {
                "id": transaction.transaction_id,
                "label": transaction.transaction_id,
                "type": "related_transaction",
                "risk": "medium" if transaction.status == "flagged" else "low",
            }

        for link in links:
            related = related_by_id.get(link.target)
            if not related:
                continue
            entity_id, entity_label, entity_type = self._entity_for_relationship(
                link.relationship,
                trigger,
                related,
            )
            nodes[entity_id] = {
                "id": entity_id,
                "label": entity_label,
                "type": entity_type,
                "risk": "shared",
            }
            edges.append(
                {
                    "source": trigger.transaction_id,
                    "target": entity_id,
                    "relationship": link.relationship,
                    "strength": 1.0,
                }
            )
            edges.append(
                {
                    "source": entity_id,
                    "target": related.transaction_id,
                    "relationship": link.relationship,
                    "strength": 0.82,
                }
            )

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "layout": "radial_shared_infrastructure",
            "updated_at_source": "network-agent",
        }

    def _detect_campaign(
        self,
        context: InvestigationContext,
        links: list[NetworkLink],
    ) -> dict[str, Any]:
        relationship_counts = Counter(link.relationship for link in links)
        related_count = len(context.related_transactions)
        shared_infrastructure_count = (
            relationship_counts["shared_device"]
            + relationship_counts["shared_ip"]
            + relationship_counts["shared_email"]
        )
        federated_score = (
            context.federated_risk_signal.federated_risk_score
            if context.federated_risk_signal
            else 0
        )
        campaign_signature = (
            context.federated_risk_signal.campaign_signature
            if context.federated_risk_signal
            else "local-only"
        )
        detected = (
            related_count >= 2
            and len(links) >= 3
            and (shared_infrastructure_count >= 2 or federated_score >= 75)
        )
        severity = self._campaign_severity(
            detected,
            len(links),
            shared_infrastructure_count,
            federated_score,
        )
        confidence = self._campaign_confidence(
            detected,
            len(links),
            related_count,
            shared_infrastructure_count,
            federated_score,
        )

        return {
            "detected": detected,
            "status": "campaign_detected" if detected else "no_campaign_detected",
            "campaign_id": f"camp-{campaign_signature[-12:]}",
            "campaign_signature": campaign_signature,
            "severity": severity,
            "confidence": confidence,
            "linked_transaction_count": related_count,
            "network_link_count": len(links),
            "shared_infrastructure_count": shared_infrastructure_count,
            "relationship_counts": dict(sorted(relationship_counts.items())),
            "pattern": self._campaign_pattern(relationship_counts, federated_score),
            "recommended_action": (
                "Escalate for supervisor review and monitor connected accounts before any hold."
                if detected
                else "Continue planned investigation without campaign escalation."
            ),
        }

    @staticmethod
    def _entity_for_relationship(
        relationship: str,
        trigger: Transaction,
        related: Transaction,
    ) -> tuple[str, str, str]:
        value_by_relationship = {
            "shared_account": trigger.account_id,
            "shared_counterparty": trigger.counterparty_account_id,
            "shared_device": trigger.device_id,
            "shared_ip": trigger.ip_address,
            "shared_email": trigger.email,
        }
        value = value_by_relationship.get(relationship, related.transaction_id)
        if relationship == "shared_email":
            return ("email:cluster", "Shared Email Cluster", "email")
        return (f"{relationship}:{value}", value, relationship.replace("shared_", ""))

    @staticmethod
    def _campaign_severity(
        detected: bool,
        link_count: int,
        shared_infrastructure_count: int,
        federated_score: int,
    ) -> str:
        if not detected:
            return "none"
        if federated_score >= 85 and link_count >= 6:
            return "critical"
        if federated_score >= 75 or shared_infrastructure_count >= 4:
            return "high"
        return "medium"

    @staticmethod
    def _campaign_confidence(
        detected: bool,
        link_count: int,
        related_count: int,
        shared_infrastructure_count: int,
        federated_score: int,
    ) -> float:
        if not detected:
            return 0.35
        score = (
            0.42
            + min(link_count, 10) * 0.035
            + min(related_count, 6) * 0.025
            + min(shared_infrastructure_count, 6) * 0.03
            + min(federated_score, 100) * 0.0012
        )
        return round(min(score, 0.96), 2)

    @staticmethod
    def _campaign_pattern(relationship_counts: Counter[str], federated_score: int) -> str:
        if relationship_counts["shared_device"] and relationship_counts["shared_ip"]:
            return "Shared device and IP cluster across related transactions"
        if relationship_counts["shared_counterparty"]:
            return "Repeated counterparty pattern across connected transactions"
        if federated_score >= 75:
            return "Federated campaign signature with local network corroboration"
        return "Insufficient campaign pattern"

    def _adk_binding(self) -> dict:
        if not self.adk_runtime:
            return {"enabled": False, "available": False, "framework": "google_adk"}
        return self.adk_runtime.bind_agent(
            self.identity,
            description="Discovers account, device, IP, email, and counterparty links.",
            instruction=(
                "You are TraceLayer's Network Agent. Use approved related-transaction "
                "search tools to find connected accounts, devices, IP addresses, emails, "
                "and counterparties without exposing unnecessary PII."
            ),
        ).as_dict()

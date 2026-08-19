from __future__ import annotations

from app.agents.base import BaseInvestigationAgent
from app.connectors.bigquery_network import BigQueryNetworkSearch
from app.domain.models import AgentIdentity, AgentOutput, InvestigationContext, NetworkLink


class NetworkAgent(BaseInvestigationAgent):
    required_permissions = ["transactions.read", "graph.search"]

    def __init__(self, identity: AgentIdentity, network_search: BigQueryNetworkSearch) -> None:
        self.identity = identity
        self.network_search = network_search

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

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Found {len(links)} network links across "
                f"{len(context.related_transactions)} related transactions via "
                f"{context.network_search_metadata.get('backend', 'unknown')} search."
            ),
            confidence=0.82,
            data={
                "link_count": len(links),
                "relationships": sorted({link.relationship for link in links}),
                "search": context.network_search_metadata,
            },
        )
        context.agent_outputs.append(output)
        return output

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from app.connectors.repository import InvestigationRepository
from app.domain.models import Transaction


@dataclass(frozen=True)
class NetworkSearchResult:
    transactions: list[Transaction]
    metadata: dict[str, Any]


class BigQueryNetworkSearch:
    """Searches related transactions in BigQuery, with local data fallback for demos."""

    def __init__(
        self,
        settings: Settings,
        repository: InvestigationRepository,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.client = client

    def find_related_transactions(self, transaction: Transaction) -> NetworkSearchResult:
        if self.settings.network_search_backend == "local":
            return self._local_result(transaction, "local_repository")

        if self.settings.network_search_backend in {"auto", "bigquery"}:
            result = self._try_bigquery(transaction)
            if result:
                return result

        return self._local_result(transaction, "local_repository_fallback")

    def _try_bigquery(self, transaction: Transaction) -> NetworkSearchResult | None:
        if not self.settings.google_cloud_project:
            return None

        try:
            client = self.client or self._build_client()
            rows = client.query(
                self._query(),
                job_config=self._job_config(transaction),
            ).result()
        except Exception as exc:
            if self.settings.network_search_backend == "bigquery":
                raise RuntimeError(f"BigQuery network search failed: {exc}") from exc
            return None

        transactions = [self._row_to_transaction(row) for row in rows]
        return NetworkSearchResult(
            transactions=sorted(transactions, key=lambda item: item.timestamp),
            metadata={
                "backend": "bigquery",
                "table": self.settings.bigquery_transactions_table,
                "query_shape": "shared_account_counterparty_device_ip_email_hash",
                "result_count": len(transactions),
            },
        )

    def _local_result(self, transaction: Transaction, backend: str) -> NetworkSearchResult:
        transactions = self.repository.find_related_transactions(transaction)
        return NetworkSearchResult(
            transactions=transactions,
            metadata={
                "backend": backend,
                "table": "data/transactions.json",
                "query_shape": "shared_account_counterparty_device_ip_email",
                "result_count": len(transactions),
            },
        )

    def _query(self) -> str:
        table = self.settings.bigquery_transactions_table
        return f"""
        SELECT
          transaction_id,
          customer_id,
          account_id,
          counterparty_account_id,
          amount,
          currency,
          country,
          channel,
          device_id,
          ip_address,
          email_hash,
          event_timestamp,
          status,
          risk_flags
        FROM `{table}`
        WHERE transaction_id != @transaction_id
          AND (
            account_id = @account_id
            OR counterparty_account_id = @counterparty_account_id
            OR device_id = @device_id
            OR ip_address = @ip_address
            OR email_hash = @email_hash
          )
        ORDER BY event_timestamp ASC
        LIMIT @limit
        """

    def _job_config(self, transaction: Transaction):
        from google.cloud import bigquery

        return bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "transaction_id", "STRING", transaction.transaction_id
                ),
                bigquery.ScalarQueryParameter("account_id", "STRING", transaction.account_id),
                bigquery.ScalarQueryParameter(
                    "counterparty_account_id", "STRING", transaction.counterparty_account_id
                ),
                bigquery.ScalarQueryParameter("device_id", "STRING", transaction.device_id),
                bigquery.ScalarQueryParameter("ip_address", "STRING", transaction.ip_address),
                bigquery.ScalarQueryParameter("email_hash", "STRING", self._hash_email(transaction.email)),
                bigquery.ScalarQueryParameter("limit", "INT64", self.settings.network_search_limit),
            ]
        )

    def _row_to_transaction(self, row: Any) -> Transaction:
        return Transaction(
            transaction_id=row.transaction_id,
            customer_id=row.customer_id,
            account_id=row.account_id,
            counterparty_account_id=row.counterparty_account_id,
            amount=float(row.amount),
            currency=row.currency,
            country=row.country,
            channel=row.channel,
            device_id=row.device_id or "",
            ip_address=row.ip_address or "",
            email=f"hash:{row.email_hash}" if row.email_hash else "",
            timestamp=self._parse_timestamp(row.event_timestamp),
            status=row.status,
            risk_flags=list(row.risk_flags or []),
        )

    @staticmethod
    def _hash_email(email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _build_client():
        from google.cloud import bigquery

        return bigquery.Client()

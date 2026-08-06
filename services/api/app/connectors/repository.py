from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import Customer, Transaction


class InvestigationRepository:
    """Repository boundary for Firestore, Cloud SQL, or BigQuery replacement later."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or self._default_data_dir()
        self._transactions = self._load_transactions()
        self._customers = self._load_customers()

    def get_transaction(self, transaction_id: str) -> Transaction:
        for transaction in self._transactions:
            if transaction.transaction_id == transaction_id:
                return transaction
        raise KeyError(f"Transaction not found: {transaction_id}")

    def get_customer(self, customer_id: str) -> Customer:
        for customer in self._customers:
            if customer.customer_id == customer_id:
                return customer
        raise KeyError(f"Customer not found: {customer_id}")

    def find_related_transactions(self, transaction: Transaction) -> list[Transaction]:
        related: list[Transaction] = []
        for candidate in self._transactions:
            if candidate.transaction_id == transaction.transaction_id:
                continue

            has_shared_signal = any(
                [
                    candidate.account_id == transaction.account_id,
                    candidate.counterparty_account_id == transaction.counterparty_account_id,
                    candidate.device_id == transaction.device_id,
                    candidate.ip_address == transaction.ip_address,
                    candidate.email == transaction.email,
                ]
            )
            if has_shared_signal:
                related.append(candidate)

        return sorted(related, key=lambda item: item.timestamp)

    def read_policy_text(self) -> str:
        return (self.data_dir / "policies.md").read_text(encoding="utf-8")

    def _load_transactions(self) -> list[Transaction]:
        payload = json.loads((self.data_dir / "transactions.json").read_text(encoding="utf-8"))
        return [Transaction.model_validate(item) for item in payload]

    def _load_customers(self) -> list[Customer]:
        payload = json.loads((self.data_dir / "customers.json").read_text(encoding="utf-8"))
        return [Customer.model_validate(item) for item in payload]

    @staticmethod
    def _default_data_dir() -> Path:
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data"
            if candidate.exists():
                return candidate

        container_data = Path("/data")
        if container_data.exists():
            return container_data

        raise FileNotFoundError("Could not locate the TraceLayer data directory.")

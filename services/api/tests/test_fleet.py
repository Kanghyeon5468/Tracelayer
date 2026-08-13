from pathlib import Path

from app.config import Settings
from app.connectors.repository import InvestigationRepository
from app.connectors.report_writer import ReportWriter
import app.fleet as fleet_module
from app.fleet import FraudInvestigationFleet
from app.federation.secure_agg import secure_aggregate
from app.memory.job_store import LocalInvestigationJobStore
from app.memory.memory_bank import FirestoreMemoryBank, MemoryBank
from app.observability.audit import AuditLedger
from app.domain.models import ActorRole, ApprovalDecisionRequest, RequestContext
from app.security.redaction import redact_case_for_role


def test_demo_case_requires_human_approval() -> None:
    fleet = _test_fleet(Path("/tmp/tracelayer-test-default"))

    case = fleet.investigate("tx-9001")

    assert case.status == "needs_approval"
    assert case.priority in {"high", "critical"}
    assert case.risk_score >= 70
    assert case.approval_request is not None
    assert case.federated_risk_signal is not None
    assert case.federated_risk_signal.model_family == "veritas_embedded_federated_fraud_v1"
    assert case.federated_risk_signal.secure_aggregation["client_count"] == 3
    assert len(case.network_links) >= 1
    assert len(case.evidence_timeline) >= 1
    assert case.audit_chain_tip is not None
    assert case.memory_snapshot_id is not None
    assert fleet.audit_ledger.verify_chain()


def test_demo_runs_can_create_distinct_case_records(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)

    first_case = fleet.investigate("tx-9001", create_case_run=True)
    second_case = fleet.investigate("tx-9001", create_case_run=True)
    approval_log = fleet.list_approval_log()

    assert first_case.case_id.startswith("case-tx-9001-")
    assert second_case.case_id.startswith("case-tx-9001-")
    assert first_case.case_id != second_case.case_id
    assert {entry.case_id for entry in approval_log} == {
        first_case.case_id,
        second_case.case_id,
    }


def test_random_demo_uses_flagged_demo_transactions(tmp_path: Path, monkeypatch) -> None:
    fleet = _test_fleet(tmp_path)
    demo_ids = InvestigationRepository().list_demo_transaction_ids()

    assert {
        "tx-9001",
        "tx-9101",
        "tx-9201",
        "tx-9301",
        "tx-9401",
        "tx-9501",
        "tx-9601",
    }.issubset(set(demo_ids))

    monkeypatch.setattr(fleet_module.random, "choice", lambda values: "tx-9201")
    case = fleet.investigate_random_demo()

    assert case.trigger_transaction_id == "tx-9201"
    assert case.case_id.startswith("case-tx-9201-")
    assert case.approval_request is not None
    assert case.risk_score >= 70


def test_random_demo_avoids_recent_demo_repeats(tmp_path: Path, monkeypatch) -> None:
    fleet = _test_fleet(tmp_path)
    candidate_sets: list[list[str]] = []

    def choose_first(values: list[str]) -> str:
        candidate_sets.append(list(values))
        return values[0]

    monkeypatch.setattr(fleet_module.random, "choice", choose_first)

    first_case = fleet.investigate_random_demo()
    second_case = fleet.investigate_random_demo()
    third_case = fleet.investigate_random_demo()

    assert first_case.trigger_transaction_id == "tx-9001"
    assert second_case.trigger_transaction_id == "tx-9101"
    assert third_case.trigger_transaction_id == "tx-9201"
    assert candidate_sets == [
        ["tx-9001", "tx-9101", "tx-9201", "tx-9301", "tx-9401", "tx-9501", "tx-9601"],
        ["tx-9101", "tx-9201", "tx-9301", "tx-9401", "tx-9501", "tx-9601"],
        ["tx-9201", "tx-9301", "tx-9401", "tx-9501", "tx-9601"],
    ]


def test_demo_scenarios_cover_risk_priority_range(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    results = {
        transaction_id: fleet.investigate(transaction_id, create_case_run=True)
        for transaction_id in InvestigationRepository().list_demo_transaction_ids()
    }

    priorities = {case.priority for case in results.values()}

    assert {"low", "medium", "high", "critical"}.issubset(priorities)
    assert results["tx-9301"].risk_score < 40
    assert results["tx-9401"].priority == "medium"
    assert results["tx-9501"].priority == "medium"
    assert results["tx-9601"].priority == "high"
    assert results["tx-9301"].approval_request is None
    assert results["tx-9401"].approval_request is not None
    assert results["tx-9401"].approval_request.action == "manual_case_review"
    assert results["tx-9501"].approval_request is not None
    assert results["tx-9501"].approval_request.action == "manual_case_review"
    assert results["tx-9601"].approval_request is not None


def test_network_agent_records_search_backend_metadata(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)

    case = fleet.investigate("tx-9001")
    network_output = next(
        output for output in case.agent_outputs if output.agent_id == "network-agent"
    )

    assert network_output.data["search"]["backend"] == "local_repository"
    assert network_output.data["search"]["result_count"] >= 1


def test_async_demo_job_persists_status_and_case_id(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)

    job = fleet.enqueue_random_demo()
    assert job.status == "queued"
    assert job.pubsub_message_id.startswith("local-pubsub-")

    finished_job = fleet.run_investigation_job(job.job_id)
    loaded_job = fleet.get_job(job.job_id)

    assert finished_job.status == "succeeded"
    assert finished_job.case_id is not None
    assert loaded_job is not None
    assert loaded_job.case_id == finished_job.case_id


def test_viewer_cannot_start_investigation(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    viewer = RequestContext(
        actor_id="viewer@example.com",
        role=ActorRole.VIEWER,
        request_id="req-test-viewer",
    )

    try:
        fleet.investigate("tx-9001", viewer)
    except PermissionError as exc:
        assert "does not have cases.investigate" in str(exc)
    else:
        raise AssertionError("Viewer role should not be able to start an investigation.")


def test_supervisor_can_decide_approval(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    supervisor = RequestContext(
        actor_id="supervisor@example.com",
        role=ActorRole.SUPERVISOR,
        request_id="req-test-supervisor",
    )

    case = fleet.investigate("tx-9001", supervisor)
    assert case.approval_request is not None

    decided_case = fleet.decide_approval(
        case.case_id,
        ApprovalDecisionRequest(
            approval_id=case.approval_request.approval_id,
            decision="approved",
            reason="Demo reviewer approved a temporary outbound transfer hold.",
        ),
        supervisor,
    )

    assert decided_case.status == "closed"
    assert decided_case.approval_request is not None
    assert decided_case.approval_request.status == "approved"
    assert decided_case.approval_request.decided_by == "supervisor@example.com"
    assert fleet.audit_ledger.verify_chain()


def test_supervisor_can_list_pending_approvals(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    supervisor = RequestContext(
        actor_id="supervisor@example.com",
        role=ActorRole.SUPERVISOR,
        request_id="req-test-supervisor-pending",
    )

    case = fleet.investigate("tx-9001", supervisor)
    pending = fleet.list_pending_approvals(supervisor)

    assert len(pending) == 1
    assert pending[0].case_id == case.case_id
    assert pending[0].approval_id == "appr-case-tx-9001"
    assert pending[0].risk_score == case.risk_score


def test_approval_decision_removes_case_from_pending_list(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    supervisor = RequestContext(
        actor_id="supervisor@example.com",
        role=ActorRole.SUPERVISOR,
        request_id="req-test-supervisor-deny",
    )

    case = fleet.investigate("tx-9001", supervisor)
    assert fleet.list_pending_approvals(supervisor)

    fleet.decide_approval(
        case.case_id,
        ApprovalDecisionRequest(
            approval_id=case.approval_request.approval_id,
            decision="denied",
            reason="Reviewer denied the hold for test coverage.",
        ),
        supervisor,
    )

    assert fleet.list_pending_approvals(supervisor) == []


def test_approval_log_retains_approved_and_denied_decisions(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    supervisor = RequestContext(
        actor_id="supervisor@example.com",
        role=ActorRole.SUPERVISOR,
        request_id="req-test-supervisor-history",
    )

    approved_case = fleet.investigate("tx-9001", supervisor, create_case_run=True)
    denied_case = fleet.investigate("tx-9001", supervisor, create_case_run=True)

    fleet.decide_approval(
        approved_case.case_id,
        ApprovalDecisionRequest(
            approval_id=approved_case.approval_request.approval_id,
            decision="approved",
            reason="Approved in history test.",
        ),
        supervisor,
    )
    fleet.decide_approval(
        denied_case.case_id,
        ApprovalDecisionRequest(
            approval_id=denied_case.approval_request.approval_id,
            decision="denied",
            reason="Denied in history test.",
        ),
        supervisor,
    )

    log_by_case = {entry.case_id: entry for entry in fleet.list_approval_log(supervisor)}

    assert log_by_case[approved_case.case_id].approval_status == "approved"
    assert log_by_case[approved_case.case_id].case_status == "closed"
    assert log_by_case[denied_case.case_id].approval_status == "denied"
    assert log_by_case[denied_case.case_id].case_status == "open"


def test_viewer_case_response_is_redacted(tmp_path: Path) -> None:
    fleet = _test_fleet(tmp_path)
    case = fleet.investigate("tx-9001")

    redacted = redact_case_for_role(case, ActorRole.VIEWER)
    redacted_json = redacted.model_dump_json()

    assert redacted.customer_id == "cus-***"
    assert "acct-7781" not in redacted_json
    assert "203.0.113.74" not in redacted_json


def test_embedded_secure_aggregation_recovers_sum() -> None:
    updates = {
        "bank-a": [1.0, 2.0, 3.0],
        "bank-b": [4.0, 5.0, 6.0],
        "bank-c": [7.0, 8.0, 9.0],
    }

    aggregate, metadata = secure_aggregate(updates, session_id="test-session")

    assert [round(value, 6) for value in aggregate] == [12.0, 15.0, 18.0]
    assert metadata["protocol"] == "bonawitz_pairwise_masking_reference"
    assert metadata["server_observes"] == "masked_node_updates_and_aggregate_only"


def test_firestore_memory_bank_saves_and_loads_case(tmp_path: Path) -> None:
    settings = Settings(
        google_cloud_project="demo-project",
        firestore_case_collection="test_cases",
    )
    fleet = _test_fleet(tmp_path)
    case = fleet.investigate("tx-9001")
    firestore_memory = FirestoreMemoryBank(settings, client=FakeFirestoreClient())

    snapshot_id = firestore_memory.save_case(case)
    loaded_case = firestore_memory.load_case(case.case_id)

    assert loaded_case is not None
    assert snapshot_id.startswith("mem-")
    assert loaded_case.case_id == case.case_id
    assert loaded_case.memory_snapshot_id == snapshot_id
    assert loaded_case.approval_request is not None


def _test_fleet(tmp_path: Path) -> FraudInvestigationFleet:
    settings = Settings(network_search_backend="local")
    return FraudInvestigationFleet(
        settings,
        report_writer=ReportWriter(tmp_path / "reports"),
        memory_bank=MemoryBank(settings, tmp_path / "memory.jsonl"),
        job_store=LocalInvestigationJobStore(settings, tmp_path / "jobs.jsonl"),
        audit_ledger=AuditLedger(settings, tmp_path / "audit.jsonl"),
    )


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollectionRef] = {}

    def collection(self, name: str) -> "FakeCollectionRef":
        if name not in self.collections:
            self.collections[name] = FakeCollectionRef()
        return self.collections[name]


class FakeCollectionRef:
    def __init__(self) -> None:
        self.documents: dict[str, FakeDocumentRef] = {}

    def document(self, document_id: str) -> "FakeDocumentRef":
        if document_id not in self.documents:
            self.documents[document_id] = FakeDocumentRef()
        return self.documents[document_id]

    def where(self, field: str, operator: str, value: str) -> "FakeQuery":
        return FakeQuery(self.documents.values(), field, operator, value)

    def stream(self):
        for document in self.documents.values():
            if document.payload is not None:
                yield FakeSnapshot(document.payload)


class FakeDocumentRef:
    def __init__(self) -> None:
        self.payload: dict | None = None
        self.collections: dict[str, FakeCollectionRef] = {}

    def set(self, payload: dict, merge: bool = False) -> None:
        if merge and self.payload:
            self.payload.update(payload)
            return
        self.payload = payload.copy()

    def get(self) -> "FakeSnapshot":
        return FakeSnapshot(self.payload)

    def collection(self, name: str) -> FakeCollectionRef:
        if name not in self.collections:
            self.collections[name] = FakeCollectionRef()
        return self.collections[name]


class FakeSnapshot:
    def __init__(self, payload: dict | None) -> None:
        self.payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict | None:
        return self.payload.copy() if self.payload else None


class FakeQuery:
    def __init__(
        self,
        documents,
        field: str,
        operator: str,
        value: str,
    ) -> None:
        self.documents = documents
        self.field = field
        self.operator = operator
        self.value = value

    def stream(self):
        for document in self.documents:
            payload = document.payload or {}
            if self.operator == "==" and payload.get(self.field) == self.value:
                yield FakeSnapshot(payload)

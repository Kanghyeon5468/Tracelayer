from pathlib import Path

from app.config import Settings
from app.connectors.report_writer import ReportWriter
from app.fleet import FraudInvestigationFleet
from app.federation.secure_agg import secure_aggregate
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
    settings = Settings()
    return FraudInvestigationFleet(
        settings,
        report_writer=ReportWriter(tmp_path / "reports"),
        memory_bank=MemoryBank(settings, tmp_path / "memory.jsonl"),
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

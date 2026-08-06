from __future__ import annotations

from pathlib import Path

from app.domain.models import InvestigationCase


class ReportWriter:
    """Writes an audit-friendly Markdown report that can later be rendered to PDF."""

    def __init__(self, report_dir: Path | None = None) -> None:
        self.report_dir = report_dir or self._default_report_dir()
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def write_markdown(self, case: InvestigationCase) -> Path:
        path = self.path_for(case.case_id)
        lines = [
            f"# Investigation Report: {case.case_id}",
            "",
            f"- Status: {case.status}",
            f"- Trigger Transaction: {case.trigger_transaction_id}",
            f"- Customer ID: {case.customer_id}",
            f"- Risk Score: {case.risk_score}",
            f"- Priority: {case.priority}",
            f"- Memory Snapshot: {case.memory_snapshot_id or 'pending'}",
            f"- Audit Chain Tip: {case.audit_chain_tip or 'pending'}",
            "",
            "## Agent Findings",
        ]

        for output in case.agent_outputs:
            lines.extend(
                [
                    f"### {output.agent_id}",
                    "",
                    output.summary,
                    "",
                    f"Confidence: {output.confidence:.2f}",
                    "",
                ]
            )

        lines.append("## Embedded Veritas Federated Signal")
        if case.federated_risk_signal:
            signal = case.federated_risk_signal
            lines.extend(
                [
                    f"- Signal ID: {signal.signal_id}",
                    f"- Model Family: {signal.model_family}",
                    f"- Federated Risk Score: {signal.federated_risk_score}",
                    f"- Campaign Signature: {signal.campaign_signature}",
                    f"- Participating Nodes: {', '.join(signal.participating_nodes)}",
                    f"- DP Epsilon: {signal.differential_privacy.get('epsilon')}",
                    f"- DP Delta: {signal.differential_privacy.get('delta')}",
                    f"- Secure Aggregation: {signal.secure_aggregation.get('protocol')}",
                    f"- Provenance Hash: {signal.provenance_hash}",
                    "",
                    signal.explanation,
                    "",
                ]
            )
        else:
            lines.extend(["- No federated risk signal was attached.", ""])

        lines.append("## Evidence Timeline")
        for event in case.evidence_timeline:
            lines.append(
                f"- {event.timestamp.isoformat()} | {event.event_type} | {event.description}"
            )

        lines.extend(["", "## Compliance Findings"])
        for finding in case.compliance_findings:
            lines.append(
                f"- {finding.severity.upper()} | {finding.description} | "
                f"Action: {finding.required_action}"
            )

        lines.extend(["", "## Guardrail Findings"])
        if case.guardrail_findings:
            for finding in case.guardrail_findings:
                lines.append(
                    f"- {finding.severity.upper()} | {finding.control} | "
                    f"{finding.description} | Blocked: {finding.blocked}"
                )
        else:
            lines.append("- No guardrail findings were recorded.")

        if case.approval_request:
            lines.extend(
                [
                    "",
                    "## Human Approval",
                    f"- Approval ID: {case.approval_request.approval_id}",
                    f"- Action: {case.approval_request.action}",
                    f"- Reason: {case.approval_request.reason}",
                    f"- Status: {case.approval_request.status}",
                ]
            )

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def path_for(self, case_id: str) -> Path:
        return self.report_dir / f"{case_id}.md"

    @staticmethod
    def _default_report_dir() -> Path:
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data"
            if candidate.exists():
                return candidate / "reports"

        container_data = Path("/data")
        if container_data.exists():
            return container_data / "reports"

        raise FileNotFoundError("Could not locate a report output directory.")

const fallbackCase = {
  case_id: "case-tx-9001",
  status: "needs_approval",
  trigger_transaction_id: "tx-9001",
  customer_id: "cus-1042",
  risk_score: 90,
  priority: "critical",
  agent_outputs: [
    {
      agent_id: "triage-agent",
      summary:
        "Assigned critical priority with risk score 90. The transfer combines high amount, overseas destination, unusual timing, and shared infrastructure.",
      confidence: 0.86,
    },
    {
      agent_id: "network-agent",
      summary: "Found links across shared device, IP address, and counterparty account.",
      confidence: 0.82,
    },
    {
      agent_id: "evidence-agent",
      summary: "Built a chronological timeline and matched it against internal policy.",
      confidence: 0.88,
    },
    {
      agent_id: "compliance-agent",
      summary: "Detected PII handling requirements and blocked autonomous asset freeze.",
      confidence: 0.91,
    },
    {
      agent_id: "case-manager-agent",
      summary: "Created a human approval request for outbound transfer hold review.",
      confidence: 0.9,
    },
  ],
  network_links: [
    {
      source: "tx-9001",
      target: "tx-8997",
      relationship: "shared_device",
      evidence_transaction_id: "tx-8997",
    },
    {
      source: "tx-9001",
      target: "tx-8997",
      relationship: "shared_ip",
      evidence_transaction_id: "tx-8997",
    },
    {
      source: "tx-9001",
      target: "tx-8997",
      relationship: "shared_counterparty",
      evidence_transaction_id: "tx-8997",
    },
  ],
  evidence_timeline: [
    {
      timestamp: "2026-08-05T23:51:00Z",
      event_type: "related_transaction",
      description: "Related wire transfer used the same device, IP, and foreign counterparty.",
    },
    {
      timestamp: "2026-08-06T02:14:00Z",
      event_type: "trigger_transaction",
      description: "Flagged overseas wire transfer for 18500.00 USD to SG.",
    },
    {
      timestamp: "2026-08-06T02:43:00Z",
      event_type: "related_transaction",
      description: "Related pending ACH activity reused the same device and IP.",
    },
  ],
  compliance_findings: [
    {
      finding_id: "cmp-human-approval",
      severity: "high",
      description: "High-risk enforcement actions require human approval.",
      required_action: "Route any account hold to an authorized reviewer.",
    },
    {
      finding_id: "cmp-pii-redaction",
      severity: "medium",
      description: "PII appears in source records and must be redacted in summaries.",
      required_action: "Use redacted viewer fields.",
    },
  ],
  approval_request: {
    approval_id: "appr-case-tx-9001",
    action: "review_outbound_transfer_hold",
    reason: "High-value overseas transfer with shared device or IP signals.",
    status: "pending",
  },
  guardrail_findings: [
    {
      finding_id: "model-input-pii-email",
      severity: "medium",
      control: "pii_detection",
      description: "Email-like PII detected and redaction is required.",
      blocked: false,
    },
    {
      finding_id: "model-input-account-id",
      severity: "medium",
      control: "pii_detection",
      description: "Account identifier detected and redaction is required.",
      blocked: false,
    },
  ],
  federated_risk_signal: {
    signal_id: "veritas-tx-9001",
    model_family: "veritas_embedded_federated_fraud_v1",
    federated_risk_score: 86,
    campaign_signature: "vfsi-demo9001",
    participating_nodes: ["bank-na-01", "insurer-claims-02", "fintech-wallet-03"],
    secure_aggregation: {
      protocol: "bonawitz_pairwise_masking_reference",
      client_count: 3,
    },
    differential_privacy: {
      epsilon: 3.41,
      delta: 0.00001,
    },
    provenance_hash: "demo-provenance",
    explanation:
      "Embedded Veritas federation combined privacy-preserving node updates without moving raw customer records.",
    node_indicators: ["bank:cross_border_signal", "fintech:device_cluster_overlap"],
  },
  audit_chain_tip: "demo-audit-chain-tip",
  memory_snapshot_id: "demo-memory-snapshot",
};

const inferredApiBaseUrl = window.location.protocol.startsWith("http")
  ? window.location.origin
  : "http://localhost:8080";

const API_BASE_URL =
  window.TRACELAYER_API_BASE ||
  localStorage.getItem("tracelayer.apiBaseUrl") ||
  inferredApiBaseUrl;

const titleCase = (value) =>
  String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const renderCase = (caseData) => {
  document.querySelector("#case-id").textContent = caseData.case_id;
  document.querySelector("#case-status").textContent = titleCase(caseData.status);
  document.querySelector("#risk-score").textContent = caseData.risk_score;
  document.querySelector("#priority").textContent = titleCase(caseData.priority);
  document.querySelector("#audit-tip").textContent = caseData.audit_chain_tip ? "Recorded" : "Pending";

  document.querySelector("#agent-findings").innerHTML = caseData.agent_outputs
    .map(
      (item) => `
        <div class="item">
          <strong>${titleCase(item.agent_id)}</strong>
          <p>${item.summary}</p>
        </div>
      `,
    )
    .join("");

  document.querySelector("#network-links").innerHTML = caseData.network_links
    .map(
      (item) => `
        <div class="item">
          <strong>${titleCase(item.relationship)}</strong>
          <p>${item.source} -> ${item.target}</p>
        </div>
      `,
    )
    .join("");

  const signal = caseData.federated_risk_signal;
  document.querySelector("#federated-signal").innerHTML = signal
    ? `
      <div class="metric">
        <span>Risk</span>
        <strong>${signal.federated_risk_score}/100</strong>
      </div>
      <div class="metric">
        <span>Campaign</span>
        <strong>${signal.campaign_signature}</strong>
      </div>
      <div class="metric">
        <span>DP Epsilon</span>
        <strong>${signal.differential_privacy.epsilon}</strong>
      </div>
      <div class="metric">
        <span>Nodes</span>
        <strong>${signal.participating_nodes.length}</strong>
      </div>
    `
    : '<div class="item"><strong>No signal</strong><p>No federated signal was attached.</p></div>';

  document.querySelector("#timeline").innerHTML = caseData.evidence_timeline
    .map(
      (item) => `
        <div class="event">
          <time>${new Date(item.timestamp).toLocaleString()}</time>
          <div>
            <strong>${titleCase(item.event_type)}</strong>
            <p>${item.description}</p>
          </div>
        </div>
      `,
    )
    .join("");

  document.querySelector("#compliance").innerHTML = caseData.compliance_findings
    .map(
      (item) => `
        <div class="item">
          <strong>${titleCase(item.severity)}: ${item.finding_id}</strong>
          <p>${item.description} ${item.required_action}</p>
        </div>
      `,
    )
    .join("");

  const guardrailItems = caseData.guardrail_findings || [];
  document.querySelector("#guardrails").innerHTML = guardrailItems.length
    ? guardrailItems
        .map(
          (item) => `
        <div class="item">
          <strong>${titleCase(item.severity)}: ${titleCase(item.control)}</strong>
          <p>${item.description} Blocked: ${item.blocked}</p>
        </div>
      `,
        )
        .join("")
    : '<div class="item"><strong>No findings</strong><p>No guardrail findings were recorded.</p></div>';

  const approval = caseData.approval_request;
  document.querySelector("#approval").innerHTML = approval
    ? `
      <strong>${titleCase(approval.status)}</strong>
      <p>${titleCase(approval.action)}</p>
      <p>${approval.reason}</p>
    `
    : "<p>No approval request has been created.</p>";
};

const loadRuntimeConfig = async () => {
  const status = document.querySelector("#runtime-status");
  try {
    const response = await fetch(`${API_BASE_URL}/runtime/config`);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const config = await response.json();
    status.textContent = `Backend: ${config.ai_provider} / ${config.gemini_model}`;
  } catch (error) {
    status.textContent = "Backend: local fallback";
  }
};

const runDemo = async () => {
  const button = document.querySelector("#run-demo");
  button.disabled = true;
  button.textContent = "Running...";

  try {
    const response = await fetch(`${API_BASE_URL}/cases/demo`, { method: "POST" });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    renderCase(await response.json());
  } catch (error) {
    renderCase(fallbackCase);
  } finally {
    button.disabled = false;
    button.textContent = "Run Demo Case";
  }
};

document.querySelector("#run-demo").addEventListener("click", runDemo);
renderCase(fallbackCase);
loadRuntimeConfig();

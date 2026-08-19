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
  investigation_plan: {
    plan_id: "plan-case-tx-9001",
    strategy: "deep_network_investigation",
    rationale:
      "High-risk cases require network discovery, evidence collection, compliance review, and supervisor approval.",
    created_by_agent_id: "case-manager-agent",
    steps: [
      {
        step_id: "triage",
        agent_id: "triage-agent",
        action: "score_transaction",
        reason: "Score and classify every flagged transaction.",
        status: "completed",
      },
      {
        step_id: "network",
        agent_id: "network-agent",
        action: "search_related_transactions",
        reason: "Find shared accounts, devices, IPs, emails, and counterparties.",
        status: "completed",
      },
      {
        step_id: "evidence",
        agent_id: "evidence-agent",
        action: "build_evidence_timeline",
        reason: "Build timeline from trigger, network, and federated evidence.",
        status: "completed",
      },
      {
        step_id: "approval",
        agent_id: "case-manager-agent",
        action: "request_supervisor_approval",
        reason: "Require supervisor approval before any outbound hold.",
        status: "completed",
      },
    ],
  },
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

let currentCaseId = localStorage.getItem("tracelayer.currentCaseId") || fallbackCase.case_id;
let runtimeConfig = { pubsub_backend: "local" };
const liveChannel = "BroadcastChannel" in window ? new BroadcastChannel("tracelayer-live") : null;

const titleCase = (value) =>
  String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const renderAdkRuntime = (runtime) => {
  if (!runtime) {
    return "";
  }
  const label = runtime.available ? "Google ADK" : "Local agent fallback";
  const model = runtime.model ? ` · ${runtime.model}` : "";
  const agent = runtime.agent_name ? ` · ${runtime.agent_name}` : "";
  return `<p class="muted-line">Runtime: ${label}${model}${agent}</p>`;
};

const renderModelArmorDemo = (demo) => {
  if (!demo?.external_input_present) {
    return "";
  }
  const state = demo.blocked ? "Prompt Injection Blocked" : "External Input Cleared";
  return `
    <div class="armor-callout ${demo.blocked ? "blocked" : ""}">
      <strong>${state}</strong>
      <p>External instruction blocked: ${demo.prompt_injection_detected}</p>
      <p>PII access denied: ${demo.pii_access_denied}</p>
      <p>Investigation continued: ${demo.investigation_continued}</p>
    </div>
  `;
};

const getNetworkOutput = (caseData) =>
  caseData.agent_outputs?.find((output) => output.agent_id === "network-agent");

const graphNodeClass = (type) => {
  if (type === "trigger_transaction") {
    return "trigger";
  }
  if (type === "related_transaction") {
    return "related";
  }
  return "entity";
};

const renderNetworkGraph = (graph) => {
  if (!graph?.nodes?.length) {
    return `
      <div class="item">
        <strong>No graph generated</strong>
        <p>This investigation plan did not run network discovery.</p>
      </div>
    `;
  }

  const width = 920;
  const height = 360;
  const center = { x: 460, y: 180 };
  const nodes = graph.nodes.slice(0, 18);
  const positioned = new Map();
  const trigger = nodes.find((node) => node.type === "trigger_transaction") || nodes[0];
  positioned.set(trigger.id, { ...trigger, x: center.x, y: center.y });

  const ringNodes = nodes.filter((node) => node.id !== trigger.id);
  ringNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(ringNodes.length, 1) - Math.PI / 2;
    const radius = node.type === "related_transaction" ? 132 : 98;
    positioned.set(node.id, {
      ...node,
      x: Math.round(center.x + Math.cos(angle) * radius),
      y: Math.round(center.y + Math.sin(angle) * radius),
    });
  });

  const edgeMarkup = (graph.edges || [])
    .filter((edge) => positioned.has(edge.source) && positioned.has(edge.target))
    .slice(0, 36)
    .map((edge) => {
      const source = positioned.get(edge.source);
      const target = positioned.get(edge.target);
      return `
        <line
          class="graph-edge"
          x1="${source.x}"
          y1="${source.y}"
          x2="${target.x}"
          y2="${target.y}"
        />
      `;
    })
    .join("");

  const nodeMarkup = [...positioned.values()]
    .map(
      (node) => `
        <g class="graph-node ${graphNodeClass(node.type)}" transform="translate(${node.x}, ${node.y})">
          <circle r="${node.type === "trigger_transaction" ? 24 : 18}"></circle>
          <text y="${node.type === "trigger_transaction" ? 42 : 34}">${node.label}</text>
        </g>
      `,
    )
    .join("");

  return `
    <svg class="network-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Live fraud network graph">
      ${edgeMarkup}
      ${nodeMarkup}
    </svg>
    <div class="graph-legend">
      <span><i class="legend-dot trigger"></i>Trigger</span>
      <span><i class="legend-dot related"></i>Related Transaction</span>
      <span><i class="legend-dot entity"></i>Shared Entity</span>
      <span>${nodes.length} nodes · ${(graph.edges || []).length} edges · ${titleCase(graph.layout)}</span>
    </div>
  `;
};

const renderCampaignDetection = (campaign) => {
  if (!campaign) {
    return `
      <div class="item">
        <strong>No campaign analysis</strong>
        <p>This investigation plan did not run the Network Agent.</p>
      </div>
    `;
  }
  const detected = campaign.detected;
  const relationshipRows = Object.entries(campaign.relationship_counts || {})
    .map(([relationship, count]) => `<span class="chip">${titleCase(relationship)} ${count}</span>`)
    .join("");

  return `
    <div class="campaign-card ${detected ? "detected" : ""}">
      <div>
        <span class="campaign-status">${detected ? "Campaign Detected" : "No Campaign Detected"}</span>
        <strong>${titleCase(campaign.pattern)}</strong>
        <p>${campaign.recommended_action}</p>
      </div>
      <div class="campaign-metrics">
        <div><span>Severity</span><strong>${titleCase(campaign.severity)}</strong></div>
        <div><span>Confidence</span><strong>${Math.round((campaign.confidence || 0) * 100)}%</strong></div>
        <div><span>Linked Transactions</span><strong>${campaign.linked_transaction_count}</strong></div>
        <div><span>Network Links</span><strong>${campaign.network_link_count}</strong></div>
      </div>
      <div class="chip-row">
        <span class="chip">${campaign.campaign_id}</span>
        <span class="chip">${campaign.campaign_signature}</span>
        ${relationshipRows}
      </div>
    </div>
  `;
};

const apiHeaders = () => {
  const headers = {
    "X-Tracelayer-User": localStorage.getItem("tracelayer.supervisorId") || "supervisor@example.com",
    "X-Tracelayer-Role": "supervisor",
  };
  const apiKey = localStorage.getItem("tracelayer.apiKey");
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  return headers;
};

const setLiveStatus = (message) => {
  const status = document.querySelector("#runtime-status");
  if (!status) {
    return;
  }
  status.dataset.liveStatus = message;
  if (status.textContent.includes("Backend:")) {
    const backend = status.dataset.backendStatus || status.textContent.split(" · ")[0];
    status.textContent = `${backend} · ${message}`;
  }
};

const publishCaseUpdate = (caseData, source) => {
  const event = {
    type: "case.updated",
    source,
    case: caseData,
    sent_at: new Date().toISOString(),
  };
  liveChannel?.postMessage(event);
  localStorage.setItem("tracelayer.liveCaseEvent", JSON.stringify(event));
};

const applyLiveCaseUpdate = (caseData) => {
  if (!caseData) {
    return;
  }
  renderCase(caseData);
  setLiveStatus(`Live sync: ${new Date().toLocaleTimeString()}`);
};

const renderAsyncJob = (job) => {
  document.querySelector("#async-job").innerHTML = `
    <div class="item">
      <strong>${titleCase(job.status)}</strong>
      <p>${job.job_id}</p>
      <p>Transaction: ${job.transaction_id || "pending"} · Topic: ${job.pubsub_topic}</p>
      <p>Message: ${job.pubsub_message_id}</p>
      ${job.case_id ? `<p>Case: ${job.case_id}</p>` : ""}
      ${job.error ? `<p>Error: ${job.error}</p>` : ""}
    </div>
  `;
};

const renderAgentRegistry = (agents) => {
  document.querySelector("#agent-registry").innerHTML = agents
    .map(
      (agent) => `
        <article class="registry-card">
          <header>
            <h3>${agent.display_name}</h3>
            <span class="chip">${agent.version}</span>
          </header>
          <code>${agent.service_account}</code>
          <div class="chip-row">
            ${agent.permissions.map((permission) => `<span class="chip">${permission}</span>`).join("")}
          </div>
          <div class="chip-row">
            ${agent.data_access.map((access) => `<span class="chip">${titleCase(access)}</span>`).join("")}
          </div>
        </article>
      `,
    )
    .join("");
};

const renderCase = (caseData) => {
  currentCaseId = caseData.case_id;
  localStorage.setItem("tracelayer.currentCaseId", currentCaseId);

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
          ${renderModelArmorDemo(item.data?.model_armor_demo)}
          ${renderAdkRuntime(item.data?.adk_runtime)}
        </div>
      `,
    )
    .join("");

  const plan = caseData.investigation_plan;
  document.querySelector("#investigation-plan").innerHTML = plan
    ? `
      <div class="item">
        <strong>${titleCase(plan.strategy)}</strong>
        <p>${plan.rationale}</p>
        <p>Created by ${titleCase(plan.created_by_agent_id)} after adaptive case review.</p>
      </div>
      ${plan.steps
        .map(
          (step) => `
        <div class="item">
          <strong>${titleCase(step.status)}: ${titleCase(step.agent_id)}</strong>
          <p>${titleCase(step.action)} · ${step.reason}</p>
        </div>
      `,
        )
        .join("")}
    `
    : '<div class="item"><strong>No plan</strong><p>No dynamic plan was attached.</p></div>';

  document.querySelector("#network-links").innerHTML = caseData.network_links
    .map(
      (item) => `
        <div class="item">
          <strong>${titleCase(item.relationship)}</strong>
          <p>${item.source} -> ${item.target}</p>
        </div>
      `,
    )
    .join("") || '<div class="item"><strong>No links searched</strong><p>This plan did not run network discovery.</p></div>';

  const networkOutput = getNetworkOutput(caseData);
  document.querySelector("#network-graph").innerHTML = renderNetworkGraph(
    networkOutput?.data?.network_graph,
  );
  document.querySelector("#campaign-detection").innerHTML = renderCampaignDetection(
    networkOutput?.data?.campaign_detection,
  );

  const signal = caseData.federated_risk_signal;
  const linkCount = caseData.network_links?.length || 0;
  const evidenceCount = caseData.evidence_timeline?.length || 0;
  const topPattern = signal?.node_indicators?.[0]
    ? titleCase(signal.node_indicators[0].split(":").pop())
    : "No External Pattern";
  document.querySelector("#federated-signal").innerHTML = signal
    ? `
      <div class="federated-section">
        <h3>Federated Intelligence</h3>
        <div class="metric-grid">
          <div class="metric">
            <span>Risk Score</span>
            <strong>${signal.federated_risk_score}%</strong>
          </div>
          <div class="metric">
            <span>Pattern</span>
            <strong>${topPattern}</strong>
          </div>
          <div class="metric">
            <span>Confidence</span>
            <strong>${signal.federated_risk_score >= 80 ? "High" : "Medium"}</strong>
          </div>
          <div class="metric">
            <span>Contributing Orgs</span>
            <strong>${signal.participating_nodes.length}</strong>
          </div>
          <div class="metric privacy-metric">
            <span>External Customer Records Exposed</span>
            <strong>0</strong>
          </div>
          <div class="metric">
            <span>DP Epsilon</span>
            <strong>${signal.differential_privacy.epsilon}</strong>
          </div>
        </div>
        <div class="privacy-list">
          <div><strong>Secure Aggregation</strong><p>${titleCase(signal.secure_aggregation.server_observes)}</p></div>
          <div><strong>Provenance</strong><p>${signal.provenance_hash.slice(0, 16)}...</p></div>
          <div><strong>Campaign</strong><p>${signal.campaign_signature}</p></div>
        </div>
      </div>
      <div class="federated-section local-evidence">
        <h3>Local Investigation Evidence</h3>
        <div class="privacy-list">
          <div><strong>Network Links</strong><p>${linkCount} local graph links found by TraceLayer.</p></div>
          <div><strong>Timeline Events</strong><p>${evidenceCount} events built from local records and safe federated signal metadata.</p></div>
          <div><strong>Raw External Records</strong><p>Not received, stored, or displayed.</p></div>
        </div>
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
      ${
        approval.decision_reason
          ? `<p><strong>Decision reason</strong> ${approval.decision_reason}</p>`
          : ""
      }
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
    runtimeConfig = config;
    const live = status.dataset.liveStatus || "Live sync: ready";
    const adk = config.adk_available ? "Google ADK" : "local agent runtime";
    const pubsub = config.pubsub_backend === "google" ? "Pub/Sub push" : "local worker";
    status.dataset.backendStatus = `Backend: ${config.ai_provider} / ${config.gemini_model} · ${adk} · ${pubsub}`;
    status.textContent = `${status.dataset.backendStatus} · ${live}`;
  } catch (error) {
    status.textContent = "Backend: local fallback";
  }
};

const runDemo = async () => {
  const button = document.querySelector("#run-demo");
  button.disabled = true;
  button.textContent = "Running...";

  try {
    const response = await fetch(`${API_BASE_URL}/cases/demo`, {
      method: "POST",
      headers: apiHeaders(),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const caseData = await response.json();
    renderCase(caseData);
    publishCaseUpdate(caseData, "dashboard.run_demo");
  } catch (error) {
    renderCase(fallbackCase);
  } finally {
    button.disabled = false;
    button.textContent = "Run Demo Case";
  }
};

const runAttackDemo = async () => {
  const button = document.querySelector("#run-attack-demo");
  button.disabled = true;
  button.textContent = "Attacking...";

  try {
    const response = await fetch(`${API_BASE_URL}/cases/investigate`, {
      method: "POST",
      headers: {
        ...apiHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ transaction_id: "tx-9701" }),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const caseData = await response.json();
    renderCase(caseData);
    publishCaseUpdate(caseData, "dashboard.attack_demo");
  } catch (error) {
    renderCase(fallbackCase);
  } finally {
    button.disabled = false;
    button.textContent = "Run Attack Demo";
  }
};

const pollJob = async (jobId) => {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`, {
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API returned ${response.status}`);
  }
  const job = await response.json();
  renderAsyncJob(job);
  if (job.status === "succeeded" && job.case_id) {
    const caseResponse = await fetch(`${API_BASE_URL}/cases/${job.case_id}`, {
      headers: apiHeaders(),
    });
    if (caseResponse.ok) {
      const caseData = await caseResponse.json();
      renderCase(caseData);
      publishCaseUpdate(caseData, "dashboard.async_demo");
    }
    return;
  }
  if (job.status === "failed") {
    return;
  }
  window.setTimeout(() => pollJob(jobId).catch(() => {}), 1200);
};

const runQueuedJob = async (jobId) => {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}/run`, {
    method: "POST",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API returned ${response.status}`);
  }
  const job = await response.json();
  renderAsyncJob(job);
  if (job.status === "succeeded" && job.case_id) {
    const caseResponse = await fetch(`${API_BASE_URL}/cases/${job.case_id}`, {
      headers: apiHeaders(),
    });
    if (caseResponse.ok) {
      const caseData = await caseResponse.json();
      renderCase(caseData);
      publishCaseUpdate(caseData, "dashboard.async_demo");
    }
  }
};

const runAsyncDemo = async () => {
  const button = document.querySelector("#run-async-demo");
  button.disabled = true;
  button.textContent = "Queued...";

  try {
    const response = await fetch(`${API_BASE_URL}/cases/demo/async`, {
      method: "POST",
      headers: apiHeaders(),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const job = await response.json();
    renderAsyncJob(job);
    if (runtimeConfig.pubsub_backend === "google") {
      pollJob(job.job_id).catch(() => {});
    } else {
      runQueuedJob(job.job_id)
        .then(() => pollJob(job.job_id))
        .catch(() => pollJob(job.job_id).catch(() => {}));
    }
  } catch (error) {
    renderAsyncJob({
      job_id: "local-fallback",
      status: "failed",
      transaction_id: null,
      pubsub_topic: "unavailable",
      pubsub_message_id: "unavailable",
      error: "Async endpoint unavailable.",
    });
  } finally {
    button.disabled = false;
    button.textContent = "Run Async Demo";
  }
};

const loadAgentRegistry = async () => {
  try {
    const response = await fetch(`${API_BASE_URL}/agents`, {
      headers: apiHeaders(),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    renderAgentRegistry(await response.json());
  } catch (error) {
    document.querySelector("#agent-registry").innerHTML =
      '<div class="item"><strong>Registry unavailable</strong><p>Agent identities could not be loaded.</p></div>';
  }
};

const loadCurrentCase = async () => {
  try {
    const response = await fetch(`${API_BASE_URL}/cases/${currentCaseId}`, {
      headers: apiHeaders(),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    renderCase(await response.json());
  } catch (error) {
    renderCase(fallbackCase);
  }
};

liveChannel?.addEventListener("message", (event) => {
  if (event.data?.type === "case.updated") {
    applyLiveCaseUpdate(event.data.case);
  }
});

window.addEventListener("storage", (event) => {
  if (event.key !== "tracelayer.liveCaseEvent" || !event.newValue) {
    return;
  }
  try {
    const liveEvent = JSON.parse(event.newValue);
    if (liveEvent.type === "case.updated") {
      applyLiveCaseUpdate(liveEvent.case);
    }
  } catch (error) {
    setLiveStatus("Live sync: event skipped");
  }
});

document.querySelector("#run-demo").addEventListener("click", runDemo);
document.querySelector("#run-attack-demo").addEventListener("click", runAttackDemo);
document.querySelector("#run-async-demo").addEventListener("click", runAsyncDemo);
renderCase(fallbackCase);
loadRuntimeConfig();
loadAgentRegistry();
loadCurrentCase();

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
// BroadcastChannel lets the dashboard and admin page share approval updates live.
const liveChannel = "BroadcastChannel" in window ? new BroadcastChannel("tracelayer-live") : null;
let threeModulePromise = null;
let networkGraph3dState = null;
let networkGraphRenderToken = 0;
let registryAgents = [];

const titleCase = (value) =>
  String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const conciseSummary = (value, limit = 118) => {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  const firstSentence = normalized.match(/^.*?[.!?](\s|$)/)?.[0]?.trim() || normalized;
  return firstSentence.length > limit ? `${firstSentence.slice(0, limit - 3)}...` : firstSentence;
};

const renderAdkRuntime = (runtime) => {
  if (!runtime) {
    return "";
  }
  const label = runtime.execution_mode === "adk_runner"
    ? "Google ADK Runner"
    : runtime.available
      ? "Google ADK"
      : "Local agent fallback";
  const model = runtime.model ? ` · ${runtime.model}` : "";
  const agent = runtime.agent_name ? ` · ${runtime.agent_name}` : "";
  const tool = runtime.tool_name ? ` · tool ${runtime.tool_name}` : "";
  const session = runtime.session_id ? ` · session ${runtime.session_id}` : "";
  return `<p class="muted-line">Runtime: ${label}${model}${agent}${tool}${session}</p>`;
};

const renderPlannerRuntime = (runtime) => {
  if (!runtime) {
    return "";
  }
  const state = runtime.gemini_proposal_used ? "Gemini plan accepted" : "Policy fallback";
  const source = runtime.proposal_source ? ` · ${runtime.proposal_source}` : "";
  const validation = runtime.validation_status ? ` · ${titleCase(runtime.validation_status)}` : "";
  const fallback = runtime.fallback_strategy ? ` · fallback ${titleCase(runtime.fallback_strategy)}` : "";
  return `<p class="muted-line">Planner: ${state}${source}${validation}${fallback}</p>`;
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

const nodeTone = (type) => {
  if (type === "trigger_transaction") {
    return "trigger";
  }
  if (type === "related_transaction") {
    return "related";
  }
  return "entity";
};

const loadThree = () => {
  if (!threeModulePromise) {
    threeModulePromise = import("./vendor/three.module.min.js");
  }
  return threeModulePromise;
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

  const nodes = graph.nodes.slice(0, 18);
  const edgeCount = (graph.edges || []).length;
  return `
    <div class="network-graph-stage">
      <div class="network-graph-viewport" aria-label="Interactive 3D fraud network graph"></div>
      <aside class="graph-selection">
        <span>Selected Node</span>
        <strong>Network Overview</strong>
        <p>${nodes.length} nodes · ${edgeCount} edges · Live shared graph</p>
      </aside>
      <div class="graph-legend">
        <span><i class="legend-dot account"></i>Account</span>
        <span><i class="legend-dot device"></i>Device</span>
        <span><i class="legend-dot merchant"></i>Merchant</span>
        <span><i class="legend-dot exchange"></i>Exchange</span>
        <span><i class="legend-line transaction"></i>Transaction</span>
      </div>
      <div class="fraud-map-controls" aria-label="3D graph controls">
        <button class="secondary-action graph-reset" type="button">□</button>
        <button class="secondary-action graph-zoom-out" type="button">−</button>
        <button class="secondary-action graph-zoom-in" type="button">+</button>
      </div>
    </div>
  `;
};

const handleFraudMapControlClick = (event) => {
  const button = event.target.closest("[data-map-control]");
  if (!button) {
    return;
  }
  const map = button.closest(".fraud-map");
  const svg = map?.querySelector(".fraud-map-svg");
  if (!svg) {
    return;
  }

  const action = button.dataset.mapControl;
  const original = [0, 0, 1000, 500];
  const current = (svg.getAttribute("viewBox") || original.join(" "))
    .split(/\s+/)
    .map(Number);
  if (action === "reset" || current.length !== 4 || current.some(Number.isNaN)) {
    svg.setAttribute("viewBox", original.join(" "));
    return;
  }

  const scale = action === "zoom-in" ? 0.86 : 1.16;
  const [x, y, width, height] = current;
  const nextWidth = Math.min(1000, Math.max(560, width * scale));
  const nextHeight = Math.min(500, Math.max(280, height * scale));
  const centerX = x + width / 2;
  const centerY = y + height / 2;
  const nextX = Math.min(Math.max(0, centerX - nextWidth / 2), 1000 - nextWidth);
  const nextY = Math.min(Math.max(0, centerY - nextHeight / 2), 500 - nextHeight);
  svg.setAttribute("viewBox", `${nextX} ${nextY} ${nextWidth} ${nextHeight}`);
};

const positionFraudMapNodes = (nodes) => {
  const trigger = nodes.find((node) => node.type === "trigger_transaction") || nodes[0];
  const related = nodes.filter((node) => node.type === "related_transaction" && node.id !== trigger.id);
  const entities = nodes.filter((node) => node.type !== "related_transaction" && node.id !== trigger.id);
  const hub =
    entities.find((node) => ["device", "ip", "email"].includes(node.type)) ||
    entities[0];
  const rightEntities = entities.filter((node) => node.id !== hub?.id);
  const positioned = [];

  if (trigger) {
    positioned.push({ ...trigger, x: 118, y: 230, kind: "account" });
  }
  if (hub) {
    positioned.push({ ...hub, x: 265, y: 220, kind: graphNodeKind(hub) });
  }

  const relatedSlots = [
    { x: 410, y: 88 },
    { x: 410, y: 330 },
    { x: 560, y: 220 },
    { x: 555, y: 88 },
    { x: 555, y: 330 },
    { x: 705, y: 135 },
    { x: 705, y: 305 },
    { x: 840, y: 220 },
  ];
  related.forEach((node, index) => {
    const slot = relatedSlots[index] || {
      x: 410 + (index % 4) * 150,
      y: index % 2 === 0 ? 105 : 330,
    };
    positioned.push({ ...node, ...slot, kind: "account" });
  });

  const entitySlots = [
    { x: 735, y: 220 },
    { x: 900, y: 220 },
    { x: 735, y: 88 },
    { x: 900, y: 330 },
    { x: 900, y: 88 },
    { x: 735, y: 330 },
  ];
  rightEntities.forEach((node, index) => {
    const slot = entitySlots[index] || {
      x: 735 + (index % 2) * 165,
      y: 95 + (index % 3) * 118,
    };
    positioned.push({ ...node, ...slot, kind: graphNodeKind(node) });
  });

  return positioned;
};

const graphNodeKind = (node) => {
  const value = `${node.type || ""} ${node.label || ""}`.toLowerCase();
  if (value.includes("device") || value.includes("ip") || value.includes("email")) {
    return "device";
  }
  if (value.includes("exchange") || value.includes("crypto")) {
    return "exchange";
  }
  if (value.includes("merchant") || value.includes("counterparty")) {
    return "merchant";
  }
  return "account";
};

const graphRiskLabel = (node) => {
  if (node.type === "trigger_transaction") {
    return "High Risk";
  }
  if (node.risk === "low") {
    return "Low Risk";
  }
  if (node.risk === "medium") {
    return "Medium Risk";
  }
  return node.risk === "shared" ? "Shared Signal" : "High Risk";
};

const renderFraudMapNode = (node) => {
  const label = escapeHtml(String(node.label || node.id).slice(0, 18));
  const detail = escapeHtml(String(node.id || "").slice(-6).padStart(6, "*"));
  const risk = graphRiskLabel(node);
  const riskClass = risk.toLowerCase().replaceAll(" ", "-");
  return `
    <g class="map-node ${node.kind} ${riskClass}" tabindex="0" transform="translate(${node.x} ${node.y})">
      <circle class="map-node-glow" r="51"></circle>
      <circle class="map-node-bubble" r="40"></circle>
      ${renderFraudMapIcon(node.kind)}
      <text class="map-node-label" y="72">${label}</text>
      <text class="map-node-detail" y="97">${detail}</text>
      <text class="map-node-risk" y="126">${escapeHtml(risk)}</text>
    </g>
  `;
};

const renderFraudMapIcon = (kind) => {
  if (kind === "device") {
    return '<rect class="map-icon" x="-12" y="-22" width="24" height="44" rx="5"></rect><line class="map-icon" x1="-7" y1="16" x2="7" y2="16"></line>';
  }
  if (kind === "merchant") {
    return '<path class="map-icon filled" d="M-20 -13h30l15 17h-8l-9 20h-24z"></path>';
  }
  if (kind === "exchange") {
    return '<rect class="map-icon filled" x="-22" y="6" width="9" height="18"></rect><rect class="map-icon filled" x="-5" y="-6" width="10" height="30"></rect><rect class="map-icon filled" x="14" y="-20" width="9" height="44"></rect><line class="map-icon" x1="-26" y1="0" x2="26" y2="0"></line>';
  }
  return '<circle class="map-icon filled" cx="0" cy="-12" r="10"></circle><path class="map-icon filled" d="M-21 20c4-14 12-20 21-20s17 6 21 20z"></path>';
};

const disposeNetworkGraph3d = () => {
  if (!networkGraph3dState) {
    return;
  }
  cancelAnimationFrame(networkGraph3dState.animationFrame);
  networkGraph3dState.cleanup.forEach((cleanup) => cleanup());
  networkGraph3dState.scene.traverse((object) => {
    object.geometry?.dispose?.();
    if (Array.isArray(object.material)) {
      object.material.forEach((material) => material.dispose?.());
    } else {
      object.material?.dispose?.();
    }
    object.material?.map?.dispose?.();
  });
  networkGraph3dState.renderer.dispose();
  networkGraph3dState = null;
};

const mountNetworkGraph3d = (graph) => {
  disposeNetworkGraph3d();
  const renderToken = (networkGraphRenderToken += 1);
  if (!graph?.nodes?.length) {
    return;
  }

  const viewport = document.querySelector(".network-graph-viewport");
  const selection = document.querySelector(".graph-selection");
  if (!viewport || !selection) {
    return;
  }

  viewport.classList.add("loading");
  loadThree()
    .then((THREE) => {
      if (!document.body.contains(viewport) || renderToken !== networkGraphRenderToken) {
        return;
      }
      viewport.classList.remove("loading");
      networkGraph3dState = createNetworkGraph3d(THREE, graph, viewport, selection);
    })
    .catch(() => {
      if (renderToken !== networkGraphRenderToken) {
        return;
      }
      viewport.classList.remove("loading");
      viewport.innerHTML = `
        <div class="item error-state">
          <strong>3D graph unavailable</strong>
          <p>The graph data is available, but the Three.js runtime could not be loaded.</p>
        </div>
      `;
    });
};

const createNetworkGraph3d = (THREE, graph, viewport, selection) => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x06101b);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 1.1, 18.6);

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  viewport.replaceChildren(renderer.domElement);

  const graphGroup = new THREE.Group();
  graphGroup.rotation.x = -0.42;
  graphGroup.rotation.y = 0.68;
  scene.add(graphGroup);

  const ambientLight = new THREE.AmbientLight(0xffffff, 1.45);
  scene.add(ambientLight);
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
  keyLight.position.set(4, 5, 6);
  scene.add(keyLight);
  const fillLight = new THREE.PointLight(0x0f766e, 1.1, 16);
  fillLight.position.set(-4, -2, 4);
  scene.add(fillLight);

  const nodeMeshes = [];
  // The backend supplies graph semantics; the frontend only lays them out for inspection.
  const positionedNodes = positionGraphNodes3d(THREE, graph.nodes.slice(0, 18));
  const nodeById = new Map(positionedNodes.map((node) => [node.id, node]));
  const edgeMaterial = new THREE.MeshStandardMaterial({
    color: 0x8fa1b5,
    roughness: 0.62,
    metalness: 0.08,
    transparent: true,
    opacity: 0.72,
  });

  (graph.edges || [])
    .filter((edge) => nodeById.has(edge.source) && nodeById.has(edge.target))
    .slice(0, 44)
    .forEach((edge) => {
      graphGroup.add(
        createEdgeMesh(
          THREE,
          nodeById.get(edge.source).position,
          nodeById.get(edge.target).position,
          edgeMaterial,
        ),
      );
    });

  positionedNodes.forEach((node) => {
    const icon = createIconNodeSprite(THREE, node);
    icon.position.copy(node.position);
    icon.userData = { node, baseScale: icon.scale.clone() };
    nodeMeshes.push(icon);
    graphGroup.add(icon);

    const label = createLabelSprite(THREE, node);
    label.position.copy(node.position).add(new THREE.Vector3(0, -1.15, 0.08));
    graphGroup.add(label);
  });

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const controls = {
    dragging: false,
    moved: false,
    lastX: 0,
    lastY: 0,
    targetRotationX: graphGroup.rotation.x,
    targetRotationY: graphGroup.rotation.y,
  };
  const cleanup = [];

  const resize = () => {
    const rect = viewport.getBoundingClientRect();
    const width = Math.max(Math.floor(rect.width), 320);
    const height = Math.max(Math.floor(rect.height), 300);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };

  const onPointerDown = (event) => {
    controls.dragging = true;
    controls.moved = false;
    controls.lastX = event.clientX;
    controls.lastY = event.clientY;
    viewport.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event) => {
    if (!controls.dragging) {
      return;
    }
    const dx = event.clientX - controls.lastX;
    const dy = event.clientY - controls.lastY;
    controls.moved = controls.moved || Math.abs(dx) + Math.abs(dy) > 4;
    controls.targetRotationY += dx * 0.008;
    controls.targetRotationX = Math.max(-1.15, Math.min(1.15, controls.targetRotationX + dy * 0.006));
    controls.lastX = event.clientX;
    controls.lastY = event.clientY;
  };
  const onPointerUp = (event) => {
    controls.dragging = false;
    viewport.releasePointerCapture?.(event.pointerId);
    if (!controls.moved) {
      selectGraphNode(THREE, event, viewport, camera, graphGroup, raycaster, pointer, nodeMeshes, selection);
    }
  };
  const onWheel = (event) => {
    event.preventDefault();
    camera.position.z = Math.max(10.8, Math.min(28, camera.position.z + event.deltaY * 0.01));
  };
  const onReset = () => {
    controls.targetRotationX = -0.42;
    controls.targetRotationY = 0.68;
    camera.position.set(0, 1.1, 18.6);
    updateGraphSelection(selection, null, graph);
  };
  const onZoomIn = () => {
    camera.position.z = Math.max(10.8, camera.position.z - 1.4);
  };
  const onZoomOut = () => {
    camera.position.z = Math.min(28, camera.position.z + 1.4);
  };
  const resetButton = document.querySelector("#reset-graph-view");
  const localResetButton = viewport.closest(".network-graph-stage")?.querySelector(".graph-reset");
  const zoomInButton = viewport.closest(".network-graph-stage")?.querySelector(".graph-zoom-in");
  const zoomOutButton = viewport.closest(".network-graph-stage")?.querySelector(".graph-zoom-out");

  viewport.addEventListener("pointerdown", onPointerDown);
  viewport.addEventListener("pointermove", onPointerMove);
  viewport.addEventListener("pointerup", onPointerUp);
  viewport.addEventListener("wheel", onWheel, { passive: false });
  window.addEventListener("resize", resize);
  resetButton?.addEventListener("click", onReset);
  localResetButton?.addEventListener("click", onReset);
  zoomInButton?.addEventListener("click", onZoomIn);
  zoomOutButton?.addEventListener("click", onZoomOut);
  cleanup.push(
    () => viewport.removeEventListener("pointerdown", onPointerDown),
    () => viewport.removeEventListener("pointermove", onPointerMove),
    () => viewport.removeEventListener("pointerup", onPointerUp),
    () => viewport.removeEventListener("wheel", onWheel),
    () => window.removeEventListener("resize", resize),
    () => resetButton?.removeEventListener("click", onReset),
    () => localResetButton?.removeEventListener("click", onReset),
    () => zoomInButton?.removeEventListener("click", onZoomIn),
    () => zoomOutButton?.removeEventListener("click", onZoomOut),
  );

  updateGraphSelection(selection, null, graph);
  resize();

  const animate = () => {
    graphGroup.rotation.x += (controls.targetRotationX - graphGroup.rotation.x) * 0.12;
    graphGroup.rotation.y += (controls.targetRotationY - graphGroup.rotation.y) * 0.12;
    if (!controls.dragging) {
      controls.targetRotationY += 0.0014;
    }
    renderer.render(scene, camera);
    networkGraph3dState.animationFrame = requestAnimationFrame(animate);
  };

  const state = {
    animationFrame: requestAnimationFrame(animate),
    cleanup,
    renderer,
    scene,
  };
  networkGraph3dState = state;
  return state;
};

const positionGraphNodes3d = (THREE, nodes) => {
  if (!nodes.length) {
    return [];
  }
  // A spherical scatter keeps shared fraud infrastructure readable as a true 3D graph.
  const trigger = nodes.find((node) => node.type === "trigger_transaction") || nodes[0];
  const others = nodes.filter((node) => node.id !== trigger.id);
  const relatedNodes = others.filter((node) => node.type === "related_transaction");
  const entityNodes = others.filter((node) => node.type !== "related_transaction");
  const orderedNodes = [...relatedNodes, ...entityNodes];
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const scatterPosition = (index, total, radius, phase) => {
    const count = Math.max(total, 1);
    const t = count === 1 ? 0.5 : index / (count - 1);
    const unitY = 1 - t * 2;
    const ring = Math.sqrt(Math.max(0, 1 - unitY * unitY));
    const theta = index * goldenAngle + phase;
    return new THREE.Vector3(
      Math.cos(theta) * ring * radius * 1.35,
      unitY * radius * 0.98,
      Math.sin(theta) * ring * radius * 1.55,
    );
  };
  const positioned = [
    {
      ...trigger,
      kind: graphNodeKind(trigger),
      position: new THREE.Vector3(0, 0, 0.35),
    },
  ];

  orderedNodes.forEach((node, index) => {
    const isRelated = node.type === "related_transaction";
    const radius = (isRelated ? 7.2 : 6.4) + (index % 4) * 0.58;
    const phase = isRelated ? 0.35 : 1.95;
    const position = scatterPosition(index, orderedNodes.length, radius, phase);
    position.x += ((index % 3) - 1) * 0.62;
    position.y += isRelated ? 0.56 : -0.48;
    position.z += ((index % 5) - 2) * 0.9;
    positioned.push({
      ...node,
      kind: graphNodeKind(node),
      position,
    });
  });
  return positioned;
};

const createEdgeMesh = (THREE, source, target, material) => {
  const direction = new THREE.Vector3().subVectors(target, source);
  const length = Math.max(direction.length(), 0.001);
  const geometry = new THREE.CylinderGeometry(0.014, 0.014, length, 10);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(source).add(target).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
  return mesh;
};

const graphKindPalette = (kind) => {
  if (kind === "device") {
    return { fill: "#14532d", stroke: "#67d06a", icon: "#b8f7b4" };
  }
  if (kind === "merchant") {
    return { fill: "#7c4a0d", stroke: "#ffab38", icon: "#ffd08a" };
  }
  if (kind === "exchange") {
    return { fill: "#4c1d95", stroke: "#8b5cf6", icon: "#c4b5fd" };
  }
  return { fill: "#0e4fa8", stroke: "#2f93ff", icon: "#c8e2ff" };
};

const createIconNodeSprite = (THREE, node) => {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  const palette = graphKindPalette(node.kind);
  const center = size / 2;

  context.shadowColor = palette.stroke;
  context.shadowBlur = 28;
  context.fillStyle = `${palette.fill}cc`;
  context.strokeStyle = palette.stroke;
  context.lineWidth = 9;
  context.beginPath();
  context.arc(center, center, 72, 0, Math.PI * 2);
  context.fill();
  context.stroke();

  context.shadowBlur = 0;
  context.fillStyle = palette.icon;
  context.strokeStyle = palette.icon;
  context.lineCap = "round";
  context.lineJoin = "round";
  if (node.kind === "device") {
    context.lineWidth = 8;
    context.beginPath();
    context.roundRect(102, 72, 52, 96, 10);
    context.stroke();
    context.beginPath();
    context.moveTo(116, 148);
    context.lineTo(140, 148);
    context.stroke();
  } else if (node.kind === "merchant") {
    context.beginPath();
    context.moveTo(76, 90);
    context.lineTo(144, 90);
    context.lineTo(184, 130);
    context.lineTo(168, 130);
    context.lineTo(148, 172);
    context.lineTo(88, 172);
    context.closePath();
    context.fill();
  } else if (node.kind === "exchange") {
    context.fillRect(78, 138, 24, 42);
    context.fillRect(116, 112, 24, 68);
    context.fillRect(154, 84, 24, 96);
  } else {
    context.beginPath();
    context.arc(128, 98, 26, 0, Math.PI * 2);
    context.fill();
    context.beginPath();
    context.moveTo(74, 170);
    context.quadraticCurveTo(128, 110, 182, 170);
    context.closePath();
    context.fill();
  }

  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(material);
  const scale = node.type === "trigger_transaction" ? 1.75 : 1.48;
  sprite.scale.set(scale, scale, 1);
  return sprite;
};

const createLabelSprite = (THREE, node) => {
  const canvas = document.createElement("canvas");
  canvas.width = 384;
  canvas.height = 150;
  const context = canvas.getContext("2d");
  const label = String(node.label || node.id).slice(0, 22);
  const detail = String(node.id || "").slice(-6).padStart(6, "*");
  const risk = graphRiskLabel(node);

  context.shadowColor = "rgba(0, 0, 0, 0.95)";
  context.shadowBlur = 9;
  context.fillStyle = "#edf6ff";
  context.font = "900 35px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, 192, 38);
  context.fillStyle = "#c8d7e8";
  context.font = "800 24px Inter, system-ui, sans-serif";
  context.fillText(detail, 192, 72);
  context.fillStyle = risk === "High Risk" ? "#ff5d55" : "#3fb7ff";
  context.font = "900 27px Inter, system-ui, sans-serif";
  context.fillText(risk.toUpperCase(), 192, 112);

  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(2.5, 0.98, 1);
  return sprite;
};

const selectGraphNode = (
  THREE,
  event,
  viewport,
  camera,
  graphGroup,
  raycaster,
  pointer,
  nodeMeshes,
  selection,
) => {
  const rect = viewport.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const intersections = raycaster.intersectObjects(nodeMeshes, false);
  nodeMeshes.forEach((mesh) => {
    if (mesh.userData.baseScale) {
      mesh.scale.copy(mesh.userData.baseScale);
    } else {
      mesh.scale.setScalar(1);
    }
  });
  if (!intersections.length) {
    updateGraphSelection(selection, null);
    return;
  }
  const mesh = intersections[0].object;
  if (mesh.userData.baseScale) {
    mesh.scale.copy(mesh.userData.baseScale).multiplyScalar(1.16);
  } else {
    mesh.scale.setScalar(1.22);
  }
  updateGraphSelection(selection, mesh.userData.node);
  graphGroup.rotation.y += 0.02;
};

const updateGraphSelection = (selection, node, graph) => {
  if (!selection) {
    return;
  }
  if (!node) {
    selection.innerHTML = `
      <span>Selected Node</span>
      <strong>Network Overview</strong>
      <p>${graph?.nodes?.length || 0} nodes · ${graph?.edges?.length || 0} edges · Live shared graph</p>
    `;
    return;
  }
  selection.innerHTML = `
    <span>${titleCase(node.type)}</span>
    <strong>${escapeHtml(node.label)}</strong>
    <p>${titleCase(node.risk || "linked")} signal · ${escapeHtml(node.id)}</p>
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

const renderInvestigationProgress = (plan) => {
  const progress = document.querySelector("#investigation-progress");
  if (!progress) {
    return;
  }
  const steps = plan?.steps?.length
    ? plan.steps.filter((step) => step.action !== "replan_after_triage")
    : [
        { action: "score_transaction", status: "planned", agent_id: "triage-agent" },
        { action: "search_related_transactions", status: "planned", agent_id: "network-agent" },
        { action: "build_evidence_timeline", status: "planned", agent_id: "evidence-agent" },
        { action: "check_policy_and_pii", status: "planned", agent_id: "compliance-agent" },
        { action: "request_supervisor_approval", status: "planned", agent_id: "case-manager-agent" },
      ];

  progress.innerHTML = `
    <svg class="progress-lines" aria-hidden="true"></svg>
    ${steps
      .map(
        (step) => `
        <div class="progress-step ${step.status}">
          <span></span>
          <strong>${titleCase(step.action)}</strong>
          <p>${titleCase(step.status)} · ${titleCase(step.agent_id)}</p>
        </div>
      `,
      )
      .join("")}
  `;
  requestAnimationFrame(() => drawProgressConnectors(progress));
};

const drawProgressConnectors = (progress) => {
  const svg = progress.querySelector(".progress-lines");
  const nodes = [...progress.querySelectorAll(".progress-step span")];
  if (!svg || nodes.length < 2) {
    return;
  }

  const bounds = progress.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
  svg.setAttribute("width", String(bounds.width));
  svg.setAttribute("height", String(bounds.height));
  svg.innerHTML = nodes
    .slice(0, -1)
    .map((node, index) => {
      const current = node.getBoundingClientRect();
      const next = nodes[index + 1].getBoundingClientRect();
      const x1 = current.left + current.width / 2 - bounds.left;
      const y1 = current.top + current.height / 2 - bounds.top;
      const x2 = next.left + next.width / 2 - bounds.left;
      const y2 = next.top + next.height / 2 - bounds.top;
      return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" />`;
    })
    .join("");
};

const renderAgentRegistry = (agents) => {
  registryAgents = agents;
  const query = (document.querySelector("#agent-registry-search")?.value || "").trim().toLowerCase();
  const enriched = agents.map(enrichAgentIdentity);
  const visibleAgents = query
    ? enriched.filter((agent) =>
        [
          agent.display_name,
          agent.agent_id,
          agent.owner_department,
          agent.lifecycle_status,
          agent.deployed_runtime,
          agent.managed_gateway_policy,
          agent.identity_provider,
          agent.identity_status,
          agent.runtime_resource,
          agent.data_region,
          agent.service_account,
          agent.agent_principal,
          ...agent.permissions,
          ...agent.data_access,
          ...agent.allowed_tools,
        ]
          .join(" ")
          .toLowerCase()
          .includes(query),
      )
    : enriched;
  document.querySelector("#agent-registry").innerHTML = `
    <div class="registry-toolbar">
      <input id="agent-registry-search" type="search" placeholder="Search agents" value="${escapeHtml(query)}" />
      <span>${visibleAgents.length}/${agents.length} registry entries</span>
    </div>
    <div class="registry-list">
      ${
        visibleAgents
    .map(
      (agent) => `
        <article class="registry-card">
          <header>
            <h3>${agent.display_name}</h3>
            <span class="chip">${titleCase(agent.lifecycle_status)}</span>
          </header>
          <dl class="registry-meta">
            <div><dt>Version</dt><dd>${agent.version}</dd></div>
            <div><dt>Approved</dt><dd>${agent.approved_version || agent.version}</dd></div>
            <div><dt>Owner</dt><dd>${agent.owner_department}</dd></div>
            <div><dt>Runtime</dt><dd>${agent.deployed_runtime}</dd></div>
            <div><dt>Identity</dt><dd>${titleCase(agent.identity_status)}</dd></div>
            <div><dt>Region</dt><dd>${agent.data_region}</dd></div>
            <div><dt>Health</dt><dd>${titleCase(agent.health_status)}</dd></div>
          </dl>
          <p><strong>Managed Gateway</strong> ${escapeHtml(agent.managed_gateway_policy)}</p>
          <p><strong>IAM Principal</strong></p>
          <code>${escapeHtml(agent.service_account)}</code>
          <p><strong>Agent Identity</strong></p>
          <code>${escapeHtml(agent.agent_principal || "Pending Agent Runtime SPIFFE binding")}</code>
          <p><strong>Runtime Resource</strong></p>
          <code>${escapeHtml(agent.runtime_resource || "Pending Agent Engine deployment")}</code>
          <p><strong>Registry Resource</strong></p>
          <code>${escapeHtml(agent.registry_resource || "Pending registration")}</code>
          <p><strong>Allowed Tools</strong></p>
          <div class="chip-row">
            ${(agent.allowed_tools || []).map((tool) => `<span class="chip">${titleCase(tool)}</span>`).join("")}
          </div>
          <p><strong>Permissions</strong></p>
          <div class="chip-row">
            ${agent.permissions.map((permission) => `<span class="chip">${permission}</span>`).join("")}
          </div>
          <p><strong>Data Classes</strong></p>
          <div class="chip-row">
            ${agent.data_access.map((access) => `<span class="chip">${titleCase(access)}</span>`).join("")}
          </div>
        </article>
      `,
    )
    .join("") || '<div class="item"><strong>No matching agents</strong><p>Try network, fraud, compliance, approval, or evidence.</p></div>'
      }
    </div>
  `;
};

const enrichAgentIdentity = (agent) => {
  return {
    owner_department: "Fraud Operations",
    lifecycle_status: "approved",
    approved_version: agent.version,
    deployed_runtime: "cloud-run-adk-runner",
    allowed_tools: [],
    data_region: "us-central1",
    registry_resource: null,
    runtime_resource: null,
    agent_principal: null,
    identity_provider: "google-cloud-iam",
    identity_status: "metadata_declared",
    managed_gateway_policy: "audit-only",
    health_status: "healthy",
    ...agent,
  };
};

const activateDashboardTab = (tabName) => {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const active = button.dataset.tab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    const active = panel.dataset.tabPanel === tabName;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
};

const handleDashboardTabClick = (event) => {
  const button = event.target.closest("[data-tab]");
  if (!button) {
    return;
  }
  activateDashboardTab(button.dataset.tab);
};

const renderTimeline = (items) =>
  (items || [])
    .map(
      (item) => `
        <div class="event">
          <time>${new Date(item.timestamp).toLocaleString()}</time>
          <div>
            <strong>${titleCase(item.event_type)}</strong>
            <p>${escapeHtml(item.description)}</p>
          </div>
        </div>
      `,
    )
    .join("") || '<div class="item"><strong>No evidence</strong><p>No timeline events were recorded.</p></div>';

const renderComplianceFindings = (items) =>
  (items || [])
    .map(
      (item) => `
        <div class="item">
          <strong>${titleCase(item.severity)}: ${escapeHtml(item.finding_id)}</strong>
          <p>${escapeHtml(item.description)} ${escapeHtml(item.required_action)}</p>
        </div>
      `,
    )
    .join("") || '<div class="item"><strong>No findings</strong><p>No compliance findings were recorded.</p></div>';

const renderCase = (caseData) => {
  currentCaseId = caseData.case_id;
  localStorage.setItem("tracelayer.currentCaseId", currentCaseId);

  document.querySelector("#case-id").textContent = caseData.case_id;
  document.querySelector("#case-status").textContent = titleCase(caseData.status);
  document.querySelector("#risk-score").textContent = caseData.risk_score;
  document.querySelector("#priority").textContent = titleCase(caseData.priority);
  document.querySelector("#audit-tip").textContent = caseData.audit_chain_tip ? "Recorded" : "Pending";
  renderInvestigationProgress(caseData.investigation_plan);

  document.querySelector("#agent-findings").innerHTML = caseData.agent_outputs
    .map(
      (item) => {
        const summary = escapeHtml(conciseSummary(item.summary));
        return `
        <div class="item">
          <strong>${titleCase(item.agent_id)}</strong>
          <p>${summary}</p>
          ${renderPlannerRuntime(item.data?.planner_runtime)}
          ${renderModelArmorDemo(item.data?.model_armor_demo)}
          ${renderAdkRuntime(item.data?.adk_runtime)}
        </div>
      `;
      },
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
  mountNetworkGraph3d(networkOutput?.data?.network_graph);
  document.querySelector("#campaign-detection").innerHTML = renderCampaignDetection(
    networkOutput?.data?.campaign_detection,
  );

  const signal = caseData.federated_risk_signal;
  const linkCount = caseData.network_links?.length || 0;
  const evidenceCount = caseData.evidence_timeline?.length || 0;
  const topPattern = signal?.node_indicators?.[0]
    ? titleCase(signal.node_indicators[0].split(":").pop())
    : "No External Pattern";
  const federatedHtml = signal
    ? `
      <div class="federated-section">
        <h3>Federated Intelligence</h3>
        <div class="metric-grid">
          <div class="metric">
            <span>Federated Risk</span>
            <strong>${signal.federated_risk_score}%</strong>
          </div>
          <div class="metric">
            <span>Pattern Match</span>
            <strong>${signal.federated_risk_score >= 80 ? "High" : "Medium"}</strong>
          </div>
          <div class="metric">
            <span>Contributing Institutions</span>
            <strong>${signal.participating_nodes.length}</strong>
          </div>
          <div class="metric">
            <span>Pattern</span>
            <strong>${topPattern}</strong>
          </div>
          <div class="metric privacy-metric">
            <span>External Customer Records Exposed</span>
            <strong>0</strong>
          </div>
          <div class="metric">
            <span>Privacy Protection</span>
            <strong>Secure Aggregation + DP</strong>
          </div>
        </div>
        <details class="advanced-details">
          <summary>Advanced Details</summary>
          <div class="privacy-list">
            <div><strong>Secure Aggregation</strong><p>${titleCase(signal.secure_aggregation.server_observes)}</p></div>
            <div><strong>DP Epsilon</strong><p>${signal.differential_privacy.epsilon}</p></div>
            <div><strong>Provenance</strong><p>${signal.provenance_hash.slice(0, 16)}...</p></div>
            <div><strong>Campaign</strong><p>${signal.campaign_signature}</p></div>
          </div>
        </details>
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
  document.querySelector("#federated-signal").innerHTML = federatedHtml;
  document.querySelector("#federated-detail").innerHTML = federatedHtml;

  const timelineHtml = renderTimeline(caseData.evidence_timeline);
  document.querySelector("#timeline").innerHTML = timelineHtml;
  document.querySelector("#evidence-tab-timeline").innerHTML = timelineHtml;

  const complianceHtml = renderComplianceFindings(caseData.compliance_findings);
  document.querySelector("#compliance").innerHTML = complianceHtml;
  document.querySelector("#compliance-detail").innerHTML = complianceHtml;

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
    : caseData.status === "paused"
      ? `
        <strong>Paused</strong>
        <p>This long-running investigation is stored in memory while it waits for missing source data.</p>
        <button class="secondary-action" type="button" data-provide-missing-data="${escapeHtml(caseData.case_id)}">Provide Missing Data</button>
      `
      : "<p>No approval request has been created.</p>";
  document.querySelector("#audit-summary").innerHTML = `
    <div class="item">
      <strong>Audit Chain</strong>
      <p>${escapeHtml(caseData.audit_chain_tip || "Pending")}</p>
    </div>
    <div class="item">
      <strong>Memory Snapshot</strong>
      <p>${escapeHtml(caseData.memory_snapshot_id || "Pending")}</p>
    </div>
    <div class="item">
      <strong>Report</strong>
      <p>${escapeHtml(caseData.report_path || "Not generated")}</p>
    </div>
  `;
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
    const armor = config.model_armor_backend === "google"
      ? `Model Armor ${config.model_armor_template_configured ? "configured" : "missing template"}`
      : "local guardrail";
    status.dataset.backendStatus = `Backend: ${config.ai_provider} / ${config.gemini_model} · ${adk} · ${pubsub} · ${armor}`;
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

const runMissingDataDemo = async () => {
  const button = document.querySelector("#run-missing-data-demo");
  button.disabled = true;
  button.textContent = "Pausing...";

  try {
    const response = await fetch(`${API_BASE_URL}/cases/investigate`, {
      method: "POST",
      headers: {
        ...apiHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ transaction_id: "tx-9801" }),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const caseData = await response.json();
    renderCase(caseData);
    publishCaseUpdate(caseData, "dashboard.paused_demo");
  } catch (error) {
    renderCase(fallbackCase);
  } finally {
    button.disabled = false;
    button.textContent = "Run Paused Demo";
  }
};

const startLongRunningDemo = async () => {
  const button = document.querySelector("#start-long-running-demo");
  button.disabled = true;
  button.textContent = "Starting...";

  try {
    const response = await fetch(`${API_BASE_URL}/cases/long-running-demo`, {
      method: "POST",
      headers: apiHeaders(),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const caseData = await response.json();
    renderCase(caseData);
    publishCaseUpdate(caseData, "dashboard.long_running_start");
    setLiveStatus("Long case: Day 1 stored");
  } catch (error) {
    renderCase(fallbackCase);
  } finally {
    button.disabled = false;
    button.textContent = "Start Long Case";
  }
};

const advanceLongRunningDemo = async () => {
  const button = document.querySelector("#advance-long-running-demo");
  button.disabled = true;
  button.textContent = "Advancing...";

  try {
    const response = await fetch(
      `${API_BASE_URL}/cases/${encodeURIComponent(currentCaseId)}/long-running/advance`,
      {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "next" }),
      },
    );
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const caseData = await response.json();
    renderCase(caseData);
    publishCaseUpdate(caseData, "dashboard.long_running_advance");
    const latestLongEvent = [...(caseData.evidence_timeline || [])]
      .reverse()
      .find((event) => String(event.event_type || "").startsWith("day_"));
    setLiveStatus(`Long case: ${titleCase(latestLongEvent?.event_type || "advanced")}`);
  } catch (error) {
    setLiveStatus("Long case: start a long case first");
  } finally {
    button.disabled = false;
    button.textContent = "Advance Day";
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

const provideMissingData = async (caseId) => {
  const button = document.querySelector("[data-provide-missing-data]");
  if (button) {
    button.disabled = true;
    button.textContent = "Resuming...";
  }
  try {
    const response = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}/missing-data`, {
      method: "POST",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({
        reason:
          "External event supplied beneficiary account, amount, device fingerprint, and IP records for the paused case.",
      }),
    });
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const caseData = await response.json();
    renderCase(caseData);
    publishCaseUpdate(caseData, "dashboard.provide_missing_data");
  } catch (error) {
    if (button) {
      button.disabled = false;
      button.textContent = "Provide Missing Data";
    }
  }
};

const handleProvideMissingDataClick = (event) => {
  const button = event.target.closest("[data-provide-missing-data]");
  if (!button) {
    return;
  }
  provideMissingData(button.dataset.provideMissingData);
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

window.addEventListener("resize", () => {
  const progress = document.querySelector("#investigation-progress");
  if (progress) {
    requestAnimationFrame(() => drawProgressConnectors(progress));
  }
});

document.querySelector("#run-demo").addEventListener("click", runDemo);
document.querySelector("#run-attack-demo").addEventListener("click", runAttackDemo);
document.querySelector("#run-async-demo").addEventListener("click", runAsyncDemo);
document.querySelector("#run-missing-data-demo").addEventListener("click", runMissingDataDemo);
document.querySelector("#start-long-running-demo").addEventListener("click", startLongRunningDemo);
document.querySelector("#advance-long-running-demo").addEventListener("click", advanceLongRunningDemo);
document.addEventListener("click", handleFraudMapControlClick);
document.addEventListener("click", handleDashboardTabClick);
document.addEventListener("click", handleProvideMissingDataClick);
document.addEventListener("input", (event) => {
  if (event.target?.id === "agent-registry-search") {
    renderAgentRegistry(registryAgents);
  }
});
renderCase(fallbackCase);
loadRuntimeConfig();
loadAgentRegistry();
loadCurrentCase();

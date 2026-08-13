const DEFAULT_API_BASE_URL =
  window.TRACELAYER_API_BASE ||
  localStorage.getItem("tracelayer.apiBaseUrl") ||
  (window.location.protocol.startsWith("http")
    ? window.location.origin
    : "http://localhost:8080");

const adminState = {
  apiBaseUrl: DEFAULT_API_BASE_URL,
  apiKey: localStorage.getItem("tracelayer.apiKey") || "",
  supervisorId: localStorage.getItem("tracelayer.supervisorId") || "supervisor@example.com",
  pendingApprovals: [],
  approvalLog: [],
  riskPolicy: null,
  selectedCase: null,
};
const liveChannel = "BroadcastChannel" in window ? new BroadcastChannel("tracelayer-live") : null;

const titleCase = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const headers = () => {
  const requestHeaders = {
    "X-Tracelayer-User": adminState.supervisorId,
    "X-Tracelayer-Role": "supervisor",
  };
  if (adminState.apiKey) {
    requestHeaders["X-API-Key"] = adminState.apiKey;
  }
  return requestHeaders;
};

const setText = (selector, value) => {
  document.querySelector(selector).textContent = value;
};

const setRiskPolicyFeedback = (message, state = "neutral") => {
  const node = document.querySelector("#risk-policy-feedback");
  node.textContent = message;
  node.className = `risk-policy-feedback ${state}`;
};

const buildApiUrl = (path) => `${adminState.apiBaseUrl.replace(/\/+$/, "")}${path}`;

const clearChildren = (node) => {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
};

const createNode = (tagName, className, text) => {
  const node = document.createElement(tagName);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
};

const applySettingsToForm = () => {
  document.querySelector("#api-base-url").value = adminState.apiBaseUrl;
  document.querySelector("#api-key").value = adminState.apiKey;
  document.querySelector("#supervisor-id").value = adminState.supervisorId;
};

const saveSettings = () => {
  adminState.apiBaseUrl = (
    document.querySelector("#api-base-url").value.trim() || DEFAULT_API_BASE_URL
  ).replace(/\/+$/, "");
  adminState.apiKey = document.querySelector("#api-key").value.trim();
  adminState.supervisorId =
    document.querySelector("#supervisor-id").value.trim() || "supervisor@example.com";

  localStorage.setItem("tracelayer.apiBaseUrl", adminState.apiBaseUrl);
  localStorage.setItem("tracelayer.apiKey", adminState.apiKey);
  localStorage.setItem("tracelayer.supervisorId", adminState.supervisorId);
  setText("#last-action", "Settings Saved");
  loadRuntimeConfig();
  loadRiskPolicy();
  loadPendingApprovals();
  loadApprovalLog();
};

const apiFetch = async (path, options = {}) => {
  const response = await fetch(buildApiUrl(path), {
    ...options,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `API returned ${response.status}`);
  }

  return response.json();
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

const loadRuntimeConfig = async () => {
  try {
    const config = await apiFetch("/runtime/config");
    setText("#admin-runtime-status", `Backend: ${config.ai_provider} / ${config.gemini_model}`);
  } catch (error) {
    setText("#admin-runtime-status", "Backend: unavailable");
  }
};

const renderRiskPolicyForm = () => {
  if (!adminState.riskPolicy) {
    return;
  }

  document.querySelector("#medium-threshold").value = adminState.riskPolicy.medium_threshold;
  document.querySelector("#high-threshold").value = adminState.riskPolicy.high_threshold;
  document.querySelector("#critical-threshold").value = adminState.riskPolicy.critical_threshold;
  setText(
    "#risk-policy-status",
    `Policy: ${adminState.riskPolicy.medium_threshold}/${adminState.riskPolicy.high_threshold}/${adminState.riskPolicy.critical_threshold} · ${adminState.riskPolicy.updated_by}`,
  );
};

const loadRiskPolicy = async () => {
  try {
    adminState.riskPolicy = await apiFetch("/risk-policy");
    renderRiskPolicyForm();
    setRiskPolicyFeedback("");
  } catch (error) {
    setText("#risk-policy-status", "Policy: unavailable");
    setRiskPolicyFeedback(error.message, "error");
  }
};

const readRiskPolicyInputs = () => {
  const medium = Number.parseInt(document.querySelector("#medium-threshold").value, 10);
  const high = Number.parseInt(document.querySelector("#high-threshold").value, 10);
  const critical = Number.parseInt(document.querySelector("#critical-threshold").value, 10);

  if ([medium, high, critical].some((value) => Number.isNaN(value))) {
    throw new Error("Enter all threshold values.");
  }
  if ([medium, high, critical].some((value) => value < 0 || value > 100)) {
    throw new Error("Thresholds must be between 0 and 100.");
  }
  if (!(medium < high && high < critical)) {
    throw new Error("Use ascending thresholds: medium < high < critical.");
  }

  return { medium, high, critical };
};

const saveRiskPolicy = async () => {
  const button = document.querySelector("#save-risk-policy");
  let thresholds;

  try {
    thresholds = readRiskPolicyInputs();
  } catch (error) {
    setRiskPolicyFeedback(error.message, "error");
    return;
  }

  button.disabled = true;
  button.textContent = "Saving";
  setRiskPolicyFeedback("Saving thresholds.", "neutral");
  try {
    adminState.riskPolicy = await apiFetch("/risk-policy", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        policy_id: "default",
        medium_threshold: thresholds.medium,
        high_threshold: thresholds.high,
        critical_threshold: thresholds.critical,
        updated_by: adminState.supervisorId,
      }),
    });
    renderRiskPolicyForm();
    await loadRiskPolicy();
    await refreshAdminData();
    publishRiskPolicyUpdate(adminState.riskPolicy, "admin.risk_policy_saved");
    button.textContent = "Saved";
    document.querySelector(".risk-policy-panel").classList.add("saved");
    const savedAt = new Date(adminState.riskPolicy.updated_at).toLocaleTimeString();
    setRiskPolicyFeedback(
      `Saved ${adminState.riskPolicy.medium_threshold}/${adminState.riskPolicy.high_threshold}/${adminState.riskPolicy.critical_threshold} at ${savedAt}. New investigations use this policy.`,
      "success",
    );
    setText("#last-action", "Thresholds Saved");
  } catch (error) {
    setRiskPolicyFeedback(error.message, "error");
  } finally {
    window.setTimeout(() => {
      button.disabled = false;
      button.textContent = "Save Thresholds";
      document.querySelector(".risk-policy-panel").classList.remove("saved");
    }, 900);
  }
};

const publishRiskPolicyUpdate = (policy, source) => {
  const event = {
    type: "risk_policy.updated",
    source,
    policy,
    sent_at: new Date().toISOString(),
  };
  liveChannel?.postMessage(event);
  localStorage.setItem("tracelayer.liveRiskPolicyEvent", JSON.stringify(event));
};

const loadPendingApprovals = async () => {
  const button = document.querySelector("#refresh-approvals");
  button.disabled = true;
  button.textContent = "Refreshing";

  try {
    adminState.pendingApprovals = await apiFetch("/approvals/pending");
    if (!adminState.selectedCase && adminState.pendingApprovals.length) {
      await selectCase(adminState.pendingApprovals[0].case_id);
    }
    renderApprovalQueue();
    updateSummary();
  } catch (error) {
    renderError(error);
  } finally {
    button.disabled = false;
    button.textContent = "Refresh";
  }
};

const loadApprovalLog = async () => {
  try {
    adminState.approvalLog = await apiFetch("/approvals/log");
    renderApprovalLog();
    updateSummary();
  } catch (error) {
    renderApprovalLogError(error);
  }
};

const refreshAdminData = async () => {
  await loadPendingApprovals();
  await loadApprovalLog();
};

const selectCase = async (caseId) => {
  adminState.selectedCase = await apiFetch(`/cases/${caseId}`);
  localStorage.setItem("tracelayer.currentCaseId", caseId);
  publishCaseUpdate(adminState.selectedCase, "admin.select_case");
  renderSelectedCase();
};

const decideApproval = async (approval, decision) => {
  const reason =
    decision === "approved"
      ? "Supervisor approved the recommended high-risk action from the admin console."
      : "Supervisor denied the recommended high-risk action from the admin console.";

  const updatedCase = await apiFetch(`/cases/${approval.case_id}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      approval_id: approval.approval_id,
      decision,
      reason,
    }),
  });

  adminState.selectedCase = updatedCase;
  localStorage.setItem("tracelayer.currentCaseId", updatedCase.case_id);
  publishCaseUpdate(updatedCase, `admin.${decision}`);
  setText("#last-action", `${titleCase(decision)} ${approval.case_id}`);
  renderSelectedCase();
  await loadPendingApprovals();
  await loadApprovalLog();
};

const renderApprovalQueue = () => {
  const queue = document.querySelector("#approval-queue");
  clearChildren(queue);

  if (!adminState.pendingApprovals.length) {
    const empty = createNode("div", "empty-state");
    empty.appendChild(createNode("strong", "", "No pending approvals"));
    empty.appendChild(createNode("p", "", "All reviewed cases are out of the pending queue."));
    queue.appendChild(empty);
    return;
  }

  adminState.pendingApprovals.forEach((approval) => {
    const row = createNode("article", "approval-row");
    const body = createNode("div", "approval-row-body");
    body.appendChild(createNode("strong", "", approval.case_id));
    body.appendChild(
      createNode(
        "p",
        "",
        `${titleCase(approval.action)} · Risk ${approval.risk_score} · ${titleCase(
          approval.priority,
        )}`,
      ),
    );
    body.appendChild(createNode("p", "muted-line", approval.reason));

    const actions = createNode("div", "approval-actions");
    const viewButton = createNode("button", "secondary", "View");
    viewButton.type = "button";
    viewButton.addEventListener("click", () => selectCase(approval.case_id));

    const approveButton = createNode("button", "", "Accept");
    approveButton.type = "button";
    approveButton.addEventListener("click", () => decideApproval(approval, "approved"));

    const denyButton = createNode("button", "danger", "Deny");
    denyButton.type = "button";
    denyButton.addEventListener("click", () => decideApproval(approval, "denied"));

    actions.append(viewButton, approveButton, denyButton);
    row.append(body, actions);
    queue.appendChild(row);
  });
};

const renderSelectedCase = () => {
  const container = document.querySelector("#selected-case");
  clearChildren(container);

  if (!adminState.selectedCase) {
    const empty = createNode("div", "empty-state");
    empty.appendChild(createNode("strong", "", "No case selected"));
    empty.appendChild(createNode("p", "", "Select a pending approval to inspect its case record."));
    container.appendChild(empty);
    return;
  }

  const caseData = adminState.selectedCase;
  const triageOutput = caseData.agent_outputs.find((output) => output.agent_id === "triage-agent");
  const riskPolicy = triageOutput?.data?.risk_policy;
  const summary = createNode("div", "case-summary-list");
  [
    ["Case", caseData.case_id],
    ["Status", titleCase(caseData.status)],
    ["Risk", String(caseData.risk_score)],
    ["Priority", titleCase(caseData.priority)],
    ["Policy", riskPolicy ? `${riskPolicy.medium_threshold}/${riskPolicy.high_threshold}/${riskPolicy.critical_threshold}` : "-"],
    ["Transaction", caseData.trigger_transaction_id],
    ["Customer", caseData.customer_id],
  ].forEach(([label, value]) => {
    const item = createNode("div", "summary-item");
    item.appendChild(createNode("span", "", label));
    item.appendChild(createNode("strong", "", value));
    summary.appendChild(item);
  });

  const approval = caseData.approval_request;
  const approvalBox = createNode("div", "approval-detail");
  approvalBox.appendChild(createNode("strong", "", approval ? titleCase(approval.status) : "No Approval"));
  approvalBox.appendChild(
    createNode("p", "", approval ? `${titleCase(approval.action)}: ${approval.reason}` : ""),
  );
  if (approval?.decision_reason) {
    approvalBox.appendChild(createNode("p", "", `Decision: ${approval.decision_reason}`));
  }
  if (approval?.decided_by) {
    approvalBox.appendChild(createNode("p", "", `Reviewer: ${approval.decided_by}`));
  }

  const evidence = createNode("div", "compact-list");
  caseData.evidence_timeline.slice(0, 4).forEach((event) => {
    const item = createNode("div", "item");
    item.appendChild(createNode("strong", "", titleCase(event.event_type)));
    item.appendChild(createNode("p", "", event.description));
    evidence.appendChild(item);
  });

  container.append(summary, approvalBox, createNode("h3", "", "Evidence"), evidence);
};

const updateSummary = () => {
  const pendingCount = adminState.pendingApprovals.length;
  const completedCount = adminState.approvalLog.filter((entry) =>
    ["approved", "denied"].includes(entry.approval_status),
  ).length;
  const highestRisk = adminState.pendingApprovals.reduce(
    (max, approval) => Math.max(max, approval.risk_score),
    0,
  );

  setText("#pending-count", String(pendingCount));
  setText("#highest-risk", pendingCount ? String(highestRisk) : "-");
  if (completedCount && document.querySelector("#last-action").textContent === "None") {
    setText("#last-action", `${completedCount} Decisions`);
  }
};

const renderError = (error) => {
  const queue = document.querySelector("#approval-queue");
  clearChildren(queue);
  const errorBox = createNode("div", "empty-state error-state");
  errorBox.appendChild(createNode("strong", "", "Unable to load approvals"));
  errorBox.appendChild(createNode("p", "", error.message));
  queue.appendChild(errorBox);
  setText("#pending-count", "0");
  setText("#highest-risk", "-");
};

const renderApprovalLog = () => {
  const log = document.querySelector("#approval-log");
  clearChildren(log);

  if (!adminState.approvalLog.length) {
    const empty = createNode("div", "empty-state");
    empty.appendChild(createNode("strong", "", "No approval activity"));
    empty.appendChild(createNode("p", "", "Run demo cases and decide approvals to build this log."));
    log.appendChild(empty);
    return;
  }

  adminState.approvalLog.forEach((entry) => {
    const row = createNode("article", `log-row ${entry.approval_status}`);
    const status = createNode("span", `status-pill ${entry.approval_status}`, titleCase(entry.approval_status));
    const body = createNode("div", "log-row-body");
    body.appendChild(createNode("strong", "", entry.case_id));
    body.appendChild(
      createNode(
        "p",
        "",
        `${titleCase(entry.action)} · ${titleCase(entry.case_status)} · Risk ${entry.risk_score}`,
      ),
    );
    body.appendChild(
      createNode(
        "p",
        "muted-line",
        entry.decision_reason || entry.reason,
      ),
    );

    const meta = createNode("div", "log-meta");
    meta.appendChild(status);
    meta.appendChild(
      createNode(
        "span",
        "",
        entry.decided_at
          ? `Decided ${new Date(entry.decided_at).toLocaleString()}`
          : `Created ${new Date(entry.created_at).toLocaleString()}`,
      ),
    );

    row.append(body, meta);
    row.addEventListener("click", () => selectCase(entry.case_id));
    log.appendChild(row);
  });
};

const renderApprovalLogError = (error) => {
  const log = document.querySelector("#approval-log");
  clearChildren(log);
  const errorBox = createNode("div", "empty-state error-state");
  errorBox.appendChild(createNode("strong", "", "Unable to load approval log"));
  errorBox.appendChild(createNode("p", "", error.message));
  log.appendChild(errorBox);
};

document.querySelector("#save-settings").addEventListener("click", saveSettings);
document.querySelector("#refresh-approvals").addEventListener("click", refreshAdminData);
document.querySelector("#save-risk-policy").addEventListener("click", saveRiskPolicy);

liveChannel?.addEventListener("message", (event) => {
  if (event.data?.type === "case.updated") {
    loadPendingApprovals();
    loadApprovalLog();
  }
  if (event.data?.type === "risk_policy.updated") {
    loadRiskPolicy();
  }
});

applySettingsToForm();
renderApprovalQueue();
renderSelectedCase();
loadRuntimeConfig();
loadRiskPolicy();
loadPendingApprovals();
loadApprovalLog();

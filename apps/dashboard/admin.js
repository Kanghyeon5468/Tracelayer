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
  selectedCase: null,
};

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
  adminState.apiBaseUrl = document.querySelector("#api-base-url").value.trim() || DEFAULT_API_BASE_URL;
  adminState.apiKey = document.querySelector("#api-key").value.trim();
  adminState.supervisorId =
    document.querySelector("#supervisor-id").value.trim() || "supervisor@example.com";

  localStorage.setItem("tracelayer.apiBaseUrl", adminState.apiBaseUrl);
  localStorage.setItem("tracelayer.apiKey", adminState.apiKey);
  localStorage.setItem("tracelayer.supervisorId", adminState.supervisorId);
  setText("#last-action", "Settings Saved");
  loadRuntimeConfig();
  loadPendingApprovals();
};

const apiFetch = async (path, options = {}) => {
  const response = await fetch(`${adminState.apiBaseUrl}${path}`, {
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

const loadRuntimeConfig = async () => {
  try {
    const config = await apiFetch("/runtime/config");
    setText("#admin-runtime-status", `Backend: ${config.ai_provider} / ${config.gemini_model}`);
  } catch (error) {
    setText("#admin-runtime-status", "Backend: unavailable");
  }
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

const selectCase = async (caseId) => {
  adminState.selectedCase = await apiFetch(`/cases/${caseId}`);
  localStorage.setItem("tracelayer.currentCaseId", caseId);
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
  setText("#last-action", `${titleCase(decision)} ${approval.case_id}`);
  renderSelectedCase();
  await loadPendingApprovals();
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
  const summary = createNode("div", "case-summary-list");
  [
    ["Case", caseData.case_id],
    ["Status", titleCase(caseData.status)],
    ["Risk", String(caseData.risk_score)],
    ["Priority", titleCase(caseData.priority)],
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
  const highestRisk = adminState.pendingApprovals.reduce(
    (max, approval) => Math.max(max, approval.risk_score),
    0,
  );

  setText("#pending-count", String(pendingCount));
  setText("#highest-risk", pendingCount ? String(highestRisk) : "-");
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

document.querySelector("#save-settings").addEventListener("click", saveSettings);
document.querySelector("#refresh-approvals").addEventListener("click", loadPendingApprovals);

applySettingsToForm();
renderApprovalQueue();
renderSelectedCase();
loadRuntimeConfig();
loadPendingApprovals();

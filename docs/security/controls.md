# Security Controls

TraceLayer implements security controls as executable backend code, not only as architecture notes.

## Identity and Access

- Human actors are represented by `RequestContext`.
- API requests can include `X-Tracelayer-User` and `X-Tracelayer-Role`.
- `SECURITY_MODE=enforcing` requires `X-API-Key`.
- `PolicyEngine` maps roles to scopes and denies unsupported actions.

## Secret Boundary

The dashboard never stores or sends Gemini, Google Cloud, or API provider secrets. It only knows the TraceLayer backend URL. All live AI and Google Cloud calls happen inside the FastAPI service through one of these backend providers:

- `mock`
- `gemini_api`
- `vertex_ai`
- `auto`

`/runtime/config` exposes only non-secret runtime metadata so the dashboard can display which backend mode is active.

## Agent Least Privilege

Every agent declares `required_permissions`.

`AgentRegistry` defines:

- Agent ID
- Display name
- Version
- Service account
- Permissions
- Data classifications

`AgentGateway` denies execution when an agent requests a permission or data class that is not declared in the registry.

## Guardrails

`ModelArmorGuardrail` scans:

- Model inputs
- Agent summaries
- Prompt injection indicators
- Email-like PII
- Account identifiers
- IP addresses

Blocking findings stop the model call. Non-blocking findings are attached to the investigation case and report.

## Auditability

`AuditLedger` records:

- Human investigation requests
- Agent authorization decisions
- Agent run completion
- Case persistence
- Approval decisions

Each event contains a previous hash and event hash. Local runs keep a tamper-evident JSONL chain. Deployed runs also emit structured Cloud Logging trace entries with `case_id`, `agent_id`, `agent_version`, `tool`, `latency_ms`, and `status` fields for Cloud Run log correlation.

## Human-in-the-loop Enforcement

TraceLayer does not execute final account freezes. The Case Manager can request review, but a supervisor must approve or deny the action.

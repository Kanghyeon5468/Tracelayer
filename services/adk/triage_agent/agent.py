from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from google.adk.agents import Agent

TRACE_LAYER_API_BASE_URL = os.environ.get(
    "TRACELAYER_API_BASE_URL",
    "https://tracelayer-api-235426782310.us-central1.run.app",
).rstrip("/")
TRACE_LAYER_API_KEY = os.environ.get("TRACELAYER_API_KEY", "")

os.environ.setdefault("GOOGLE_API_USE_MTLS_ENDPOINT", "never")


def score_trace_layer_transaction(transaction_id: str = "tx-9001") -> dict[str, Any]:
    """Call the governed TraceLayer Triage invocation surface for one transaction."""
    if not transaction_id:
        return {"status": "error", "message": "transaction_id is required"}

    payload = json.dumps(
        {"transaction_id": transaction_id, "include_case": True}
    ).encode("utf-8")
    request = Request(
        f"{TRACE_LAYER_API_BASE_URL}/agents/triage-agent/invoke",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": TRACE_LAYER_API_KEY,
            "X-Tracelayer-User": "agent-engine-triage-runtime",
            "X-Tracelayer-Role": "supervisor",
        },
    )

    try:
        with urlopen(request, timeout=45) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        return {
            "status": "error",
            "http_status": exc.code,
            "message": exc.read().decode("utf-8", errors="replace"),
        }
    except URLError as exc:
        return {"status": "error", "message": str(exc.reason)}

    return json.loads(body)


root_agent = Agent(
    model=os.environ.get("ADK_MODEL", "gemini-3.5-flash"),
    name="tracelayer_triage_agent",
    description=(
        "TraceLayer's Agent Runtime Triage Agent. It scores suspicious "
        "transactions through the governed TraceLayer backend."
    ),
    instruction=(
        "You are TraceLayer's Triage Agent running on Google Agent Runtime. "
        "Use only the approved score_trace_layer_transaction tool when asked "
        "to analyze a transaction. Summarize the returned risk score, priority, "
        "case id, identity status, and managed gateway policy. Do not request "
        "or reveal raw customer records."
    ),
    tools=[score_trace_layer_transaction],
)

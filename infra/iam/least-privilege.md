# Least-Privilege IAM Plan

Each agent should run with its own service account in deployed mode.

| Service Account | Agent | Minimum Access |
| --- | --- | --- |
| `triage-agent@PROJECT_ID.iam.gserviceaccount.com` | Triage Agent | Read flagged transactions, call Vertex AI. |
| `network-agent@PROJECT_ID.iam.gserviceaccount.com` | Network Agent | Read BigQuery transaction graph tables. |
| `evidence-agent@PROJECT_ID.iam.gserviceaccount.com` | Evidence Agent | Read transactions and policies, write evidence events. |
| `compliance-agent@PROJECT_ID.iam.gserviceaccount.com` | Compliance Agent | Read policies and redacted case data. |
| `case-manager-agent@PROJECT_ID.iam.gserviceaccount.com` | Case Manager Agent | Write case state, publish approval messages, write reports. |
| `tracelayer-api@PROJECT_ID.iam.gserviceaccount.com` | Case API | Invoke approved agent jobs and read/write case metadata. |

## Deny-by-default Rules

- Agents should not have broad project editor roles.
- Agents should not share one runtime service account.
- The Case Manager should not directly mutate customer funds.
- Approval decisions must come from authenticated supervisor or compliance roles.

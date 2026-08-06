# Cloud Run Deployment Notes

The current service manifest is a deployment stub. For the hackathon demo, show the Cloud Run service, logs, and environment variables to prove the backend is running on Google Cloud.

## Recommended Flow

1. Build the container image from the repository root.
2. Push the image to Artifact Registry.
3. Deploy `tracelayer-api` with a dedicated service account.
4. Set `SECURITY_MODE=enforcing`.
5. Store API keys and Gemini credentials in Secret Manager instead of plain environment variables.

## Production Changes

- Replace local file memory with Firestore.
- Export audit events to Cloud Logging and BigQuery.
- Use Pub/Sub push or pull workers for long-running agent tasks.
- Route Gemini calls through Vertex AI with Model Armor policies.

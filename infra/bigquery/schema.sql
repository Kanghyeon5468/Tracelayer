CREATE SCHEMA IF NOT EXISTS `PROJECT_ID.fraud_investigations`;

CREATE TABLE IF NOT EXISTS `PROJECT_ID.fraud_investigations.transactions` (
  transaction_id STRING NOT NULL,
  customer_id STRING NOT NULL,
  account_id STRING NOT NULL,
  counterparty_account_id STRING NOT NULL,
  amount NUMERIC NOT NULL,
  currency STRING NOT NULL,
  country STRING NOT NULL,
  channel STRING NOT NULL,
  device_id STRING,
  ip_address STRING,
  email_hash STRING,
  event_timestamp TIMESTAMP NOT NULL,
  status STRING NOT NULL,
  risk_flags ARRAY<STRING>
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY customer_id, account_id, device_id;

CREATE TABLE IF NOT EXISTS `PROJECT_ID.fraud_investigations.audit_events` (
  event_id STRING NOT NULL,
  event_timestamp TIMESTAMP NOT NULL,
  case_id STRING,
  actor_id STRING NOT NULL,
  actor_type STRING NOT NULL,
  action STRING NOT NULL,
  resource STRING NOT NULL,
  decision STRING NOT NULL,
  reason STRING,
  previous_hash STRING NOT NULL,
  event_hash STRING NOT NULL,
  metadata JSON
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY case_id, actor_id, action;
